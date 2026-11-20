"""Device agent: the only seam for demo behavior and tests.

HTTP and the CLI are transports that call this same object. Pairing, catalog
writes, and sync happen here; the private key never leaves the process.
"""

from __future__ import annotations

import base64
import json
import logging
import random
import secrets
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from tunebag.activity import ActivityEntry, ActivityLog
from tunebag.cover_cache import CoverCache, CoverFetcher, cover_media_type
from tunebag.discovery import (
    DISCOVERY_REFRESH_SECONDS,
    LanAdvertisement,
    LanDiscovery,
    NullLanDiscovery,
)
from tunebag.domain import (
    Artist,
    Assignment,
    Device,
    DeviceHours,
    Intent,
    Mix,
    Platform,
    Playhead,
    ReleaseKind,
    Sequence,
    SkipPending,
    StarDistribution,
    Stars,
    default_intent_platforms,
    new_id,
)
from tunebag.catalog_journal import CatalogJournal
from tunebag.durable_store import open_durable_store
from tunebag.events import Event, EventLog, EventType
from tunebag.pairing import (
    PIN_MAX_ATTEMPTS,
    PIN_TTL_SECONDS,
    DeviceIdentity,
    confirm_transcript,
    ephemeral_pair_offer,
    fingerprint_from_key,
    generate_identity,
    generate_pairing_pin,
    join_transcript,
    normalize_pin,
    pairing_payload as build_pairing_payload,
    pins_equal,
    resolve_store_identity,
    sas_for_session,
)
from tunebag.player import AudioPlayer, default_player
from tunebag.playback import (
    ContinueTo,
    EmitLastHeard,
    MarkPlayed,
    PlaybackIntent,
    PlaybackSupervisor,
    ReportPlayhead,
    clamp_seek_position,
)
from tunebag.event_payloads import encode_intent, encode_mix_added
from tunebag.projection import CatalogState, LocalEffects
from tunebag.maintenance import BoundMaintenance, CatalogChange, CatalogChangeReason
from tunebag.reject import (
    SOFT_REJECT_SECONDS,
    RejectFileDeleteBuffer,
    is_soft_rejected,
)
from tunebag.release_cache import OriginFetch, ReleaseCache
from tunebag.release_layout import album_timeline_location
from tunebag.sequence_provision import SequenceProvisioner
from tunebag.skip import SkipBuffer
from tunebag.source import (
    DEFAULT_MIN_DURATION_SECONDS,
    Source,
    bandcamp_normalize_artist_url,
    default_source,
    release_from_upload,
    youtube_normalize_artist_url,
)
from tunebag.title_display import display_title
from tunebag.ui_notices import UIViewNotice, UIViewSection, ViewNoticeBus
from tunebag.ytdlp_fetch import YtdlpCookies

_HTTP_TIMEOUT = 5.0
_PLAYBACK_THRESHOLD_WATCH_SECONDS = 1.0
_DOWNLOAD_CACHE_NOTICE_SECONDS = 1.0
_ORIGIN_DOWNLOADS_PER_PLATFORM = 2
# Peer copies + origin slots across platforms; keep headroom for peer handoffs.
_FILL_POOL_WORKERS = _ORIGIN_DOWNLOADS_PER_PLATFORM * len(Platform) + 8
PLAYLOG_PAST_LIMIT = 20
_UNSET = object()
# Default first-boot Explore intent: even 1★–5★ shares, half unrated (10|10|10|10|10|50).
# Well-known id + seed so independently seeded devices merge to one Explore on pair.
# Current device gets an 8h standing budget so Explore is immediately assignable.
EXPLORE_INTENT_ID = UUID("00000000-0000-4000-8000-000000000001")
EXPLORE_SEED = 1
EXPLORE_DEFAULT_BUDGET_SECONDS = 8 * 3600
EXPLORE_DISTRIBUTION = StarDistribution(
    five=0.1,
    four=0.1,
    three=0.1,
    two=0.1,
    one=0.1,
    unrated=0.5,
)
# (device_id, budget) or (device_id, budget, expires_at)
DeviceHoursSpec = tuple[UUID, int] | tuple[UUID, int, datetime | None]

# Catalog Event → UI section notices (Device-local; see ui-view-notices spec).
_MIXES = (UIViewSection.MIXES,)
_MIXES_AND_PLAYLOG = (UIViewSection.MIXES, UIViewSection.PLAYLOG)
_INTENTS = (UIViewSection.INTENTS,)
_INTENTS_AND_CACHE = (UIViewSection.INTENTS, UIViewSection.CACHE)
_INTENTS_CACHE_PLAYLOG = (
    UIViewSection.INTENTS,
    UIViewSection.CACHE,
    UIViewSection.PLAYLOG,
)
_PEERS = (UIViewSection.PEERS,)
_VIEW_SECTIONS_FOR_EVENT: dict[EventType, tuple[UIViewSection, ...]] = {
    EventType.ARTIST_ADDED: _MIXES,
    EventType.ARTIST_DELETED: _MIXES,
    EventType.MIX_ADDED: _MIXES,
    EventType.MIX_TAGGED: _MIXES_AND_PLAYLOG,
    EventType.MIX_TAG_ADDED: _MIXES_AND_PLAYLOG,
    EventType.MIX_TAG_REMOVED: _MIXES_AND_PLAYLOG,
    EventType.MIX_RATED: _MIXES_AND_PLAYLOG,
    EventType.MIX_REJECTED: _MIXES_AND_PLAYLOG,
    EventType.MIX_UNREJECTED: _MIXES_AND_PLAYLOG,
    # PLAYHEAD: no Catalog UI notice — live position is Player; remounting
    # mixes/playlog every tick freezes the companion.
    EventType.PLAYED: _MIXES_AND_PLAYLOG,
    EventType.SKIPPED: _MIXES_AND_PLAYLOG,
    EventType.LAST_HEARD: _MIXES_AND_PLAYLOG,
    # Intent / assignment / sequence reshape cache + playlog queue.
    EventType.INTENT_UPSERTED: _INTENTS_CACHE_PLAYLOG,
    EventType.INTENT_DELETED: _INTENTS_CACHE_PLAYLOG,
    EventType.SEQUENCE_BUILT: _INTENTS_CACHE_PLAYLOG,
    EventType.ASSIGNMENT_SET: _INTENTS_CACHE_PLAYLOG,
    EventType.ASSIGNMENT_CLEARED: _INTENTS_CACHE_PLAYLOG,
    EventType.DEVICE_PAIRED: _PEERS,
    EventType.DEVICE_UNPAIRED: (UIViewSection.PEERS, UIViewSection.INTENTS),
}


class DeviceAgent:
    def __init__(
        self,
        name: str,
        *,
        priority: int = 100,
        base_url: str | None = None,
        identity: DeviceIdentity | None = None,
        source: Source | None = None,
        cookies: YtdlpCookies | None = None,
        data_dir: Path | None = None,
        player: AudioPlayer | None = None,
        clock: Callable[[], datetime] | None = None,
        discovery: LanDiscovery | None = None,
        cover_fetch: CoverFetcher | None = None,
    ) -> None:
        # Persist identity/log/hints only for an explicit data_dir so in-process
        # multi-agent tests (default ~/.tunebag) do not collide on one SQLite bag.
        persist = data_dir is not None
        self._persist = persist
        self.catalog = CatalogState(data_dir=data_dir)
        self.data_dir = self.catalog.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._store = open_durable_store(self.data_dir) if persist else None
        if persist:
            assert self._store is not None
            self._identity, device_id = resolve_store_identity(
                self._store,
                name=name,
                identity=identity,
            )
        else:
            self._identity = identity or generate_identity(name)
            device_id = new_id()
        self._private_key = _load_private_key(self._identity.private_key_pem)
        self.device = Device(
            id=device_id,
            name=name,
            public_key_pem=self._identity.public_key_pem,
            priority=priority,
        )
        self.base_url = base_url
        self.source = (
            source if source is not None else default_source(cookies=cookies)
        )
        self._discovery: LanDiscovery = (
            discovery if discovery is not None else NullLanDiscovery()
        )
        self.catalog.local_device_id = self.device.id
        self.catalog.add_device(self.device)
        self._log = EventLog(store=self._store)
        self._activity = ActivityLog()
        self._view_notices = ViewNoticeBus()
        # When set, peer Event applies accumulate sections here and flush once at
        # the end of sync/ingest_events (avoids holding a bus batch across threads).
        self._ingest_notice_sink: set[UIViewSection] | None = None
        self._reachable: list[DeviceAgent] = []
        # In-process meet sessions: proved until disconnect.
        self._proved_agents: set[int] = set()
        self._peer_urls: dict[UUID, str] = (
            self._store.load_locator_hints() if self._store is not None else {}
        )
        self._pair_candidates: dict[str, dict[str, Any]] = {}
        # Ephemeral pairing session (host and/or guest view); never persisted.
        self._pairing_session: dict[str, Any] | None = None
        self._pairing_expiry_timer: threading.Timer | None = None
        self._playback_threshold_timer: threading.Timer | None = None
        self._download_cache_notice_at: float = 0.0
        self._cache = ReleaseCache(
            self.data_dir,
            self.catalog,
            on_changed=lambda: self._mark_view_sections(UIViewSection.CACHE),
        )
        self._covers = CoverCache(self.data_dir, fetch=cover_fetch)
        # Local-only (not events): simulated link mode, Soft→Hard File delete,
        # skip delay, now-playing.
        self._metered = False
        self._current_mix_id: UUID | None = None
        # Local-only Playlog cushion: keep the immediate previous File briefly
        # so ◀ still works (same duration as Soft Reject; not Soft Reject).
        self._playlog_previous_mix_id: UUID | None = None
        self._playlog_previous_until: datetime | None = None
        self._clock: Callable[[], datetime] = clock or datetime.utcnow
        self._reject_file_deletes = RejectFileDeleteBuffer()
        self._skips = SkipBuffer()
        # Event log spine: lock, seq, dedupe, sign/verify, live apply / boot replay.
        self._journal = CatalogJournal(
            catalog=self.catalog,
            log=self._log,
            local_device_id=self.device.id,
            local_public_key_pem=self.public_key_pem,
            clock=self._clock,
            sign=self._sign,
            verify=self._verify,
            on_applied=self._on_journal_applied,
            store=self._store,
        )
        # Local player supervision (browser is remote control; closing it does not stop).
        self._player: AudioPlayer = player if player is not None else default_player()
        self._playback = PlaybackSupervisor(
            self._player,
            self._clock,
            locate_audio=self._locate_audio,
        )
        # Background fill: single-flight with coalesce so HTTP can return immediately.
        self._fill_lock = threading.Lock()
        self._fill_in_progress = False
        self._fill_pending = False
        self._fill_pending_override: UUID | None = None
        # Background catalog sync: same single-flight/coalesce shape as fill.
        self._sync_lock = threading.Lock()
        self._sync_in_progress = False
        self._sync_pending = False
        self._sync_pending_fill = False
        self._downloads: dict[UUID, dict[str, Any]] = {}
        self._download_lock = threading.Lock()
        self._origin_slots: dict[Platform, threading.Semaphore] = {
            platform: threading.Semaphore(_ORIGIN_DOWNLOADS_PER_PLATFORM)
            for platform in Platform
        }
        self._last_discovery_at: datetime | None = None
        # Nestable: defer auto-sync until a multi-event local write finishes
        # (e.g. INTENT_UPSERTED + SEQUENCE + ASSIGNMENTs) so peers do not pull a
        # half-written intent and rebuild missing assignments.
        self._auto_sync_defer_depth = 0
        self._auto_sync_deferred = False
        if persist:
            self._journal.boot()
            # Drop hints for Peers no longer trusted after replay (e.g. unpaired).
            self._prune_stale_locator_hints()
            # Boot replay skips on_applied — arm Soft→Hard File deletes from Catalog.
            self._arm_reject_file_deletes_from_catalog()
        self._start_discovery()
        self._sequence_provisioner = SequenceProvisioner()
        # Catalog maintenance ports (rebuild / fill / prune) — after methods exist.
        self._maintenance = BoundMaintenance(
            rebuild_all_sequences=self._rebuild_all_sequences,
            fillup_all_sequences=self._fillup_all_sequences,
            rebuild_unfilled_sequences=self._rebuild_unfilled_sequences,
            rebuild_sequence_for_intent=self._rebuild_sequence_for_intent,
            fill_caches=self.fill_caches,
            request_fill=self.request_fill,
            prune_unassigned_files=self._prune_unassigned_files,
            delete_retired_file_if_replaced=self._delete_retired_file_if_replaced,
        )

    def seed_default_intents_if_empty(self) -> bool:
        """On first durable boot (empty Event log), create the Explore intent.

        Returns True if Explore was created. Idempotent for non-empty logs.
        """
        if not self._log.is_empty():
            return False
        self.create_intent(
            "Explore",
            tags=[],
            distribution=EXPLORE_DISTRIBUTION,
            seed=EXPLORE_SEED,
            intent_id=EXPLORE_INTENT_ID,
            device_hours=[(self.device_id, EXPLORE_DEFAULT_BUDGET_SECONDS)],
        )
        return True

    def note(self, message: str, *, level: int = logging.INFO) -> None:
        """Record an operational progress line (terminal + UI activity feed)."""
        self._activity.note(message, level=level)
        self._mark_view_sections(UIViewSection.ACTIVITY)

    def activity(self) -> list[ActivityEntry]:
        return self._activity.entries()

    def drain_view_notices(self) -> list[UIViewNotice]:
        """Return coalesced UI section notices since the last drain (tests + SSE)."""
        return self._view_notices.drain()

    def subscribe_view_notices(
        self, callback: Callable[[UIViewNotice], None]
    ) -> Callable[[], None]:
        """Register for live notice delivery; return an unsubscribe callable."""
        return self._view_notices.subscribe(callback)

    @contextmanager
    def _view_notice_batch(self) -> Iterator[None]:
        self._view_notices.begin_batch()
        try:
            yield
        finally:
            self._view_notices.end_batch()

    @contextmanager
    def _defer_auto_sync(self) -> Iterator[None]:
        """Coalesce ``_schedule_auto_sync`` calls until the with-block exits."""
        self._auto_sync_defer_depth += 1
        try:
            yield
        finally:
            self._auto_sync_defer_depth -= 1
            if self._auto_sync_defer_depth == 0 and self._auto_sync_deferred:
                self._auto_sync_deferred = False
                self._schedule_auto_sync()

    @contextmanager
    def _ingest_notice_pass(self) -> Iterator[None]:
        """Coalesce UI notices for one sync/ingest pass without a shared bus batch."""
        owns_sink = self._ingest_notice_sink is None
        if owns_sink:
            self._ingest_notice_sink = set()
        try:
            yield
            if owns_sink and self._ingest_notice_sink:
                self._mark_view_sections(*self._ingest_notice_sink)
        finally:
            if owns_sink:
                self._ingest_notice_sink = None

    def _mark_view_sections(self, *sections: UIViewSection) -> None:
        self._view_notices.mark(*sections)

    def _mark_pairing_session(self) -> None:
        self._mark_view_sections(UIViewSection.PAIRING_SESSION)

    def _cancel_pairing_expiry_notice(self) -> None:
        timer = self._pairing_expiry_timer
        if timer is not None:
            timer.cancel()
            self._pairing_expiry_timer = None

    def _arm_pairing_expiry_notice(self) -> None:
        """Push a pairing_session notice when the ephemeral session TTL elapses."""
        self._cancel_pairing_expiry_notice()
        session = self._pairing_session
        if session is None:
            return
        session_id = session["session_id"]
        delay = max(0.0, float(session["expires_at"]) - time.monotonic()) + 0.05

        def _fire() -> None:
            sess = self._pairing_session
            if sess is None or sess.get("session_id") != session_id:
                return
            if sess["state"] in {"complete", "cancelled"}:
                return
            if not self._pairing_session_expired(sess):
                return
            sess["state"] = "cancelled"
            self._refresh_advertisement()
            self._mark_pairing_session()

        timer = threading.Timer(delay, _fire)
        timer.daemon = True
        self._pairing_expiry_timer = timer
        timer.start()

    def _mark_view_sections_for_event(self, event_type: EventType) -> None:
        sections = _VIEW_SECTIONS_FOR_EVENT.get(event_type)
        if sections:
            self._mark_view_sections(*sections)

    def _record_view_sections_for_event(self, event_type: EventType) -> None:
        sections = _VIEW_SECTIONS_FOR_EVENT.get(event_type)
        if not sections:
            return
        if self._ingest_notice_sink is not None:
            self._ingest_notice_sink.update(sections)
        else:
            self._mark_view_sections(*sections)

    @property
    def device_id(self) -> UUID:
        return self.device.id

    @property
    def name(self) -> str:
        return self.device.name

    @property
    def public_key_pem(self) -> str:
        return self.device.public_key_pem

    @property
    def private_key_pem(self) -> str:
        return self._identity.private_key_pem

    def fingerprint(self) -> str:
        return fingerprint_from_key(self.public_key_pem)

    def short_code(self) -> str:
        """Discovery label alias for fingerprint (not a pairing secret)."""
        return self.fingerprint()

    def pairing_payload(self) -> dict[str, Any]:
        return build_pairing_payload(
            self.name,
            self.public_key_pem,
            device_id=str(self.device.id),
            priority=self.device.priority,
            url=self.base_url,
        )

    def pairing_session_open(self) -> bool:
        session = self._pairing_session
        if session is None:
            return False
        if session.get("state") in {"complete", "cancelled"}:
            return False
        return not self._pairing_session_expired(session)

    def connect(self, other: DeviceAgent) -> None:
        """Mark another in-process agent reachable (test / same-host peer)."""
        if other is self:
            return
        if other not in self._reachable:
            self._reachable.append(other)
        if self not in other._reachable:
            other._reachable.append(self)
        # Becoming reachable triggers a catalog sync attempt on both sides.
        self.request_sync(fill=False)
        other.request_sync(fill=False)
        # Peer bytes / preferred-origin graph may have become actionable.
        self.request_fill()
        other.request_fill()

    def disconnect(self, other: DeviceAgent) -> None:
        """Mark another in-process agent unreachable."""
        if other in self._reachable:
            self._reachable.remove(other)
        if self in other._reachable:
            other._reachable.remove(self)
        # Proof lasts only for the live meet; reconnect must challenge again.
        self._proved_agents.discard(id(other))
        other._proved_agents.discard(id(self))

    def prove_possession(self, nonce: str) -> str:
        """Sign a meet challenge nonce with this Device's private key."""
        signature = self._private_key.sign(nonce.encode("utf-8"))
        return base64.b64encode(signature).decode("ascii")

    def peers(self) -> list[Device]:
        return [d for d in self.catalog.devices.values() if d.id != self.device.id]

    def mixes(self) -> list[Mix]:
        return self.catalog.mixes_list()

    def _assignment_ordered_ids(self, intent_id: UUID) -> list[UUID]:
        """Assigned mix ids in sequence listening order for this device."""
        assignment = self.assignment(intent_id)
        if assignment is None or not assignment.mix_ids:
            return []
        assignment_set = set(assignment.mix_ids)
        sequence = self.sequence(intent_id)
        if sequence is not None:
            ordered_ids = [
                entry.mix_id
                for entry in sequence.entries
                if entry.mix_id in assignment_set
            ]
            seen = set(ordered_ids)
            ordered_ids.extend(mid for mid in assignment.mix_ids if mid not in seen)
            return ordered_ids
        return list(assignment.mix_ids)

    def _is_playlog_previous_retained(self, mix_id: UUID) -> bool:
        """True while the Playlog previous-File cushion still holds."""
        if self._playlog_previous_mix_id != mix_id:
            return False
        until = self._playlog_previous_until
        if until is None:
            return False
        if self._clock() >= until:
            return False
        return True

    def _record_playlog_advance(self, *, previous: UUID) -> None:
        """Arm the previous-File cushion after leaving ``previous``."""
        self._playlog_previous_mix_id = previous
        self._playlog_previous_until = self._clock() + timedelta(
            seconds=SOFT_REJECT_SECONDS
        )

    def _playlog_global_past_ids(
        self,
        *,
        exclude: set[UUID],
        limit: int,
        now: datetime,
    ) -> list[UUID]:
        """Newest completed (Played) Releases for Playlog past (Catalog-global).

        Independent of Intent and of whether Files are local. Ordered by Last
        heard (set at natural end with Played). Hard Rejected are omitted; Soft
        Rejected stay. ``exclude`` drops rows already shown as current/upcoming.
        """
        heard: list[Mix] = []
        for mix in self.catalog.mixes_list():
            if not mix.played:
                continue
            if mix.last_heard_at is None:
                continue
            if mix.id in exclude:
                continue
            if mix.rejected and not is_soft_rejected(
                rejected=mix.rejected,
                rejected_at=mix.rejected_at,
                now=now,
            ):
                continue
            heard.append(mix)
        heard.sort(
            key=lambda m: m.last_heard_at or datetime.min,
            reverse=True,
        )
        return [mix.id for mix in heard[:limit]]

    def _play_target_for_intent(self, intent_id: UUID) -> UUID | None:
        """Mix ``play(intent)`` would pick without an explicit mix_id."""
        assignment = self.assignment(intent_id)
        if assignment is None or not assignment.mix_ids:
            return None
        if (
            self._current_mix_id is not None
            and self._current_mix_id in assignment.mix_ids
            and self._has_local_file(self._current_mix_id)
        ):
            return self._current_mix_id
        return assignment.mix_ids[0]

    def _mix_wanted_elsewhere(self, mix_id: UUID, *, except_intent: UUID) -> bool:
        for intent in self.intents():
            if intent.id == except_intent:
                continue
            assignment = self.assignment(intent.id)
            if assignment is not None and mix_id in assignment.mix_ids:
                return True
        return False

    def _playlog_row(
        self,
        mix: Mix,
        *,
        offset: int,
        intent_id: UUID,
        local_ids: set[UUID],
        downloads: dict[UUID, dict[str, Any]],
        now: datetime,
    ) -> dict[str, Any]:
        mix_id = mix.id
        if mix_id in local_ids:
            status = "cached"
        elif mix_id in downloads:
            status = "loading"
        elif offset < 0:
            status = "absent"
        else:
            status = "pending"
        artist = self.catalog.artists.get(mix.artist_id)
        artist_name = artist.name if artist is not None else "Unknown"
        soft = is_soft_rejected(
            rejected=mix.rejected,
            rejected_at=mix.rejected_at,
            now=now,
        )
        assignment = self.assignment(intent_id)
        in_assignment = assignment is not None and mix_id in assignment.mix_ids
        retained = self._is_playlog_previous_retained(mix_id)
        is_live_current = mix_id == self._current_mix_id
        entry: dict[str, Any] = {
            "offset": offset,
            "id": mix_id,
            "artist": artist_name,
            "artist_url": artist.url if artist is not None else None,
            "title": display_title(mix.title, artist=artist_name),
            "url": mix.url,
            "platform": mix.platform.value,
            "duration_seconds": int(mix.duration_seconds),
            "stars": int(mix.stars) if mix.stars is not None else None,
            "tags": list(mix.tags),
            "rejected": mix.rejected,
            "rejected_at": (
                mix.rejected_at.isoformat() if mix.rejected_at is not None else None
            ),
            "soft_rejected": soft,
            "cache_status": status,
            "has_cover": self.has_cover(mix_id),
            # Local + not Rejected: assignment/cushion, still-current after a
            # rebuild, or any past row (revise from Last heard while File stays).
            "playable": (
                mix_id in local_ids
                and not mix.rejected
                and (
                    in_assignment
                    or retained
                    or is_live_current
                    or offset < 0
                )
            ),
            "wanted_elsewhere": self._mix_wanted_elsewhere(
                mix_id, except_intent=intent_id
            ),
            "retained_previous": retained,
            "last_heard_at": (
                mix.last_heard_at.isoformat()
                if mix.last_heard_at is not None
                else None
            ),
        }
        if status == "cached":
            size = self._local_file_size(mix_id)
            if size is not None:
                entry["size_bytes"] = size
        elif status == "loading":
            progress = downloads[mix_id]
            entry["downloaded_bytes"] = int(progress["downloaded_bytes"])
            total = progress["total_bytes"]
            entry["total_bytes"] = total
        return entry

    def playlog(
        self,
        intent_id: UUID,
        *,
        past_limit: int = PLAYLOG_PAST_LIMIT,
    ) -> dict[str, Any]:
        """Playlog: Catalog-global Last-heard past + Intent assignment upcoming.

        Past (−N) is newest completed (Played) Releases across the Catalog.
        Current (0) and upcoming (+N) are this Intent's assignment order.
        """
        if intent_id not in self.catalog.intents:
            raise KeyError(f"unknown intent {intent_id}")
        now = self._clock()
        ordered_ids = self._assignment_ordered_ids(intent_id)
        local_ids = self._local_file_ids()
        with self._download_lock:
            downloads = {
                mix_id: {
                    "downloaded_bytes": int(progress["downloaded_bytes"]),
                    "total_bytes": progress["total_bytes"],
                }
                for mix_id, progress in self._downloads.items()
            }

        playing = self.is_playing() and self._playback.intent_id == intent_id
        current = self._current_mix_id
        # Live current for this Intent stays at 0 even after mark_played (etc.)
        # drops it from the assignment — otherwise it falls into Last-heard past.
        live_current = (
            current is not None
            and self._playback.intent_id == intent_id
            and current in self.catalog.mixes
        )
        if current is not None and current in ordered_ids:
            anchor = current
        elif live_current:
            anchor = current
        else:
            anchor = self._play_target_for_intent(intent_id)

        anchor_index: int | None = None
        if anchor is not None and anchor in ordered_ids:
            anchor_index = ordered_ids.index(anchor)

        items: list[dict[str, Any]] = []
        included: set[UUID] = set()

        # Current + upcoming first so global past does not duplicate queue rows.
        if (
            anchor is not None
            and anchor_index is None
            and live_current
            and anchor == current
        ):
            # Still playing / current but no longer in assignment.
            mix = self.catalog.mixes[anchor]
            items.append(
                self._playlog_row(
                    mix,
                    offset=0,
                    intent_id=intent_id,
                    local_ids=local_ids,
                    downloads=downloads,
                    now=now,
                )
            )
            included.add(anchor)
            upcoming_offset = 1
            for mid in ordered_ids:
                if mid in included:
                    continue
                mix = self.catalog.mixes.get(mid)
                if mix is None:
                    continue
                items.append(
                    self._playlog_row(
                        mix,
                        offset=upcoming_offset,
                        intent_id=intent_id,
                        local_ids=local_ids,
                        downloads=downloads,
                        now=now,
                    )
                )
                included.add(mid)
                upcoming_offset += 1
        elif anchor_index is not None:
            for i in range(anchor_index, len(ordered_ids)):
                mid = ordered_ids[i]
                mix = self.catalog.mixes.get(mid)
                if mix is None:
                    continue
                items.append(
                    self._playlog_row(
                        mix,
                        offset=i - anchor_index,
                        intent_id=intent_id,
                        local_ids=local_ids,
                        downloads=downloads,
                        now=now,
                    )
                )
                included.add(mid)
        elif ordered_ids:
            for i, mid in enumerate(ordered_ids):
                mix = self.catalog.mixes.get(mid)
                if mix is None:
                    continue
                items.append(
                    self._playlog_row(
                        mix,
                        offset=i,
                        intent_id=intent_id,
                        local_ids=local_ids,
                        downloads=downloads,
                        now=now,
                    )
                )
                included.add(mid)

        past_ids = self._playlog_global_past_ids(
            exclude=included,
            limit=past_limit,
            now=now,
        )
        # Cushion / soft-reject previous may lack Last heard yet — keep at −1.
        prev_id = self._playlog_previous_mix_id
        if (
            prev_id is not None
            and prev_id not in included
            and prev_id not in past_ids
            and prev_id in self.catalog.mixes
            and (
                self._is_playlog_previous_retained(prev_id)
                or is_soft_rejected(
                    rejected=self.catalog.mixes[prev_id].rejected,
                    rejected_at=self.catalog.mixes[prev_id].rejected_at,
                    now=now,
                )
            )
        ):
            past_ids = [prev_id, *[mid for mid in past_ids if mid != prev_id]][
                :past_limit
            ]

        for i, mid in enumerate(past_ids):
            mix = self.catalog.mixes.get(mid)
            if mix is None:
                continue
            items.append(
                self._playlog_row(
                    mix,
                    offset=-(i + 1),
                    intent_id=intent_id,
                    local_ids=local_ids,
                    downloads=downloads,
                    now=now,
                )
            )

        items.sort(key=lambda row: int(row["offset"]))
        return {
            "intent_id": intent_id,
            "current_mix_id": current,
            "anchor_mix_id": anchor,
            "playing": playing,
            "past_limit": past_limit,
            "items": items,
        }

    def artists(self) -> list[Artist]:
        return list(self.catalog.artists.values())

    def intents(self) -> list[Intent]:
        return list(self.catalog.intents.values())

    def sequence(self, intent_id: UUID) -> Sequence | None:
        return self.catalog.sequences.get(intent_id)

    def assignment(
        self, intent_id: UUID, device_id: UUID | None = None
    ) -> Assignment | None:
        target = device_id if device_id is not None else self.device.id
        return self.catalog.assignments.get((intent_id, target))

    def files(self) -> list[Mix]:
        """Mixes that have local audio bytes on this device."""
        return [
            self.catalog.mixes[mix_id]
            for mix_id in self._cache.local_ids()
            if mix_id in self.catalog.mixes
        ]

    @property
    def downloading_mix_id(self) -> UUID | None:
        """Compat: first active download, if any."""
        with self._download_lock:
            if not self._downloads:
                return None
            return next(iter(self._downloads))

    @property
    def download_progress(self) -> dict[str, Any] | None:
        """Compat: progress for the first active download, if any."""
        with self._download_lock:
            if not self._downloads:
                return None
            mix_id, progress = next(iter(self._downloads.items()))
            return {
                "mix_id": mix_id,
                "downloaded_bytes": int(progress["downloaded_bytes"]),
                "total_bytes": progress["total_bytes"],
            }

    @property
    def downloads_in_progress(self) -> list[dict[str, Any]]:
        with self._download_lock:
            return [
                {
                    "mix_id": mix_id,
                    "downloaded_bytes": int(progress["downloaded_bytes"]),
                    "total_bytes": progress["total_bytes"],
                }
                for mix_id, progress in self._downloads.items()
            ]

    def _assignment_offset(self, assignment: Assignment, index: int) -> float:
        """Cumulative duration of mixes before ``index`` in the assignment."""
        offset = 0.0
        for mix_id in assignment.mix_ids[:index]:
            mix = self.catalog.mixes.get(mix_id)
            if mix is not None:
                offset += float(mix.duration_seconds)
        return offset

    @property
    def _playback_position(self) -> float:
        """Compat for tests / urgency: local frozen or idle position."""
        return self._playback.position

    @_playback_position.setter
    def _playback_position(self, value: float) -> None:
        self._playback.position = float(value)

    def _current_mix_position_seconds(self) -> float:
        """Live position when playing the current mix; else catalog playhead."""
        current = self._current_mix_id
        if current is None:
            return 0.0
        if self._playback.playing:
            return float(self.playback_position())
        head = self.catalog.playheads.get(current)
        if head is not None:
            return float(head.position_seconds)
        return float(self._playback.position)

    def _sequence_progress(self, assignment: Assignment) -> float:
        """Seconds already consumed in this assignment's listen timeline.

        When ``_current_mix_id`` sits in the assignment, progress is the
        cumulative offset to that mix plus its play position; otherwise 0.
        """
        current = self._current_mix_id
        if current is None or current not in assignment.mix_ids:
            return 0.0
        index = assignment.mix_ids.index(current)
        return self._assignment_offset(assignment, index) + self._current_mix_position_seconds()

    def _mix_urgency(self, assignment: Assignment, mix_id: UUID) -> float:
        """Time-until-needed: sequence offset minus listen progress (lower first)."""
        if mix_id not in assignment.mix_ids:
            raise ValueError("mix is not in assignment")
        index = assignment.mix_ids.index(mix_id)
        return self._assignment_offset(assignment, index) - self._sequence_progress(
            assignment
        )

    def _assignment_min_urgency(self, assignment: Assignment) -> float:
        if not assignment.mix_ids:
            return float("inf")
        return min(self._mix_urgency(assignment, mid) for mid in assignment.mix_ids)

    def cache_groups(self) -> list[dict[str, Any]]:
        """Assignments for this device, grouped for the Cache UI.

        Each group has mixes in that intent's sequence listening order (assigned
        ids only; falls back to assignment order if the sequence is missing)
        with status cached / loading / pending, plus overview count, duration,
        and on-disk size totals. Intent groups are ordered by soonest listen
        need (min mix urgency). Local files with no remaining assignment appear
        under a synthetic Other group last.
        """
        local_ids = self._local_file_ids()
        with self._download_lock:
            downloads = {
                mix_id: {
                    "downloaded_bytes": int(progress["downloaded_bytes"]),
                    "total_bytes": progress["total_bytes"],
                }
                for mix_id, progress in self._downloads.items()
            }
        assigned_ids: set[UUID] = set()
        intent_groups: list[tuple[float, str, dict[str, Any]]] = []

        for intent in self.intents():
            assignment = self.assignment(intent.id)
            if assignment is None:
                continue
            assignment_set = set(assignment.mix_ids)
            sequence = self.sequence(intent.id)
            if sequence is not None:
                ordered_ids = [
                    entry.mix_id
                    for entry in sequence.entries
                    if entry.mix_id in assignment_set
                ]
                # Assigned ids missing from the sequence stay in assignment order.
                seen = set(ordered_ids)
                ordered_ids.extend(
                    mid for mid in assignment.mix_ids if mid not in seen
                )
            else:
                ordered_ids = list(assignment.mix_ids)
            mixes: list[dict[str, Any]] = []
            overview = {
                "cached": {"count": 0, "duration_seconds": 0, "size_bytes": 0},
                "loading": {"count": 0, "duration_seconds": 0, "size_bytes": 0},
                "pending": {"count": 0, "duration_seconds": 0, "size_bytes": 0},
            }
            for mix_id in ordered_ids:
                assigned_ids.add(mix_id)
                mix = self.catalog.mixes.get(mix_id)
                if mix is None:
                    continue
                if mix_id in local_ids:
                    status = "cached"
                elif mix_id in downloads:
                    status = "loading"
                else:
                    status = "pending"
                duration = int(mix.duration_seconds)
                artist = self.catalog.artists.get(mix.artist_id)
                artist_name = artist.name if artist is not None else "Unknown"
                entry: dict[str, Any] = {
                    "id": mix_id,
                    "artist": artist_name,
                    "title": display_title(mix.title, artist=artist_name),
                    "duration_seconds": duration,
                    "status": status,
                }
                if status == "cached":
                    size = self._local_file_size(mix_id)
                    if size is not None:
                        entry["size_bytes"] = size
                        overview[status]["size_bytes"] += size
                if status == "loading":
                    progress = downloads[mix_id]
                    entry["downloaded_bytes"] = int(progress["downloaded_bytes"])
                    entry["total_bytes"] = progress["total_bytes"]
                mixes.append(entry)
                overview[status]["count"] += 1
                overview[status]["duration_seconds"] += duration
            intent_groups.append(
                (
                    self._assignment_min_urgency(assignment),
                    str(intent.id),
                    {
                        "id": intent.id,
                        "name": intent.name,
                        "mixes": mixes,
                        "overview": overview,
                    },
                )
            )

        intent_groups.sort(key=lambda item: (item[0], item[1]))
        groups: list[dict[str, Any]] = [item[2] for item in intent_groups]

        other_mixes: list[dict[str, Any]] = []
        other_overview = {
            "cached": {"count": 0, "duration_seconds": 0, "size_bytes": 0},
            "loading": {"count": 0, "duration_seconds": 0, "size_bytes": 0},
            "pending": {"count": 0, "duration_seconds": 0, "size_bytes": 0},
        }
        for mix_id in sorted(local_ids - assigned_ids, key=str):
            mix = self.catalog.mixes.get(mix_id)
            if mix is None:
                continue
            duration = int(mix.duration_seconds)
            artist = self.catalog.artists.get(mix.artist_id)
            artist_name = artist.name if artist is not None else "Unknown"
            entry: dict[str, Any] = {
                "id": mix_id,
                "artist": artist_name,
                "title": display_title(mix.title, artist=artist_name),
                "duration_seconds": duration,
                "status": "cached",
            }
            size = self._local_file_size(mix_id)
            if size is not None:
                entry["size_bytes"] = size
                other_overview["cached"]["size_bytes"] += size
            other_mixes.append(entry)
            other_overview["cached"]["count"] += 1
            other_overview["cached"]["duration_seconds"] += duration
        if other_mixes:
            groups.append(
                {
                    "id": None,
                    "name": "Other",
                    "mixes": other_mixes,
                    "overview": other_overview,
                }
            )
        return groups

    def cache_summary(self) -> dict[str, int]:
        """Count, duration, and on-disk size for all local audio files."""
        count = 0
        duration_seconds = 0
        size_bytes = 0
        for mix in self.files():
            count += 1
            duration_seconds += int(mix.duration_seconds)
            size = self._local_file_size(mix.id)
            if size is not None:
                size_bytes += size
        return {
            "count": count,
            "duration_seconds": duration_seconds,
            "size_bytes": size_bytes,
        }

    def file_bytes(self, mix_id: UUID) -> bytes | None:
        """Local audio bytes for a Mix, if present (peer handoff).

        Albums use ``album_track_bytes`` — a single blob is not meaningful.
        """
        return self._cache.mix_bytes(mix_id)

    def album_track_bytes(self, mix_id: UUID) -> list[bytes] | None:
        """Ordered track bytes for a complete Album, else None (peer handoff)."""
        return self._cache.album_bytes(mix_id)

    def remove_local_file(self, mix_id: UUID) -> None:
        """Drop local audio (and cover) for a Release so it can be fetched again."""
        had = self._cache.remove(mix_id)
        self._covers.remove(mix_id)
        self._refresh_intent_folders()
        if had:
            self._mark_view_sections(UIViewSection.CACHE)

    def has_local_cover(self, mix_id: UUID) -> bool:
        return self._covers.has(mix_id)

    def has_cover(self, mix_id: UUID) -> bool:
        """True when a local cover exists or Catalog has a fetchable cover_url."""
        if self._covers.has(mix_id):
            return True
        mix = self.catalog.mixes.get(mix_id)
        return mix is not None and bool(mix.cover_url)

    def ensure_cover(
        self,
        mix_id: UUID,
        url: str | None = None,
        *,
        page_url: str | None = None,
    ) -> bool:
        """Ensure local cover bytes exist. Soft-fails on network errors.

        ``page_url`` (typically the Release permalink) is a last-resort scrape
        source for hearthis covers when CDN size/slug fallbacks all 403.
        """
        if self._covers.has(mix_id):
            return True
        mix = self.catalog.mixes.get(mix_id)
        cover_url = url
        if not cover_url:
            cover_url = mix.cover_url if mix is not None else None
        if not cover_url:
            return False
        scrape_page = page_url
        if not scrape_page and mix is not None:
            scrape_page = mix.url
        ok = self._covers.ensure(mix_id, cover_url, page_url=scrape_page)
        if ok:
            self.note(f"cover cached: {mix_id}")
        return ok

    def cover_bytes(self, mix_id: UUID) -> tuple[bytes, str] | None:
        """Return (bytes, media_type) for a local or freshly ensured cover."""
        if mix_id not in self.catalog.mixes:
            return None
        if not self.ensure_cover(mix_id):
            return None
        path = self._covers.path(mix_id)
        data = path.read_bytes()
        return data, cover_media_type(data)

    def intent_folder(self, intent_id: UUID) -> Path:
        """Directory of this device's assigned files for an intent."""
        return self._cache.intent_folder(intent_id)

    def is_metered(self) -> bool:
        return self._metered

    def set_metered(self, metered: bool) -> None:
        """Simulate a metered link (demo switch; no SIM required)."""
        self._metered = bool(metered)
        # Unmetered makes the full assignment actionable; enabling metered only
        # shrinks the window (next fill pass already skips deferred).
        if not self._metered:
            self.request_fill()

    def current_mix(self) -> UUID | None:
        return self._current_mix_id

    def set_current_mix(self, mix_id: UUID | None) -> None:
        """Mark the mix in progress (including a resumed one) for the metered cap."""
        if mix_id is not None and mix_id not in self.catalog.mixes:
            raise KeyError(f"unknown mix {mix_id}")
        previous = self._current_mix_id
        if previous is not None and mix_id is not None and previous != mix_id:
            self._record_playlog_advance(previous=previous)
        self._current_mix_id = mix_id
        # Metered window moves with play / skip / continue.
        self.request_fill()

    def is_playing(self) -> bool:
        self._supervise_playback()
        return self._playback.playing

    def play(self, intent_id: UUID, mix_id: UUID | None = None) -> Mix:
        """Supervise local playback of an assigned Release that has Files on this device.

        Resumes from the latest synced playhead when one exists, except when that
        playhead is already at the Release end (then starts at 0). Mixes start the
        cached blob; Albums start the Catalog-ordered track file for the timeline
        position (browser is remote only).
        """
        if intent_id not in self.catalog.intents:
            raise KeyError(f"unknown intent {intent_id}")
        assignment = self.assignment(intent_id)
        if assignment is None or not assignment.mix_ids:
            raise ValueError("intent has no assignment on this device")
        if mix_id is not None:
            target = mix_id
        else:
            picked = self._play_target_for_intent(intent_id)
            if picked is None:
                raise ValueError("intent has no assignment on this device")
            target = picked
        retained_ok = self._is_playlog_previous_retained(target) and self._has_local_file(
            target
        )
        # Explicit mix_id: allow revising a still-local past/cushion Release or
        # the live current after it left the assignment.
        target_mix = self.catalog.mixes.get(target)
        explicit_local_ok = (
            mix_id is not None
            and target_mix is not None
            and self._has_local_file(target)
            and (
                retained_ok
                or target == self._current_mix_id
                or target_mix.played
            )
        )
        if (
            target not in assignment.mix_ids
            and not retained_ok
            and not explicit_local_ok
        ):
            raise ValueError("mix is not in this device's assignment")
        if not self._has_local_file(target):
            raise ValueError("mix has no local file")
        mix = self.catalog.mixes[target]
        # Resuming a mix cancels a pending skip for it (natural undo of the delay).
        self._skips.cancel(target)
        existing = self.catalog.playheads.get(target)
        start = float(existing.position_seconds) if existing is not None else 0.0
        duration = float(mix.duration_seconds)
        # End-of-Release playhead would immediately natural-end; start over.
        if duration > 0 and start >= duration:
            start = 0.0
        self._ensure_blob_on_disk(target)
        # Capture successor before any mid-release mark_played rebuilds reshuffle.
        continue_next = self._next_local_assigned(intent_id, target, wrap=False)
        self._playback.start(
            mix,
            start,
            intent_id=intent_id,
            continue_next_id=continue_next,
        )
        # Advance current + cushion before fill so PLAYER/PLAYLOG notices
        # are not trapped in a concurrent fill view-notice batch.
        previous = self._current_mix_id
        if previous is not None and previous != target:
            self._record_playlog_advance(previous=previous)
        self._current_mix_id = target
        # Resume/play boundary: flush prior pause playhead to peers. Do not
        # re-append PLAYHEAD at ``start`` — equal-position ticks refresh
        # updated_at and block near-window seek-backs (Last heard tests).
        self._schedule_auto_sync()
        self._arm_playback_threshold_watch()
        self._mark_view_sections(UIViewSection.PLAYER, UIViewSection.PLAYLOG)
        self.request_fill()
        # Last play wins: ask reachable Peers to pause so only one Device is audible.
        self._request_peers_yield()
        return mix

    def stop(self, position_seconds: float | None = None) -> None:
        """Stop local playback without marking the mix played; reset playhead to 0.

        ``position_seconds`` is accepted for API compatibility but ignored —
        Stop always commits playhead 0:00 on the current Release. Same-Device
        Playhead updates are causal LWW, so the rewind is accepted without a
        special payload flag.
        """
        del position_seconds  # API compat; Stop always resets to 0.
        if self._current_mix_id is not None:
            if self.is_playing():
                self._playback.freeze()
            self.report_playhead(0.0)
        self._playback.stop()
        self._cancel_playback_threshold_watch()
        # Expiry may have deferred deletion of the mix that was playing.
        self._prune_unassigned_files()
        self._schedule_auto_sync()
        self._mark_view_sections(UIViewSection.PLAYER, UIViewSection.PLAYLOG)

    def yield_playback(self) -> bool:
        """Pause if locally playing so a Peer can take over audio.

        No-op when idle so idle Peers do not rewrite playheads. Returns whether
        this Device yielded.
        """
        if not self.is_playing():
            return False
        self.pause()
        return True

    def pause(self, position_seconds: float | None = None) -> None:
        """Pause local playback; keep current mix and intent for resume.

        Always commits the playhead (optional explicit position, else frozen clock).
        """
        if self.is_playing():
            self._playback.freeze()
        pos = (
            float(position_seconds)
            if position_seconds is not None
            else self._playback.position
        )
        if self._current_mix_id is not None:
            self.report_playhead(pos)
        if self.is_playing():
            self._playback.pause_audio()
        self._cancel_playback_threshold_watch()
        # Playhead ticks skip auto-sync; flush to peers on transport boundaries.
        self._schedule_auto_sync()
        self._mark_view_sections(UIViewSection.PLAYER, UIViewSection.PLAYLOG)

    def skip(self, intent_id: UUID | None = None) -> Mix:
        """Advance to the next local assigned mix without marking the current played.

        Schedules a local 5‑minute skip delay for the abandoned mix. After the
        delay, a sticky SKIPPED event runs Sequence fillup (drop from Sequences;
        keep remaining queued order; append if hours need it) without setting
        played.
        """
        self.commit_pending_skips()
        resolved = intent_id if intent_id is not None else self._playback.intent_id
        if resolved is None:
            raise ValueError("no intent to skip within")
        if resolved not in self.catalog.intents:
            raise KeyError(f"unknown intent {resolved}")
        assignment = self.assignment(resolved)
        if assignment is None or not assignment.mix_ids:
            raise ValueError("intent has no assignment on this device")
        current = self._current_mix_id
        next_id = self._next_local_assigned(resolved, current, wrap=True)
        if next_id is None:
            raise ValueError("no other local mix to skip to")
        if current is not None and current in self.catalog.mixes:
            mix = self.catalog.mixes[current]
            if not mix.played and not mix.skipped:
                self._skips.start(current, self.device.id, now=self._clock())
        self._playback.freeze()
        if current is not None:
            self.report_playhead(self._playback.position)
        result = self.play(resolved, next_id)
        # Playhead ticks skip auto-sync; flush to peers on transport boundaries.
        self._schedule_auto_sync()
        return result

    def _next_local_assigned(
        self, intent_id: UUID, current: UUID | None, *, wrap: bool
    ) -> UUID | None:
        """Next local File in assignment order after ``current``.

        When ``wrap`` is True (Skip), wraps to the first local id and returns
        None only when there is no other local release. When ``wrap`` is False
        (natural end), returns the next later local id or None at the end.
        """
        assignment = self.assignment(intent_id)
        if assignment is None or not assignment.mix_ids:
            return None
        local_ids = [mid for mid in assignment.mix_ids if self._has_local_file(mid)]
        if not local_ids:
            return None
        if current in local_ids:
            idx = local_ids.index(current)
            if wrap:
                next_id = local_ids[(idx + 1) % len(local_ids)]
                return None if next_id == current else next_id
            if idx + 1 >= len(local_ids):
                return None
            return local_ids[idx + 1]
        return local_ids[0] if wrap else None

    def playback_position(self) -> float:
        """Current local playback position (including a mid-mix resume point)."""
        self._supervise_playback()
        mix = (
            self.catalog.mixes.get(self._current_mix_id)
            if self._current_mix_id is not None
            else None
        )
        return self._playback.live_position(mix)

    def _maybe_commit_threshold_playhead(
        self, mix: Mix | None, position_seconds: float
    ) -> None:
        """No mid-song Last heard / Played; natural end emits those."""
        return

    def _arm_playback_threshold_watch(self) -> None:
        """While playing, supervise natural end every second without UI polls."""
        self._cancel_playback_threshold_watch()

        def _fire() -> None:
            self._playback_threshold_timer = None
            self._playback_threshold_tick()

        timer = threading.Timer(_PLAYBACK_THRESHOLD_WATCH_SECONDS, _fire)
        timer.daemon = True
        self._playback_threshold_timer = timer
        timer.start()

    def _cancel_playback_threshold_watch(self) -> None:
        if self._playback_threshold_timer is not None:
            self._playback_threshold_timer.cancel()
            self._playback_threshold_timer = None

    def _playback_threshold_tick(self) -> None:
        if not self._playback.playing:
            return
        was_playing = True
        self._supervise_playback()
        if not self._playback.playing:
            if was_playing:
                self._mark_view_sections(UIViewSection.PLAYER)
            return
        mix = (
            self.catalog.mixes.get(self._current_mix_id)
            if self._current_mix_id is not None
            else None
        )
        pos = self._playback.live_position(mix)
        self._maybe_commit_threshold_playhead(mix, pos)
        if self._playback.playing:
            self._arm_playback_threshold_watch()

    def playing_intent_id(self) -> UUID | None:
        return self._playback.intent_id

    def report_playhead(self, position_seconds: float) -> Playhead:
        """Update the playhead for the current mix (mid-play; no completion)."""
        mix_id = self._current_mix_id
        if mix_id is None:
            raise ValueError("no current mix")
        mix = self.catalog.mixes.get(mix_id)
        if mix is None:
            raise KeyError(f"unknown mix {mix_id}")
        previous = 0.0
        existing_head = self.catalog.playheads.get(mix_id)
        if existing_head is not None:
            previous = float(existing_head.position_seconds)
        with self._view_notice_batch():
            intents = self._playback.note_position(
                mix,
                float(position_seconds),
                previous_position=previous,
            )
            self._apply_playback_intents(intents)
        return self.catalog.playheads[mix_id]

    def seek(self, position_seconds: float) -> Playhead:
        """Seek the current mix: sync playhead and restart local audio if playing."""
        mix_id = self._current_mix_id
        if mix_id is None:
            raise ValueError("no current mix")
        mix = self.catalog.mixes.get(mix_id)
        if mix is None:
            raise KeyError(f"unknown mix {mix_id}")
        pos = clamp_seek_position(position_seconds, float(mix.duration_seconds))
        was_playing = self.is_playing()
        head = self.report_playhead(pos)
        self._playback.seek(
            mix,
            pos,
            was_playing=was_playing,
            keep_playing=self.is_playing(),
        )
        # Playhead ticks skip auto-sync; flush to peers on transport boundaries.
        self._schedule_auto_sync()
        self._mark_view_sections(UIViewSection.PLAYER)
        return head

    def _locate_audio(self, mix: Mix, timeline_seconds: float) -> tuple[Path, float]:
        """Resolve Cache path + within-file offset for a Release timeline position."""
        if mix.kind is ReleaseKind.ALBUM:
            if not mix.tracks:
                raise ValueError("album has no tracks")
            index, offset = album_timeline_location(mix, timeline_seconds)
            track_path = self._cache.album_track_path(mix, index)
            if not track_path.is_file():
                raise FileNotFoundError(f"album track missing: {track_path}")
            return track_path, offset
        blob = self._ensure_blob_on_disk(mix.id)
        return blob, float(timeline_seconds)

    def _apply_playback_intents(self, intents: list[PlaybackIntent]) -> None:
        """Translate supervisor intents into Events / auto-continue play()."""
        for intent in intents:
            if isinstance(intent, ReportPlayhead):
                self._append_and_apply(
                    EventType.PLAYHEAD,
                    {
                        "mix_id": str(intent.mix_id),
                        "position_seconds": intent.position_seconds,
                    },
                )
            elif isinstance(intent, EmitLastHeard):
                self._append_and_apply(
                    EventType.LAST_HEARD,
                    {"mix_id": str(intent.mix_id)},
                )
            elif isinstance(intent, MarkPlayed):
                self.mark_played(intent.mix_id)
            elif isinstance(intent, ContinueTo):
                try:
                    self.play(intent.intent_id, intent.mix_id)
                except (ValueError, KeyError, FileNotFoundError):
                    # Assignment/cache may have changed after mark_played rebuild.
                    pass

    def _supervise_playback(self) -> None:
        """Advance Album tracks; on release end, continue to the next local assignment."""
        if not self._playback.playing or self._player.is_alive():
            return
        mix_id = self._current_mix_id
        mix = self.catalog.mixes.get(mix_id) if mix_id is not None else None
        previous = 0.0
        if mix_id is not None:
            existing_head = self.catalog.playheads.get(mix_id)
            if existing_head is not None:
                previous = float(existing_head.position_seconds)
        fallback_next: UUID | None = None
        if mix is not None and self._playback.intent_id is not None:
            fallback_next = self._next_local_assigned(
                self._playback.intent_id, mix.id, wrap=False
            )
        with self._view_notice_batch():
            intents = self._playback.supervise(
                mix,
                previous_position=previous,
                fallback_next_id=fallback_next,
            )
            self._apply_playback_intents(intents)
        if intents:
            # Track advance / release end: flush playhead (and ContinueTo) to peers.
            self._schedule_auto_sync()
            self._mark_view_sections(UIViewSection.PLAYER, UIViewSection.PLAYLOG)
            if self._playback.playing:
                self._arm_playback_threshold_watch()
            else:
                self._cancel_playback_threshold_watch()

    def mark_played(self, mix_id: UUID | None = None) -> Mix:
        """Mark a mix played (natural end-of-Release, or internal helper).

        Sequence fillup drops the mix from Sequences, keeps remaining queued
        order, and appends only if device hours need it. Does not stop playback
        or advance. The played file is deleted once a replacement is local and
        the mix is no longer current.
        """
        target = mix_id if mix_id is not None else self._current_mix_id
        if target is None:
            raise ValueError("no mix to mark played")
        if target not in self.catalog.mixes:
            raise KeyError(f"unknown mix {target}")
        self._skips.cancel(target)
        if not self.catalog.mixes[target].played:
            with self._view_notice_batch():
                self._append_and_apply(EventType.PLAYED, {"mix_id": str(target)})
                self._maintenance.after_catalog_change(
                    CatalogChange(
                        CatalogChangeReason.MARK_PLAYED,
                        mix_id=target,
                    )
                )
        return self.catalog.mixes[target]

    def mark_played_and_continue(
        self, intent_id: UUID | None = None
    ) -> Mix:
        """Companion Mark played: Last heard + Played, then next local (wrap).

        Unlike Skip, does not schedule Skipped. Unlike natural end, wraps like
        Skip when choosing the next local File. If there is no other local
        Release, stays on the current one after marking.
        """
        current = self._current_mix_id
        if current is None:
            raise ValueError("no mix to mark played")
        if current not in self.catalog.mixes:
            raise KeyError(f"unknown mix {current}")
        mix = self.catalog.mixes[current]
        resolved = (
            intent_id if intent_id is not None else self._playback.intent_id
        )
        with self._view_notice_batch():
            if self.is_playing():
                self._playback.freeze()
            self.report_playhead(float(mix.duration_seconds))
            self._append_and_apply(
                EventType.LAST_HEARD, {"mix_id": str(current)}
            )
            marked = self.mark_played(current)
            if resolved is None or resolved not in self.catalog.intents:
                return marked
            next_id = self._next_local_assigned(
                resolved, current, wrap=True
            )
            if next_id is None:
                return marked
            result = self.play(resolved, next_id)
            self._schedule_auto_sync()
            return result

    def mix(self, mix_id: UUID) -> Mix | None:
        return self.catalog.mixes.get(mix_id)

    def playhead(self, mix_id: UUID) -> Playhead | None:
        return self.catalog.playheads.get(mix_id)

    def suggest_tags(self, prefix: str = "", limit: int = 6) -> list[str]:
        """Tags already in the catalog that match the prefix (popularity order)."""
        return self.catalog.suggest_tags(prefix, limit=limit)

    def later_features(self) -> list[str]:
        """Planned later features shown when the demo player closes (not implemented)."""
        return _load_later_features()

    @property
    def fill_in_progress(self) -> bool:
        with self._fill_lock:
            return self._fill_in_progress

    @property
    def sync_in_progress(self) -> bool:
        with self._sync_lock:
            return self._sync_in_progress

    def request_sync(self, *, fill: bool = False) -> bool:
        """Start catalog ``sync`` on a daemon thread (single-flight).

        Auto-sync is catalog-only by default (``fill=False``). Pass ``fill=True``
        to also ``request_fill`` after the pull (manual Sync still does that
        itself). If a sync is already running, coalesce another pass when it
        finishes (OR-ing the fill flag). Returns True if a new thread started.
        """
        with self._sync_lock:
            if self._sync_in_progress:
                self._sync_pending = True
                self._sync_pending_fill = self._sync_pending_fill or fill
                return False
            self._sync_in_progress = True
            self._sync_pending = False
            self._sync_pending_fill = fill
            started_fill = fill
        thread = threading.Thread(
            target=self._run_sync_background,
            kwargs={"fill": started_fill},
            daemon=True,
            name="tunebag-sync",
        )
        thread.start()
        return True

    def wait_for_sync(self, timeout: float = 30.0) -> None:
        """Block until no background sync is running (for tests)."""
        deadline = time.monotonic() + timeout
        while self.sync_in_progress:
            if time.monotonic() >= deadline:
                raise TimeoutError("sync still in progress")
            time.sleep(0.05)

    def _run_sync_background(self, *, fill: bool = False) -> None:
        try:
            while True:
                try:
                    self.sync(fill=False)
                    if fill:
                        self.request_fill()
                except Exception as exc:
                    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                        raise
                    self.note(f"auto-sync failed: {exc}", level=logging.WARNING)
                with self._sync_lock:
                    if not self._sync_pending:
                        self._sync_in_progress = False
                        return
                    fill = self._sync_pending_fill
                    self._sync_pending = False
                    self._sync_pending_fill = False
        except BaseException:
            with self._sync_lock:
                self._sync_in_progress = False
                self._sync_pending = False
                self._sync_pending_fill = False
            raise

    def request_fill(self, *, override_intent_id: UUID | None = None) -> bool:
        """Start ``fill_caches`` on a daemon thread (single-flight).

        If a fill is already running, coalesce another pass when it finishes
        (preferring a provided fill-now override). Returns True if a new thread
        was started, False if coalesced onto the in-progress fill.
        """
        with self._fill_lock:
            if self._fill_in_progress:
                self._fill_pending = True
                if override_intent_id is not None:
                    self._fill_pending_override = override_intent_id
                return False
            self._fill_in_progress = True
            self._fill_pending = False
            self._fill_pending_override = None
            started_override = override_intent_id
        thread = threading.Thread(
            target=self._run_fill_background,
            kwargs={"override_intent_id": started_override},
            daemon=True,
            name="tunebag-fill",
        )
        thread.start()
        return True

    def wait_for_fill(self, timeout: float = 30.0) -> None:
        """Block until no background fill is running (for tests)."""
        deadline = time.monotonic() + timeout
        while self.fill_in_progress:
            if time.monotonic() >= deadline:
                raise TimeoutError("fill still in progress")
            time.sleep(0.05)

    def _run_fill_background(self, *, override_intent_id: UUID | None = None) -> None:
        try:
            while True:
                try:
                    self.fill_caches(override_intent_id=override_intent_id)
                except Exception as exc:
                    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                        raise
                    self.note(f"fill caches failed: {exc}", level=logging.WARNING)
                with self._fill_lock:
                    if not self._fill_pending:
                        self._fill_in_progress = False
                        return
                    override_intent_id = self._fill_pending_override
                    self._fill_pending = False
                    self._fill_pending_override = None
        except BaseException:
            with self._fill_lock:
                self._fill_in_progress = False
                self._fill_pending = False
                self._fill_pending_override = None
            raise

    def fill_caches(self, *, override_intent_id: UUID | None = None) -> int:
        """Fill this device's assignments from peers or origin.

        Missing mixes are fetched in soonest-needed order across intents
        (sequence time offset minus listen progress). Origin fetches run up to
        ``_ORIGIN_DOWNLOADS_PER_PLATFORM`` concurrent downloads per Platform;
        peer copies do not consume those slots. Only **actionable** gaps are
        attempted: peer already has bytes, or this device may origin-fetch
        under Metered / preferred-origin rules. Deferred gaps stay pending and
        the pass ends (re-kick on play, unmetered, peer cache, connect, …).
        When metered, origin fetches are limited to the current mix plus one
        ahead per intent, unless ``override_intent_id`` is that intent
        (Fill now). Peer copies always ignore the metered cap. Files already
        local stay.

        Returns the number of mixes with local audio after the pass. Per-mix
        fetch failures are skipped so one bad URL does not abort the fill.

        If a background ``request_fill`` is already running (e.g. after intent
        create), coalesce a follow-up pass and wait instead of racing.
        """
        if (
            self.fill_in_progress
            and threading.current_thread().name != "tunebag-fill"
        ):
            with self._fill_lock:
                self._fill_pending = True
                if override_intent_id is not None:
                    self._fill_pending_override = override_intent_id
            self.wait_for_fill()
            return len(self.files())
        if override_intent_id is not None:
            self.note(f"fill caches start (fill-now intent={override_intent_id})")
        else:
            self.note("fill caches start")
        # Do not hold a view-notice batch across downloads. A long fill would
        # delay PEERS/INTENTS SSE until the last byte lands, so Assign hours
        # still misses a device that paired mid-fill.
        #
        # Re-read the live assignment each step: Explore refresh (or peer rebuild)
        # may replace mix_ids while a long origin fetch is in flight. Walking a
        # stale snapshot keeps downloading mixes the Cache UI no longer lists.
        for intent in self.intents():
            if self.assignment(intent.id) is None and intent.device_hours:
                other = ", ".join(str(dh.device_id) for dh in intent.device_hours)
                self.note(
                    f"fill skip: {intent.name} has hours for {other} "
                    f"(not this device {self.device.id})",
                    level=logging.WARNING,
                )

        attempted: set[tuple[UUID, UUID]] = set()
        # Future -> (intent_id, mix_id, held origin Platform or None for peer copy)
        in_flight: dict[Future[None], tuple[UUID, UUID, Platform | None]] = {}

        def _reap_done() -> None:
            done = [fut for fut in in_flight if fut.done()]
            for fut in done:
                intent_id, mix_id, held = in_flight.pop(fut)
                if held is not None:
                    self._origin_slots[held].release()
                try:
                    fut.result()
                except Exception as exc:
                    # yt-dlp and platform errors vary; one bad URL must not abort the fill.
                    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                        raise
                    mix = self.catalog.mixes.get(mix_id)
                    label = mix.title if mix is not None else str(mix_id)
                    self.note(
                        f"download failed: {label}: {exc}",
                        level=logging.WARNING,
                    )
                    continue
                if self._has_local_file(mix_id):
                    self._nudge_peers_waiting_on_us(intent_id, mix_id)

        with ThreadPoolExecutor(
            max_workers=_FILL_POOL_WORKERS,
            thread_name_prefix="tunebag-dl",
        ) as pool:
            while True:
                _reap_done()
                in_flight_mixes = {mix_id for _, mix_id, _ in in_flight.values()}
                candidates: list[tuple[float, str, int, UUID, UUID]] = []
                for intent in self.intents():
                    assignment = self.assignment(intent.id)
                    if assignment is None:
                        continue
                    for index, mix_id in enumerate(assignment.mix_ids):
                        key = (intent.id, mix_id)
                        if (
                            key in attempted
                            or mix_id in in_flight_mixes
                            or self._has_local_file(mix_id)
                        ):
                            continue
                        if not self._fetch_actionable(
                            intent.id,
                            mix_id,
                            override_intent_id=override_intent_id,
                        ):
                            continue
                        urgency = self._mix_urgency(assignment, mix_id)
                        candidates.append(
                            (urgency, str(intent.id), index, intent.id, mix_id)
                        )
                candidates.sort()
                started = False
                for _urgency, _intent_key, _index, intent_id, mix_id in candidates:
                    if mix_id in in_flight_mixes:
                        continue
                    held: Platform | None = None
                    if not self._peer_can_supply(mix_id):
                        mix = self.catalog.mixes.get(mix_id)
                        if mix is None:
                            attempted.add((intent_id, mix_id))
                            continue
                        if not self._origin_slots[mix.platform].acquire(
                            blocking=False
                        ):
                            continue
                        held = mix.platform
                    attempted.add((intent_id, mix_id))
                    in_flight_mixes.add(mix_id)
                    fut = pool.submit(
                        self._ensure_local_file,
                        intent_id,
                        mix_id,
                        override_intent_id=override_intent_id,
                    )
                    in_flight[fut] = (intent_id, mix_id, held)
                    started = True
                if not in_flight:
                    break
                if not started:
                    wait(tuple(in_flight.keys()), return_when=FIRST_COMPLETED)

        # Drop leftovers from prior assignments / deleted intents before
        # rewriting intent folders. Batch only this short tail.
        with self._view_notice_batch():
            self._prune_unassigned_files()
            self._refresh_intent_folders()
        cached = len(self.files())
        self.note(f"fill caches end · {cached} cached")
        return cached

    def fill_now(self, intent_id: UUID) -> int:
        """One-shot origin fill of one intent to full device hours, then the cap returns."""
        if intent_id not in self.catalog.intents:
            raise KeyError(f"unknown intent {intent_id}")
        return self.fill_caches(override_intent_id=intent_id)

    def add_artists(
        self,
        urls: list[str],
        *,
        min_duration_seconds: int = DEFAULT_MIN_DURATION_SECONDS,
    ) -> list[Mix]:
        """List own uploads for each artist URL and write catalog rows only.

        Re-adding a URL already in the catalog reuses that Artist and only
        appends uploads not already present (by platform + platform id).
        """
        self.note(f"add artists start · {len(urls)} URL(s)")
        added: list[Mix] = []
        known = self._known_platform_keys()
        for url in urls:
            self.note(f"fetch artist list start: {url}")
            try:
                listing = self.source.list_uploads(url)
            except Exception as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                self.note(
                    f"fetch artist list failed: {url}: {exc}",
                    level=logging.WARNING,
                )
                raise
            # Catalog apply stays in the batch; cover HTTP stays outside so SSE
            # is not held across image downloads.
            cover_jobs: list[tuple[UUID, str, str]] = []
            with self._view_notice_batch():
                artist = self._artist_by_url(listing.url) or self._artist_by_url(url)
                if artist is None:
                    artist = Artist(
                        platform=listing.platform,
                        platform_id=listing.platform_id,
                        name=listing.name,
                        url=listing.url,
                    )
                    self._append_and_apply(
                        EventType.ARTIST_ADDED,
                        {
                            "id": str(artist.id),
                            "platform": artist.platform.value,
                            "platform_id": artist.platform_id,
                            "name": artist.name,
                            "url": artist.url,
                        },
                    )
                kept = 0
                by_platform = self._mixes_by_platform_key()
                for upload in listing.uploads:
                    mix = release_from_upload(artist.id, upload, min_duration_seconds)
                    if mix is None:
                        continue
                    key = (mix.platform, mix.platform_id)
                    if key in known:
                        existing = by_platform.get(key)
                        if (
                            existing is not None
                            and upload.cover_url
                            and not self.has_local_cover(existing.id)
                        ):
                            cover_jobs.append(
                                (existing.id, upload.cover_url, upload.url)
                            )
                        continue
                    self._append_and_apply(EventType.MIX_ADDED, encode_mix_added(mix))
                    known.add(key)
                    stored = self.catalog.mixes[mix.id]
                    added.append(stored)
                    by_platform[key] = stored
                    if upload.cover_url:
                        cover_jobs.append((stored.id, upload.cover_url, upload.url))
                    kept += 1
            for mix_id, cover_url, page_url in cover_jobs:
                self.ensure_cover(mix_id, cover_url, page_url=page_url)
            self.note(
                f"fetch artist list end: {listing.name} · "
                f"{len(listing.uploads)} upload(s), {kept} mix(es) added"
            )
        self.note(f"add artists end · {len(added)} mix(es)")
        self._maintenance.after_catalog_change(
            CatalogChange(
                CatalogChangeReason.ARTIST_INGEST,
                mixes_added=bool(added),
            )
        )
        return added

    def refresh_artists(
        self,
        artist_ids: list[UUID] | None = None,
        *,
        min_duration_seconds: int = DEFAULT_MIN_DURATION_SECONDS,
    ) -> list[Mix]:
        """Re-list known artists' own uploads; add new catalog rows only.

        Also backfills local cover art for known Releases that still lack a
        cached image when the listing exposes a cover URL.
        """
        if artist_ids:
            artists: list[Artist] = []
            for artist_id in artist_ids:
                artist = self.catalog.artists.get(artist_id)
                if artist is None:
                    raise KeyError(f"unknown artist {artist_id}")
                artists.append(artist)
        else:
            artists = list(self.catalog.artists.values())

        self.note(f"refresh artists start · {len(artists)} artist(s)")
        known = self._known_platform_keys()
        by_platform = self._mixes_by_platform_key()
        added: list[Mix] = []
        for artist in artists:
            self.note(f"fetch artist list start: {artist.url}")
            try:
                listing = self.source.list_uploads(artist.url)
            except Exception as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                self.note(
                    f"fetch artist list failed: {artist.url}: {exc}",
                    level=logging.WARNING,
                )
                raise
            cover_jobs: list[tuple[UUID, str, str]] = []
            with self._view_notice_batch():
                kept = 0
                for upload in listing.uploads:
                    mix = release_from_upload(artist.id, upload, min_duration_seconds)
                    if mix is None:
                        continue
                    key = (mix.platform, mix.platform_id)
                    if key in known:
                        existing = by_platform.get(key)
                        if (
                            existing is not None
                            and upload.cover_url
                            and not self.has_local_cover(existing.id)
                        ):
                            cover_jobs.append(
                                (existing.id, upload.cover_url, upload.url)
                            )
                        continue
                    self._append_and_apply(EventType.MIX_ADDED, encode_mix_added(mix))
                    known.add(key)
                    stored = self.catalog.mixes[mix.id]
                    added.append(stored)
                    by_platform[key] = stored
                    if upload.cover_url:
                        cover_jobs.append((stored.id, upload.cover_url, upload.url))
                    kept += 1
            for mix_id, cover_url, page_url in cover_jobs:
                self.ensure_cover(mix_id, cover_url, page_url=page_url)
            self.note(
                f"fetch artist list end: {artist.name} · "
                f"{len(listing.uploads)} upload(s), {kept} mix(es) added"
            )
        self.note(f"refresh artists end · {len(added)} mix(es)")
        self._maintenance.after_catalog_change(
            CatalogChange(
                CatalogChangeReason.ARTIST_INGEST,
                mixes_added=bool(added),
            )
        )
        return added

    def _known_platform_keys(self) -> set[tuple[Platform, str]]:
        return {(m.platform, m.platform_id) for m in self.catalog.mixes.values()}

    def _mixes_by_platform_key(self) -> dict[tuple[Platform, str], Mix]:
        return {(m.platform, m.platform_id): m for m in self.catalog.mixes.values()}

    def _artist_by_url(self, url: str) -> Artist | None:
        key = _normalize_artist_url(url)
        for artist in self.catalog.artists.values():
            if _normalize_artist_url(artist.url) == key:
                return artist
        return None

    def pair(self, payload: dict[str, Any]) -> Device:
        """In-process helper for tests.

        When the peer agent is reachable, runs a full dual-confirmed session.
        Otherwise applies local trust only (HTTP no longer exposes this path).
        """
        peer_agent = self._find_agent_for_payload(payload)
        if peer_agent is not None:
            return self.pair_with(peer_agent)
        return self._trust_payload(payload)

    def pair_with(self, host: DeviceAgent) -> Device:
        """Guest completes mutual pairing with an in-process host (both auto-confirm)."""
        if host is self:
            raise ValueError("cannot pair with self")
        host.start_pairing_session()
        status = host.pairing_session_status(include_pin=True)
        pin = status["pin"]
        assert isinstance(pin, str)
        self.join_pairing_session(pin=pin, host_agent=host)
        host.confirm_pairing_session()  # host first; may still wait for guest
        peer = self.confirm_pairing_session()
        if peer is None:
            peer = self.refresh_pairing_session_trust()
        if peer is None:
            raise ValueError("pairing did not complete")
        return peer

    def unpair(self, device_id: UUID) -> None:
        """Revoke trust in a Peer via a replicated DEVICE_UNPAIRED event."""
        if device_id == self.device.id:
            raise ValueError("cannot unpair this Device")
        self._append_and_apply(EventType.DEVICE_UNPAIRED, {"id": str(device_id)})
        # Hours/assignments cleared in apply; drop Cache blobs only that peer needed.
        self._prune_unassigned_files()

    def start_pairing_session(self) -> dict[str, Any]:
        """Host: open an ephemeral pairing session and show its PIN locally."""
        now = time.monotonic()
        session_id = secrets.token_urlsafe(16)
        pin = generate_pairing_pin()
        self._pairing_session = {
            "role": "host",
            "session_id": session_id,
            "pin": pin,
            "expires_at": now + PIN_TTL_SECONDS,
            "state": "waiting",
            "attempts": 0,
            "host_confirmed": False,
            "guest_confirmed": False,
            "guest_payload": None,
            "guest_nonce": None,
            "sas": None,
            "peer_name": None,
            "peer_url": None,
        }
        self._refresh_advertisement()
        self._arm_pairing_expiry_notice()
        self._mark_pairing_session()
        return self.pairing_session_status(include_pin=True)

    def pairing_session_status(self, *, include_pin: bool = False) -> dict[str, Any]:
        """Current pairing session view (PIN only when include_pin for local host UI)."""
        session = self._pairing_session
        if session is None:
            return {"active": False}
        if self._pairing_session_expired(session) and session["state"] not in {
            "complete",
            "cancelled",
        }:
            session["state"] = "cancelled"
            self._cancel_pairing_expiry_notice()
            self._mark_pairing_session()
        out: dict[str, Any] = {
            "active": session["state"] not in {"complete", "cancelled"},
            "role": session["role"],
            "session_id": session["session_id"],
            "state": session["state"],
            "expires_at_monotonic": session["expires_at"],
            "host_confirmed": session["host_confirmed"],
            "guest_confirmed": session["guest_confirmed"],
            "sas": session.get("sas"),
            "peer_name": session.get("peer_name"),
            "peer_device_id": (session.get("guest_payload") or {}).get("device_id")
            if session["role"] == "host"
            else session.get("host_device_id"),
        }
        if include_pin and session["role"] == "host" and session["state"] in {
            "waiting",
            "pending_confirm",
        }:
            out["pin"] = session["pin"]
            if self.base_url:
                out["offer"] = ephemeral_pair_offer(
                    url=self.base_url,
                    session_id=session["session_id"],
                    pin=session["pin"],
                )
        return out

    def cancel_pairing_session(self) -> dict[str, Any]:
        session = self._pairing_session
        if session is None:
            return {"active": False, "state": "cancelled"}
        if session["role"] == "guest" and session.get("host_url"):
            try:
                self._http_pair_cancel(session["host_url"], session["session_id"])
            except Exception as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                self.note(f"pair cancel notify failed: {exc}", level=logging.WARNING)
        elif session["role"] == "host":
            pass
        session["state"] = "cancelled"
        self._cancel_pairing_expiry_notice()
        self._refresh_advertisement()
        self._mark_pairing_session()
        return self.pairing_session_status()

    def receive_pair_cancel(self, session_id: str) -> dict[str, Any]:
        """Host: guest cancelled; burn the session."""
        session = self._require_host_session(session_id)
        session["state"] = "cancelled"
        self._cancel_pairing_expiry_notice()
        self._refresh_advertisement()
        self._mark_pairing_session()
        return self.pairing_session_status()

    def join_pairing_session(
        self,
        *,
        pin: str,
        host_agent: DeviceAgent | None = None,
        peer_url: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Guest: join a host pairing session with the one-time PIN."""
        pin_norm = normalize_pin(pin)
        if not pin_norm:
            raise ValueError("pin required")
        if host_agent is not None:
            host_session = host_agent._pairing_session
            if host_session is None:
                raise ValueError("host has no active pairing session")
            sid = session_id or host_session["session_id"]
            host_payload = host_agent.pairing_payload()
            guest_nonce = secrets.token_urlsafe(16)
            transcript = join_transcript(
                session_id=sid,
                pin=pin_norm,
                host_public_key_pem=host_payload["public_key_pem"],
                guest_public_key_pem=self.public_key_pem,
                guest_nonce=guest_nonce,
            )
            signature = base64.b64encode(self._private_key.sign(transcript)).decode(
                "ascii"
            )
            result = host_agent.receive_pair_join(
                {
                    "session_id": sid,
                    "pin": pin_norm,
                    "nonce": guest_nonce,
                    "signature": signature,
                    "payload": self.pairing_payload(),
                }
            )
            self._pairing_session = {
                "role": "guest",
                "session_id": sid,
                "pin": pin_norm,
                "expires_at": host_session["expires_at"],
                "state": "pending_confirm",
                "attempts": 0,
                "host_confirmed": False,
                "guest_confirmed": False,
                "sas": result["sas"],
                "peer_name": host_payload["name"],
                "host_payload": host_payload,
                "host_device_id": host_payload["device_id"],
                "host_agent": host_agent,
                "host_url": None,
                "guest_nonce": guest_nonce,
            }
            if host_agent not in self._reachable:
                self.connect(host_agent)
            self._arm_pairing_expiry_notice()
            self._mark_pairing_session()
            return self.pairing_session_status()

        if not peer_url:
            raise ValueError("peer_url or host_agent required")
        host_payload = self._http_fetch_pairing(peer_url)
        # Discover session_id from status if not in offer.
        if session_id is None:
            remote_status = self._http_pair_status(peer_url)
            session_id = remote_status.get("session_id")
            if not session_id:
                raise ValueError("host has no active pairing session")
        guest_nonce = secrets.token_urlsafe(16)
        transcript = join_transcript(
            session_id=session_id,
            pin=pin_norm,
            host_public_key_pem=host_payload["public_key_pem"],
            guest_public_key_pem=self.public_key_pem,
            guest_nonce=guest_nonce,
        )
        signature = base64.b64encode(self._private_key.sign(transcript)).decode("ascii")
        result = self._http_pair_join(
            peer_url,
            {
                "session_id": session_id,
                "pin": pin_norm,
                "nonce": guest_nonce,
                "signature": signature,
                "payload": self.pairing_payload(),
            },
        )
        self._pairing_session = {
            "role": "guest",
            "session_id": session_id,
            "pin": pin_norm,
            "expires_at": time.monotonic() + PIN_TTL_SECONDS,
            "state": "pending_confirm",
            "attempts": 0,
            "host_confirmed": False,
            "guest_confirmed": False,
            "sas": result["sas"],
            "peer_name": host_payload.get("name"),
            "host_payload": {**host_payload, "url": peer_url.rstrip("/")},
            "host_device_id": host_payload.get("device_id"),
            "host_agent": None,
            "host_url": peer_url.rstrip("/"),
            "guest_nonce": guest_nonce,
        }
        self._arm_pairing_expiry_notice()
        self._mark_pairing_session()
        return self.pairing_session_status()

    def receive_pair_join(self, body: dict[str, Any]) -> dict[str, Any]:
        """Host: validate PIN + guest signature and move to pending_confirm."""
        session = self._require_host_session(body.get("session_id"))
        if session["state"] != "waiting":
            raise ValueError("pairing session is not accepting joins")
        if self._pairing_session_expired(session):
            session["state"] = "cancelled"
            self._cancel_pairing_expiry_notice()
            self._refresh_advertisement()
            self._mark_pairing_session()
            raise ValueError("pairing session expired")
        pin = body.get("pin") or ""
        if not pins_equal(pin, session["pin"]):
            session["attempts"] = int(session["attempts"]) + 1
            if session["attempts"] >= PIN_MAX_ATTEMPTS:
                session["state"] = "cancelled"
                self._cancel_pairing_expiry_notice()
                self._refresh_advertisement()
                self._mark_pairing_session()
                raise ValueError("too many PIN attempts")
            raise ValueError("invalid PIN")
        guest_payload = body.get("payload")
        if not isinstance(guest_payload, dict):
            raise ValueError("join missing guest payload")
        nonce = body.get("nonce")
        signature = body.get("signature")
        if not isinstance(nonce, str) or not isinstance(signature, str):
            raise ValueError("join missing nonce or signature")
        transcript = join_transcript(
            session_id=session["session_id"],
            pin=session["pin"],
            host_public_key_pem=self.public_key_pem,
            guest_public_key_pem=guest_payload["public_key_pem"],
            guest_nonce=nonce,
        )
        try:
            _load_public_key(guest_payload["public_key_pem"]).verify(
                base64.b64decode(signature),
                transcript,
            )
        except (InvalidSignature, ValueError, TypeError) as exc:
            session["attempts"] = int(session["attempts"]) + 1
            if session["attempts"] >= PIN_MAX_ATTEMPTS:
                session["state"] = "cancelled"
                self._cancel_pairing_expiry_notice()
                self._refresh_advertisement()
                self._mark_pairing_session()
            raise ValueError("invalid join signature") from exc
        sas = sas_for_session(
            session_id=session["session_id"],
            host_public_key_pem=self.public_key_pem,
            guest_public_key_pem=guest_payload["public_key_pem"],
        )
        session["guest_payload"] = guest_payload
        session["guest_nonce"] = nonce
        session["peer_name"] = guest_payload.get("name")
        session["sas"] = sas
        session["state"] = "pending_confirm"
        self._refresh_advertisement()
        self._mark_pairing_session()
        return {"ok": True, "sas": sas, "peer_name": self.name}

    def confirm_pairing_session(self) -> Device | None:
        """Confirm the pending pairing session (host or guest).

        Returns the trusted Peer when both sides have confirmed; otherwise None
        while waiting for the other device.
        """
        session = self._pairing_session
        if session is None:
            raise ValueError("no active pairing session")
        if self._pairing_session_expired(session) and session["state"] != "complete":
            session["state"] = "cancelled"
            self._cancel_pairing_expiry_notice()
            self._mark_pairing_session()
            raise ValueError("pairing session expired")
        if session["state"] == "complete":
            return self.refresh_pairing_session_trust()
        if session["state"] != "pending_confirm":
            raise ValueError("pairing session is not ready to confirm")
        if session["role"] == "host":
            return self._confirm_as_host()
        return self._confirm_as_guest()

    def refresh_pairing_session_trust(self) -> Device | None:
        """Guest: if the host session completed, write local DEVICE_PAIRED."""
        session = self._pairing_session
        if session is None:
            return None
        if session["state"] == "complete" and session["role"] == "guest":
            host_payload = session.get("host_payload")
            if isinstance(host_payload, dict):
                return self._trust_payload(host_payload)
            return None
        if session["role"] != "guest" or session["state"] != "pending_confirm":
            return None
        host_agent = session.get("host_agent")
        if isinstance(host_agent, DeviceAgent):
            remote = host_agent._pairing_session
            if remote and remote.get("state") == "complete":
                session["state"] = "complete"
                session["host_confirmed"] = True
                session["guest_confirmed"] = True
                self._cancel_pairing_expiry_notice()
                self._mark_pairing_session()
                host_payload = session.get("host_payload")
                assert isinstance(host_payload, dict)
                return self._trust_payload(host_payload)
            return None
        host_url = session.get("host_url")
        if not isinstance(host_url, str):
            return None
        remote = self._http_pair_status(host_url)
        if remote.get("state") != "complete":
            return None
        session["state"] = "complete"
        session["host_confirmed"] = True
        session["guest_confirmed"] = True
        self._cancel_pairing_expiry_notice()
        self._mark_pairing_session()
        host_payload = session.get("host_payload")
        assert isinstance(host_payload, dict)
        return self._trust_payload(host_payload)

    def receive_pair_confirm(self, body: dict[str, Any]) -> dict[str, Any]:
        """Host: guest Confirm with signature over the confirm transcript."""
        session = self._require_host_session(body.get("session_id"))
        if session["state"] not in {"pending_confirm", "complete"}:
            raise ValueError("pairing session is not pending confirm")
        guest_payload = session.get("guest_payload")
        if not isinstance(guest_payload, dict):
            raise ValueError("no guest bound to session")
        signature = body.get("signature")
        if not isinstance(signature, str):
            raise ValueError("confirm missing signature")
        transcript = confirm_transcript(
            session_id=session["session_id"],
            host_public_key_pem=self.public_key_pem,
            guest_public_key_pem=guest_payload["public_key_pem"],
            role="guest",
        )
        try:
            _load_public_key(guest_payload["public_key_pem"]).verify(
                base64.b64decode(signature),
                transcript,
            )
        except (InvalidSignature, ValueError, TypeError) as exc:
            raise ValueError("invalid confirm signature") from exc
        session["guest_confirmed"] = True
        peer: Device | None = None
        if session["host_confirmed"]:
            peer = self._finalize_host_pairing()
        else:
            self._mark_pairing_session()
        return {
            "ok": True,
            "complete": session["state"] == "complete",
            "host_payload": self.pairing_payload() if session["state"] == "complete" else None,
            "peer": {"id": str(peer.id), "name": peer.name} if peer else None,
        }

    def _confirm_as_host(self) -> Device | None:
        session = self._pairing_session
        assert session is not None and session["role"] == "host"
        guest_payload = session.get("guest_payload")
        if not isinstance(guest_payload, dict):
            raise ValueError("no guest bound to session")
        session["host_confirmed"] = True
        self._mark_pairing_session()
        if not session["guest_confirmed"]:
            return None
        return self._finalize_host_pairing()

    def _confirm_as_guest(self) -> Device | None:
        session = self._pairing_session
        assert session is not None and session["role"] == "guest"
        host_payload = session.get("host_payload")
        if not isinstance(host_payload, dict):
            raise ValueError("missing host payload")
        transcript = confirm_transcript(
            session_id=session["session_id"],
            host_public_key_pem=host_payload["public_key_pem"],
            guest_public_key_pem=self.public_key_pem,
            role="guest",
        )
        signature = base64.b64encode(self._private_key.sign(transcript)).decode("ascii")
        host_agent = session.get("host_agent")
        if isinstance(host_agent, DeviceAgent):
            result = host_agent.receive_pair_confirm(
                {"session_id": session["session_id"], "signature": signature}
            )
            session["guest_confirmed"] = True
            if not result.get("complete"):
                self._mark_pairing_session()
                return None
            session["host_confirmed"] = True
            session["state"] = "complete"
            self._cancel_pairing_expiry_notice()
            self._mark_pairing_session()
            return self._trust_payload(host_payload)
        host_url = session.get("host_url")
        if not isinstance(host_url, str):
            raise ValueError("missing host url")
        result = self._http_pair_confirm(
            host_url,
            {"session_id": session["session_id"], "signature": signature},
        )
        session["guest_confirmed"] = True
        if not result.get("complete"):
            self._mark_pairing_session()
            return None
        remote_host = result.get("host_payload") or host_payload
        if isinstance(remote_host, dict) and "url" not in remote_host:
            remote_host = {**remote_host, "url": host_url}
        peer = self._trust_payload(remote_host)
        session["state"] = "complete"
        session["host_confirmed"] = True
        self._cancel_pairing_expiry_notice()
        self._mark_pairing_session()
        return peer

    def _finalize_host_pairing(self) -> Device:
        session = self._pairing_session
        assert session is not None and session["role"] == "host"
        guest_payload = session.get("guest_payload")
        assert isinstance(guest_payload, dict)
        peer = self._trust_payload(guest_payload)
        session["state"] = "complete"
        self._cancel_pairing_expiry_notice()
        self._refresh_advertisement()
        self._mark_pairing_session()
        # Connect in-process guest if present on discovery.
        if url := guest_payload.get("url"):
            peer_agent = self._discovery_agent_at(str(url))
            if peer_agent is not None and peer_agent is not self:
                self.connect(peer_agent)
        return peer

    def _require_host_session(self, session_id: Any) -> dict[str, Any]:
        session = self._pairing_session
        if session is None or session.get("role") != "host":
            raise ValueError("no host pairing session")
        if not isinstance(session_id, str) or session_id != session["session_id"]:
            raise ValueError("session_id mismatch")
        if session["state"] in {"cancelled"}:
            raise ValueError("pairing session cancelled")
        if self._pairing_session_expired(session) and session["state"] != "complete":
            session["state"] = "cancelled"
            raise ValueError("pairing session expired")
        return session

    def _pairing_session_expired(self, session: dict[str, Any]) -> bool:
        return time.monotonic() > float(session["expires_at"])

    def _find_agent_for_payload(self, payload: dict[str, Any]) -> DeviceAgent | None:
        pem = payload.get("public_key_pem")
        if not isinstance(pem, str):
            return None
        for agent in self._reachable:
            if agent.public_key_pem == pem:
                return agent
        if url := payload.get("url"):
            agent = self._discovery_agent_at(str(url))
            if agent is not None and agent is not self:
                return agent
        return None

    def _refresh_advertisement(self) -> None:
        if not self.base_url:
            return
        try:
            self._discovery.advertise(
                LanAdvertisement(
                    name=self.name,
                    fingerprint=self.fingerprint(),
                    locator=self.base_url,
                    pairing=self.pairing_session_open(),
                )
            )
        except Exception as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            # Pairing must not fail because LAN discovery refresh failed.
            self.note(f"discovery advertise refresh failed: {exc}", level=logging.WARNING)
        publish = getattr(self._discovery, "publish", None)
        if callable(publish):
            try:
                publish(self, locator=self.base_url)
            except Exception as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                self.note(f"discovery publish refresh failed: {exc}", level=logging.WARNING)

    def remember_peer_url(self, peer_id: UUID, url: str) -> None:
        self._peer_urls[peer_id] = url
        self._persist_locator_hints()

    def peer_urls(self) -> dict[UUID, str]:
        return dict(self._peer_urls)

    def _persist_locator_hints(self) -> None:
        if self._store is None:
            return
        self._store.save_locator_hints(self._peer_urls)

    def _prune_stale_locator_hints(self) -> None:
        """Keep only hints for currently trusted Peers; rewrite sidecar if pruned."""
        trusted = {peer.id for peer in self.peers()}
        stale = [peer_id for peer_id in self._peer_urls if peer_id not in trusted]
        if not stale:
            return
        for peer_id in stale:
            self._peer_urls.pop(peer_id, None)
        self._persist_locator_hints()

    def pair_candidates(self) -> list[dict[str, Any]]:
        """Discovered advertisements whose public keys are not yet trusted."""
        return [dict(c) for c in self._pair_candidates.values()]

    def refresh_discovery(self) -> None:
        """Browse the LAN and process advertisements (start / network / forced)."""
        self._process_browse()
        self._last_discovery_at = self._clock()

    def on_network_change(self) -> None:
        """Browse immediately when interfaces change."""
        self.refresh_discovery()

    def tick_discovery(self, now: datetime | None = None) -> None:
        """Slow periodic browse while no trusted Peer has a live proved session."""
        if self._has_live_trusted_session():
            return
        current = now if now is not None else self._clock()
        if self._last_discovery_at is not None:
            elapsed = (current - self._last_discovery_at).total_seconds()
            if elapsed < DISCOVERY_REFRESH_SECONDS:
                return
        self.refresh_discovery()

    def _start_discovery(self) -> None:
        self._refresh_advertisement()
        self.refresh_discovery()

    def _has_live_trusted_session(self) -> bool:
        for agent in self._reachable:
            if id(agent) in self._proved_agents and self._trusts_public_key(
                agent.public_key_pem
            ):
                return True
        return False

    def _process_browse(self) -> None:
        before = set(self._pair_candidates)
        for ad in self._discovery.browse():
            if self.base_url and ad.locator.rstrip("/") == self.base_url.rstrip("/"):
                continue
            try:
                payload = self._fetch_discovery_pairing(ad.locator)
            except Exception as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                self.note(
                    f"discovery pairing fetch failed ({ad.locator}): {exc}",
                    level=logging.WARNING,
                )
                continue
            public_key_pem = payload.get("public_key_pem")
            if not isinstance(public_key_pem, str) or not public_key_pem:
                continue
            if self._trusts_public_key(public_key_pem):
                peer_id = UUID(payload["device_id"]) if "device_id" in payload else None
                if peer_id is None:
                    peer = next(
                        (
                            d
                            for d in self.peers()
                            if d.public_key_pem == public_key_pem
                        ),
                        None,
                    )
                    if peer is None:
                        continue
                    peer_id = peer.id
                if not self._meet_discovered_peer(
                    peer_id, ad.locator, public_key_pem
                ):
                    continue
                self._pair_candidates.pop(ad.locator, None)
                continue
            fingerprint = (
                payload.get("fingerprint")
                or payload.get("short_code")
                or ad.fingerprint
            )
            self._pair_candidates[ad.locator] = {
                "name": payload.get("name") or ad.name,
                "fingerprint": fingerprint,
                "short_code": fingerprint,
                "locator": ad.locator,
                "pairing": ad.pairing,
                "public_key_pem": public_key_pem,
                "device_id": payload.get("device_id"),
                "priority": payload.get("priority"),
            }
        after = set(self._pair_candidates)
        if before != after:
            self._mark_view_sections(UIViewSection.PEERS)

    def _meet_discovered_peer(
        self, peer_id: UUID, locator: str, public_key_pem: str
    ) -> bool:
        """Prove possession, then refresh Locator hint and sync."""
        peer_agent = self._discovery_agent_at(locator)
        if peer_agent is not None and peer_agent is not self:
            added_here = peer_agent not in self._reachable
            if added_here:
                self._reachable.append(peer_agent)
            added_there = self not in peer_agent._reachable
            if added_there:
                peer_agent._reachable.append(self)
            if not self._ensure_agent_proved(peer_agent):
                if added_here and peer_agent in self._reachable:
                    self._reachable.remove(peer_agent)
                if added_there and self in peer_agent._reachable:
                    peer_agent._reachable.remove(self)
                return False
            self.remember_peer_url(peer_id, locator)
            self.request_sync(fill=False)
            peer_agent.request_sync(fill=False)
            return True
        if locator.startswith("inproc://"):
            return False
        if not self._ensure_http_peer_proved(locator, public_key_pem):
            return False
        self.remember_peer_url(peer_id, locator)
        self.request_sync(fill=False)
        return True

    def _fetch_discovery_pairing(self, locator: str) -> dict[str, Any]:
        fetch = getattr(self._discovery, "pairing_payload", None)
        if callable(fetch):
            try:
                return fetch(locator)
            except ValueError:
                pass
        if locator.startswith("inproc://"):
            raise ValueError(f"no in-process pairing for {locator}")
        return self._http_fetch_pairing(locator)

    def _discovery_agent_at(self, locator: str) -> DeviceAgent | None:
        getter = getattr(self._discovery, "agent_at", None)
        if not callable(getter):
            return None
        agent = getter(locator)
        return agent if isinstance(agent, DeviceAgent) else None

    def ingest_events(self, events: list[Event], *, rebuild: bool = True) -> None:
        mixes_before = len(self.catalog.mixes)
        with self._ingest_notice_pass():
            for event in events:
                self._ingest(event)
        if not rebuild:
            return
        mixes_added = len(self.catalog.mixes) > mixes_before
        self._maintenance.after_catalog_change(
            CatalogChange(
                CatalogChangeReason.PEER_INGEST,
                mixes_added=mixes_added,
            )
        )

    def add_mix_tag(self, mix_id: UUID, tag: str) -> Mix:
        if mix_id not in self.catalog.mixes:
            raise KeyError(f"unknown mix {mix_id}")
        cleaned = tag.strip().lower()
        if not cleaned:
            return self.catalog.mixes[mix_id]
        if cleaned in self.catalog.mixes[mix_id].tags:
            return self.catalog.mixes[mix_id]
        with self._view_notice_batch():
            self._append_and_apply(
                EventType.MIX_TAG_ADDED,
                {"mix_id": str(mix_id), "tag": cleaned},
            )
        return self.catalog.mixes[mix_id]

    def remove_mix_tag(self, mix_id: UUID, tag: str) -> Mix:
        if mix_id not in self.catalog.mixes:
            raise KeyError(f"unknown mix {mix_id}")
        cleaned = tag.strip().lower()
        if not cleaned:
            return self.catalog.mixes[mix_id]
        if cleaned not in self.catalog.mixes[mix_id].tags:
            return self.catalog.mixes[mix_id]
        with self._view_notice_batch():
            self._append_and_apply(
                EventType.MIX_TAG_REMOVED,
                {"mix_id": str(mix_id), "tag": cleaned},
            )
        return self.catalog.mixes[mix_id]

    def tag_mix(self, mix_id: UUID, tags: list[str]) -> Mix:
        """Diff helper: emit ADD/REMOVE so the mix ends with exactly ``tags``."""
        if mix_id not in self.catalog.mixes:
            raise KeyError(f"unknown mix {mix_id}")
        desired = Mix.normalize_tags(list(tags))
        current = set(self.catalog.mixes[mix_id].tags)
        desired_set = set(desired)
        with self._view_notice_batch():
            for tag in sorted(desired_set - current):
                self._append_and_apply(
                    EventType.MIX_TAG_ADDED,
                    {"mix_id": str(mix_id), "tag": tag},
                )
            for tag in sorted(current - desired_set):
                self._append_and_apply(
                    EventType.MIX_TAG_REMOVED,
                    {"mix_id": str(mix_id), "tag": tag},
                )
        return self.catalog.mixes[mix_id]

    def rate_mix(self, mix_id: UUID, stars: Stars) -> Mix:
        if mix_id not in self.catalog.mixes:
            raise KeyError(f"unknown mix {mix_id}")
        with self._view_notice_batch():
            self._append_and_apply(
                EventType.MIX_RATED,
                {"mix_id": str(mix_id), "stars": int(stars)},
            )
        return self.catalog.mixes[mix_id]

    def reject_mix(self, mix_id: UUID) -> Mix:
        """Append a Reject Event immediately (confirm-click; no undo buffer)."""
        self.commit_reject_file_deletes()
        if mix_id not in self.catalog.mixes:
            raise KeyError(f"unknown mix {mix_id}")
        if self.catalog.mixes[mix_id].rejected:
            return self.catalog.mixes[mix_id]
        self._skips.cancel(mix_id)
        with self._view_notice_batch():
            self._append_and_apply(
                EventType.MIX_REJECTED,
                {"mix_id": str(mix_id)},
            )
            self._maintenance.after_catalog_change(
                CatalogChange(CatalogChangeReason.REJECT_COMMIT)
            )
        return self.catalog.mixes[mix_id]

    def pending_skips(self) -> list[SkipPending]:
        self.commit_pending_skips()
        return self._skips.pending()

    def commit_pending_skips(self) -> list[UUID]:
        """Commit skips whose 5‑minute delay has ended; rebuild + retire file."""
        committed: list[UUID] = []
        with self._view_notice_batch():
            for pending in self._skips.ready_to_commit(now=self._clock()):
                if pending.mix_id not in self.catalog.mixes:
                    continue
                mix = self.catalog.mixes[pending.mix_id]
                if mix.skipped or mix.played:
                    committed.append(pending.mix_id)
                    continue
                self._append_and_apply(
                    EventType.SKIPPED,
                    {"mix_id": str(pending.mix_id)},
                )
                self._maintenance.after_catalog_change(
                    CatalogChange(
                        CatalogChangeReason.SKIP_COMMIT,
                        mix_id=pending.mix_id,
                    )
                )
                committed.append(pending.mix_id)
        return committed

    def un_reject_mix(self, mix_id: UUID) -> Mix:
        """Clear a Reject so the Mix may re-enter sequences again."""
        self.commit_reject_file_deletes()
        if mix_id not in self.catalog.mixes:
            raise KeyError(f"unknown mix {mix_id}")
        if not self.catalog.mixes[mix_id].rejected:
            return self.catalog.mixes[mix_id]
        with self._view_notice_batch():
            self._append_and_apply(
                EventType.MIX_UNREJECTED,
                {"mix_id": str(mix_id)},
            )
            self._maintenance.after_catalog_change(
                CatalogChange(CatalogChangeReason.UN_REJECT)
            )
        return self.catalog.mixes[mix_id]

    def commit_reject_file_deletes(self) -> list[UUID]:
        """Delete File (and cover) bytes for Rejects whose Soft window has ended."""
        deleted: list[UUID] = []
        for mix_id in self._reject_file_deletes.ready_to_delete(now=self._clock()):
            mix = self.catalog.mixes.get(mix_id)
            if mix is None or not mix.rejected:
                continue
            # Always clear local audio/cover — cover may exist without a blob.
            self.remove_local_file(mix_id)
            deleted.append(mix_id)
        return deleted

    def _arm_reject_file_deletes_from_catalog(self) -> None:
        """Schedule Soft→Hard File deletes from projected Reject author times."""
        for mix in self.catalog.mixes.values():
            if mix.rejected and mix.rejected_at is not None:
                self._reject_file_deletes.schedule(mix.id, mix.rejected_at)
            else:
                self._reject_file_deletes.cancel(mix.id)

    def _sync_reject_file_delete_schedule(self, mix_id: UUID) -> None:
        """Keep local File-delete schedule aligned with Catalog Reject state."""
        mix = self.catalog.mixes.get(mix_id)
        if mix is not None and mix.rejected and mix.rejected_at is not None:
            self._reject_file_deletes.schedule(mix_id, mix.rejected_at)
        else:
            self._reject_file_deletes.cancel(mix_id)

    def create_intent(
        self,
        name: str,
        *,
        tags: list[str] | None = None,
        artist_ids: list[UUID] | None = None,
        platforms: list[Platform] | None = None,
        distribution: StarDistribution | None = None,
        seed: int | None = None,
        device_hours: list[DeviceHoursSpec] | None = None,
        intent_id: UUID | None = None,
    ) -> Intent:
        hours = _device_hours_from_spec(list(device_hours or []))
        self._require_known_devices([dh.device_id for dh in hours])
        intent = Intent(
            id=intent_id if intent_id is not None else new_id(),
            name=name,
            tags=list(tags or []),
            artist_ids=list(artist_ids or []),
            platforms=(
                list(platforms) if platforms is not None else default_intent_platforms()
            ),
            distribution=distribution or StarDistribution(),
            device_hours=hours,
            seed=seed if seed is not None else random.randrange(1 << 31),
        )
        self._upsert_intent_and_rebuild(intent, fill=True)
        return self.catalog.intents[intent.id]

    def set_device_hours(
        self,
        intent_id: UUID,
        device_id: UUID,
        budget_seconds: int,
        *,
        expires_at: datetime | None | object = _UNSET,
    ) -> Intent:
        intent = self.catalog.intents.get(intent_id)
        if intent is None:
            raise KeyError(f"unknown intent {intent_id}")
        self._require_known_devices([device_id])
        existing = next(
            (dh for dh in intent.device_hours if dh.device_id == device_id),
            None,
        )
        if expires_at is _UNSET:
            resolved_expiry = existing.expires_at if existing is not None else None
        else:
            resolved_expiry = _as_naive_utc(expires_at)  # type: ignore[arg-type]
        hours = [dh for dh in intent.device_hours if dh.device_id != device_id]
        hours.append(
            DeviceHours(
                device_id=device_id,
                budget_seconds=budget_seconds,
                expires_at=resolved_expiry,
            )
        )
        updated = intent.model_copy(update={"device_hours": hours})
        self._upsert_intent_and_rebuild(updated, fill=True)
        return self.catalog.intents[intent_id]

    def delete_artist(self, artist_id: UUID) -> None:
        if artist_id not in self.catalog.artists:
            raise KeyError(f"unknown artist {artist_id}")
        self._append_and_apply(
            EventType.ARTIST_DELETED,
            {"id": str(artist_id)},
        )
        self._maintenance.after_catalog_change(
            CatalogChange(CatalogChangeReason.ARTIST_DELETE)
        )

    def delete_intent(self, intent_id: UUID) -> None:
        if intent_id not in self.catalog.intents:
            raise KeyError(f"unknown intent {intent_id}")
        self._append_and_apply(
            EventType.INTENT_DELETED,
            {"id": str(intent_id)},
        )
        self._maintenance.after_catalog_change(
            CatalogChange(CatalogChangeReason.INTENT_DELETE)
        )

    def update_intent(
        self,
        intent_id: UUID,
        *,
        name: str | None = None,
        tags: list[str] | None = None,
        artist_ids: list[UUID] | None = None,
        platforms: list[Platform] | None = None,
        distribution: StarDistribution | None = None,
        device_hours: list[DeviceHoursSpec] | None = None,
    ) -> Intent:
        intent = self.catalog.intents.get(intent_id)
        if intent is None:
            raise KeyError(f"unknown intent {intent_id}")
        updates: dict[str, Any] = {}
        cleared_device_ids: list[UUID] | None = None
        if name is not None:
            updates["name"] = name
        if tags is not None:
            updates["tags"] = list(tags)
        if artist_ids is not None:
            updates["artist_ids"] = list(artist_ids)
        if platforms is not None:
            updates["platforms"] = list(platforms)
        if distribution is not None:
            updates["distribution"] = distribution
        if device_hours is not None:
            hours = _device_hours_from_spec(device_hours)
            self._require_known_devices([dh.device_id for dh in hours])
            updates["device_hours"] = hours
            kept = {dh.device_id for dh in hours}
            cleared = [dh.device_id for dh in intent.device_hours if dh.device_id not in kept]
            if cleared:
                cleared_device_ids = cleared
        if not updates:
            return intent
        updated = intent.model_copy(update=updates)
        self._upsert_intent_and_rebuild(
            updated,
            cleared_device_ids=cleared_device_ids,
            fill=True,
        )
        return self.catalog.intents[intent_id]

    def refresh_intent_sequence(self, intent_id: UUID) -> Intent:
        """Re-roll the intent seed and rebuild shared sequence + assignments."""
        intent = self.catalog.intents.get(intent_id)
        if intent is None:
            raise KeyError(f"unknown intent {intent_id}")
        updated = intent.model_copy(update={"seed": random.randrange(1 << 31)})
        self._upsert_intent_and_rebuild(updated, fill=True)
        return self.catalog.intents[intent_id]

    def apply_expired_hours(self) -> list[tuple[UUID, UUID]]:
        """Remove device hours whose expires_at has passed; prune exclusive files."""
        now = _as_naive_utc(self._clock())
        assert now is not None
        applied: list[tuple[UUID, UUID]] = []
        for intent in list(self.intents()):
            expired_ids = [
                dh.device_id
                for dh in intent.device_hours
                if (exp := _as_naive_utc(dh.expires_at)) is not None and exp <= now
            ]
            if not expired_ids:
                continue
            expired_set = set(expired_ids)
            remaining = [
                dh for dh in intent.device_hours if dh.device_id not in expired_set
            ]
            updated = intent.model_copy(update={"device_hours": remaining})
            self._upsert_intent_and_rebuild(updated, cleared_device_ids=expired_ids)
            for device_id in expired_ids:
                applied.append((intent.id, device_id))
        if applied:
            self._prune_unassigned_files()
        return applied

    def _require_known_devices(self, device_ids: list[UUID]) -> None:
        """Reject hours for device ids that are not local or a known peer."""
        unknown = [device_id for device_id in device_ids if device_id not in self.catalog.devices]
        if not unknown:
            return
        bad = ", ".join(str(device_id) for device_id in unknown)
        raise ValueError(f"unknown device_id(s) for hours: {bad}")

    def _prune_unassigned_files(self) -> None:
        """Drop local blobs no remaining assignment wants (except currently playing).

        Soft Rejected Releases keep bytes until Soft → Hard (ADR-0007), even when
        rebuild drops them from assignments. Playlog previous-File cushion also
        keeps the immediate previous Release briefly for ◀.
        """
        wanted: set[UUID] = set()
        for intent in self.intents():
            assignment = self.assignment(intent.id)
            if assignment is None:
                continue
            wanted.update(assignment.mix_ids)
        playing = self.current_mix() if self.is_playing() else None
        now = self._clock()
        for mix_id in list(self._cache.local_ids()):
            if mix_id in wanted:
                continue
            if playing is not None and mix_id == playing:
                continue
            if self._is_playlog_previous_retained(mix_id):
                continue
            mix = self.catalog.mixes.get(mix_id)
            if mix is not None and is_soft_rejected(
                rejected=mix.rejected,
                rejected_at=mix.rejected_at,
                now=now,
            ):
                continue
            self.remove_local_file(mix_id)

    def add_mix(
        self,
        *,
        title: str,
        url: str,
        duration_seconds: int,
        platform: Platform,
        platform_id: str,
        artist_name: str,
        size_bytes: int | None = None,
        cover_url: str | None = None,
    ) -> Mix:
        artist = Artist(
            platform=platform,
            platform_id=f"artist:{platform_id}",
            name=artist_name,
            url=url,
        )
        mix = Mix(
            artist_id=artist.id,
            platform=platform,
            platform_id=platform_id,
            title=title,
            url=url,
            duration_seconds=duration_seconds,
            size_bytes=size_bytes,
            cover_url=cover_url,
        )
        with self._view_notice_batch():
            self._append_and_apply(
                EventType.ARTIST_ADDED,
                {
                    "id": str(artist.id),
                    "platform": platform.value,
                    "platform_id": artist.platform_id,
                    "name": artist.name,
                    "url": artist.url,
                },
            )
            self._append_and_apply(EventType.MIX_ADDED, encode_mix_added(mix))
        return self.catalog.mixes[mix.id]

    def export_events(self) -> list[Event]:
        return self._journal.export()

    def iter_events(self):
        """Stream the durable Event log (HTTP NDJSON export)."""
        return self._journal.iter_all()

    def iter_events_after_cursors(self, cursors: dict[str, int]):
        """Stream events after per-author seq watermarks."""
        return self._journal.iter_after_cursors(cursors)

    def event_cursors(self) -> dict[str, int]:
        """Local per-author max seq for incremental peer pull."""
        return self._journal.author_cursors()

    def sync(self, *, fill: bool = True) -> None:
        self.commit_reject_file_deletes()
        self.commit_pending_skips()
        self.apply_expired_hours()
        self.note("sync start")
        mixes_before = len(self.catalog.mixes)
        with self._ingest_notice_pass():
            for agent in list(self._reachable):
                if not self._trusts_public_key(agent.public_key_pem):
                    continue
                if not self._ensure_agent_proved(agent):
                    continue
                before = len(self._journal._seen_event_ids)
                for event in agent.export_events():
                    self._ingest(event)
                ingested = len(self._journal._seen_event_ids) - before
                self.note(f"sync peer {agent.name}: {ingested} new event(s)")
            trusted_ids = {peer.id for peer in self.peers()}
            for peer_id, url in list(self._peer_urls.items()):
                if peer_id not in trusted_ids:
                    continue
                if str(url).startswith("inproc://"):
                    # In-process Locators sync via _reachable, not HTTP.
                    continue
                peer = self.catalog.devices.get(peer_id)
                if peer is None:
                    continue
                # HTTP Locators have no durable socket: challenge on every pull.
                if not self._ensure_http_peer_proved(url, peer.public_key_pem):
                    continue
                label = peer.name
                before = len(self._journal._seen_event_ids)
                # rebuild=False: sync finishes one rebuild/fill pass after all peers.
                self.ingest_events(self._http_fetch_events(url), rebuild=False)
                ingested = len(self._journal._seen_event_ids) - before
                self.note(f"sync peer {label} ({url}): {ingested} new event(s)")
        # Peer may have applied our expiry; drop exclusive locals after ingest.
        self.apply_expired_hours()
        # Mixes / merged Explore hours from peers need local sequence+assignment refresh.
        mixes_added = len(self.catalog.mixes) > mixes_before
        if fill:
            self.note("sync catalog end · filling caches")
        else:
            self.note("sync catalog end")
        self._maintenance.after_catalog_change(
            CatalogChange(
                CatalogChangeReason.SYNC,
                mixes_added=mixes_added,
                fill=fill,
            )
        )

    def _trusted_reachable_peers(self) -> list[DeviceAgent]:
        return [
            peer
            for peer in self._reachable
            if self._trusts_public_key(peer.public_key_pem)
        ]

    def _peer_has_release(self, peer: DeviceAgent, mix_id: UUID) -> bool:
        return peer._has_local_file(mix_id)

    def _peer_can_supply(self, mix_id: UUID) -> bool:
        """True when a trusted reachable peer already has File bytes for ``mix_id``."""
        return any(
            self._peer_has_release(peer, mix_id)
            for peer in self._trusted_reachable_peers()
        )

    def _fetch_actionable(
        self,
        intent_id: UUID,
        mix_id: UUID,
        *,
        override_intent_id: UUID | None = None,
    ) -> bool:
        """True when a peer already has bytes or this device may origin-fetch now.

        False means Metered hold or preferred-peer wait — leave pending and idle
        until a re-kick (play, metered flip, peer cache, connect, …).
        """
        if self._has_local_file(mix_id):
            return False
        for peer in self._trusted_reachable_peers():
            if self._peer_has_release(peer, mix_id):
                return True
        preferred = self._preferred_origin_agent(intent_id, mix_id)
        if preferred is not self and preferred is not None:
            return False
        return self._origin_fetch_allowed(intent_id, mix_id, override_intent_id)

    def _nudge_peers_waiting_on_us(self, intent_id: UUID, mix_id: UUID) -> None:
        """Resume fill on peers for whom we are the preferred origin for ``mix_id``.

        Avoids a peer-copy (phone ← laptop) nudging the preferred origin to
        keep origin-fetching the rest of the assignment mid handoff.
        """
        for peer in self._trusted_reachable_peers():
            if not self._assignment_includes(peer, intent_id, mix_id):
                continue
            if peer._preferred_origin_agent(intent_id, mix_id) is self:
                peer.request_fill()

    def _ensure_local_file(
        self,
        intent_id: UUID,
        mix_id: UUID,
        *,
        override_intent_id: UUID | None = None,
    ) -> None:
        """Urgency/metered/preferred-origin policy; Cache owns peer/origin I/O."""
        if self._has_local_file(mix_id):
            return
        mix = self.catalog.mixes.get(mix_id)
        if mix is None:
            return
        peers = self._trusted_reachable_peers()
        preferred = self._preferred_origin_agent(intent_id, mix_id)
        origin: OriginFetch | None = None
        if preferred is self or preferred is None:
            if self._origin_fetch_allowed(intent_id, mix_id, override_intent_id):
                origin = _SourceOriginFetch(
                    self.source,
                    lambda downloaded, total, mid=mix_id: self._on_download_progress(
                        mid, downloaded, total
                    ),
                )
        # Else preferred peer is reachable but lacks bytes — wait (origin stays None).
        self._cache.ensure_complete(
            mix,
            peers=peers,
            origin=origin,
            still_assigned=lambda: self._assignment_includes(self, intent_id, mix_id),
            note=self.note,
            wrap_download=self._with_download,
        )

    def _on_download_progress(
        self, mix_id: UUID, downloaded: int, total: int | None
    ) -> None:
        with self._download_lock:
            progress = self._downloads.get(mix_id)
            if progress is None:
                return
            progress["downloaded_bytes"] = max(0, int(downloaded))
            progress["total_bytes"] = None if total is None else max(0, int(total))
        now = time.monotonic()
        if now - self._download_cache_notice_at >= _DOWNLOAD_CACHE_NOTICE_SECONDS:
            self._download_cache_notice_at = now
            self._mark_view_sections(UIViewSection.CACHE)

    def _with_download(self, mix_id: UUID, action: Callable[[], None]) -> None:
        with self._download_lock:
            self._downloads[mix_id] = {
                "downloaded_bytes": 0,
                "total_bytes": None,
            }
        # Start/end remount Playlog status/playable; progress ticks stay CACHE-only.
        self._mark_view_sections(UIViewSection.CACHE, UIViewSection.PLAYLOG)
        try:
            action()
        finally:
            with self._download_lock:
                self._downloads.pop(mix_id, None)
            self._mark_view_sections(UIViewSection.CACHE, UIViewSection.PLAYLOG)

    def _origin_fetch_allowed(
        self,
        intent_id: UUID,
        mix_id: UUID,
        override_intent_id: UUID | None,
    ) -> bool:
        if not self._metered:
            return True
        if override_intent_id is not None and intent_id == override_intent_id:
            return True
        return mix_id in self._metered_origin_allowlist(intent_id)

    def _metered_origin_allowlist(self, intent_id: UUID) -> set[UUID]:
        """Current mix (or assignment head) plus one mix ahead for this intent."""
        assignment = self.assignment(intent_id)
        if assignment is None or not assignment.mix_ids:
            return set()
        mix_ids = assignment.mix_ids
        current = self._current_mix_id
        if current is not None and current in mix_ids:
            index = mix_ids.index(current)
        else:
            index = 0
        allowed = {mix_ids[index]}
        if index + 1 < len(mix_ids):
            allowed.add(mix_ids[index + 1])
        return allowed

    def _preferred_origin_agent(
        self, intent_id: UUID, mix_id: UUID
    ) -> DeviceAgent | None:
        """Highest-priority (lowest number) reachable agent whose assignment includes mix_id."""
        candidates: list[DeviceAgent] = []
        if self._assignment_includes(self, intent_id, mix_id):
            candidates.append(self)
        for peer in self._reachable:
            if not self._trusts_public_key(peer.public_key_pem):
                continue
            if self._assignment_includes(peer, intent_id, mix_id):
                candidates.append(peer)
        if not candidates:
            return None
        return min(candidates, key=lambda a: (a.device.priority, str(a.device_id)))

    @staticmethod
    def _assignment_includes(
        agent: DeviceAgent, intent_id: UUID, mix_id: UUID
    ) -> bool:
        assignment = agent.assignment(intent_id, agent.device_id)
        return assignment is not None and mix_id in assignment.mix_ids

    def _store_local_file(self, mix_id: UUID, data: bytes) -> None:
        self._cache.store_mix(mix_id, data)

    def _local_file_size(self, mix_id: UUID) -> int | None:
        return self._cache.size(mix_id)

    def _has_local_file(self, mix_id: UUID) -> bool:
        return self._cache.has(mix_id)

    def _local_file_ids(self) -> set[UUID]:
        return self._cache.local_ids()

    def _ensure_blob_on_disk(self, mix_id: UUID) -> Path:
        return self._cache.ensure_on_disk(mix_id)

    def _blob_path(self, mix_id: UUID) -> Path:
        return self._cache.blob_path(mix_id)

    def _refresh_intent_folders(self) -> None:
        intent_ids = [intent.id for intent in self.intents()]

        def _assigned(intent_id: UUID) -> Sequence[UUID]:
            assignment = self.assignment(intent_id)
            if assignment is None:
                return ()
            return assignment.mix_ids

        self._cache.refresh_intent_folders(intent_ids, _assigned)

    def _remove_intent_folder(self, intent_id: UUID) -> None:
        self._cache.remove_intent_folder(intent_id)

    def _cleanup_revoked_peer_session(self, device_id: UUID) -> None:
        """Drop Locator hints and in-process meet state after Catalog unpair."""
        if device_id in self._peer_urls:
            self._peer_urls.pop(device_id, None)
            self._persist_locator_hints()
        for agent in list(self._reachable):
            if agent.device_id == device_id:
                self._proved_agents.discard(id(agent))

    def _trust_payload(self, payload: dict[str, Any]) -> Device:
        if payload.get("v") != 1:
            raise ValueError("unsupported pairing payload version")
        name = payload["name"]
        public_key_pem = payload["public_key_pem"]
        if "device_id" not in payload:
            raise ValueError("pairing payload missing device_id")
        peer_id = UUID(payload["device_id"])
        priority = int(payload.get("priority", 100))
        expected = fingerprint_from_key(public_key_pem)
        claimed = payload.get("fingerprint") or payload.get("short_code")
        if claimed and str(claimed).upper() != expected:
            raise ValueError("fingerprint does not match public key")
        existing = self.catalog.devices.get(peer_id)
        if existing is None:
            existing = next(
                (d for d in self.catalog.devices.values() if d.public_key_pem == public_key_pem),
                None,
            )
        self.catalog.unpaired_device_ids.discard(peer_id)
        if existing is not None:
            peer = existing
        else:
            peer = Device(
                id=peer_id,
                name=name,
                public_key_pem=public_key_pem,
                priority=priority,
            )
            self._append_and_apply(
                EventType.DEVICE_PAIRED,
                {
                    "id": str(peer.id),
                    "name": peer.name,
                    "public_key_pem": peer.public_key_pem,
                    "priority": peer.priority,
                },
            )
            peer = self.catalog.devices[peer.id]
        if url := payload.get("url"):
            self.remember_peer_url(peer.id, url)
        return peer

    def _trusts_public_key(self, public_key_pem: str) -> bool:
        return any(d.public_key_pem == public_key_pem for d in self.peers())

    def _verify_possession(self, nonce: str, signature: str, public_key_pem: str) -> bool:
        try:
            _load_public_key(public_key_pem).verify(
                base64.b64decode(signature),
                nonce.encode("utf-8"),
            )
        except (InvalidSignature, ValueError, TypeError):
            return False
        return True

    def _ensure_agent_proved(self, peer: DeviceAgent) -> bool:
        """Challenge an in-process Peer; proof lasts until disconnect."""
        key = id(peer)
        if key in self._proved_agents:
            return True
        if not self._trusts_public_key(peer.public_key_pem):
            return False
        nonce = secrets.token_urlsafe(32)
        try:
            signature = peer.prove_possession(nonce)
        except Exception as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            self.note(f"meet proof failed for {peer.name}: {exc}", level=logging.WARNING)
            return False
        if not self._verify_possession(nonce, signature, peer.public_key_pem):
            self.note(f"meet proof failed for {peer.name}", level=logging.WARNING)
            return False
        self._proved_agents.add(key)
        return True

    def _ensure_http_peer_proved(self, url: str, public_key_pem: str) -> bool:
        """Challenge an HTTP Locator before Event log sync (every pull)."""
        nonce = secrets.token_urlsafe(32)
        try:
            signature = self._http_prove(url, nonce)
        except Exception as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            self.note(f"meet proof failed ({url}): {exc}", level=logging.WARNING)
            return False
        if not self._verify_possession(nonce, signature, public_key_pem):
            self.note(f"meet proof failed ({url})", level=logging.WARNING)
            return False
        return True

    def _append_and_apply(self, event_type: EventType, payload: dict[str, Any]) -> Event:
        event = self._journal.append_local(event_type, payload)
        self._mark_view_sections_for_event(event_type)
        # Mid-play PLAYHEAD ticks stay local for crash/resume; peers get them on
        # pause/stop/seek/skip/supervise boundaries (and other Event types).
        if event_type is not EventType.PLAYHEAD:
            self._schedule_auto_sync()
        return event

    def _schedule_auto_sync(self) -> None:
        """Pull on this device and nudge trusted reachable peers to pull too.

        Each side's ``sync`` still runs the key-proof meet gate before ingest.
        Nested under ``_defer_auto_sync``, only the outermost exit schedules once.
        """
        if self._auto_sync_defer_depth > 0:
            self._auto_sync_deferred = True
            return
        self.request_sync()
        for peer in list(self._reachable):
            if not self._trusts_public_key(peer.public_key_pem):
                continue
            if not peer._trusts_public_key(self.public_key_pem):
                continue
            peer.request_sync()
        trusted_ids = {p.id for p in self.peers()}
        for peer_id, url in list(self._peer_urls.items()):
            if peer_id not in trusted_ids:
                continue
            if str(url).startswith("inproc://"):
                continue
            self._http_nudge_sync(url)

    def _http_nudge_sync(self, peer_url: str) -> None:
        """Best-effort: ask the HTTP peer to run its own pull sync."""
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
                response = client.post(f"{peer_url.rstrip('/')}/api/sync")
                response.raise_for_status()
        except Exception as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            self.note(f"auto-sync nudge failed ({peer_url}): {exc}", level=logging.WARNING)

    def _request_peers_yield(self) -> None:
        """Best-effort: ask reachable trusted Peers to pause local playback.

        Playing stays local (not Event log). Unreachable Peers are left alone.
        Failures never fail local play.
        """
        for peer in list(self._reachable):
            if not self._trusts_public_key(peer.public_key_pem):
                continue
            if not self._ensure_agent_proved(peer):
                continue
            try:
                if peer.yield_playback():
                    self.note(f"peer {peer.name} yielded playback")
            except Exception as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                self.note(
                    f"peer yield failed for {peer.name}: {exc}",
                    level=logging.WARNING,
                )
        trusted_ids = {p.id for p in self.peers()}
        for peer_id, url in list(self._peer_urls.items()):
            if peer_id not in trusted_ids:
                continue
            if str(url).startswith("inproc://"):
                continue
            peer = self.catalog.devices.get(peer_id)
            label = peer.name if peer is not None else str(peer_id)
            self._http_request_yield(url, label=label)

    def _http_request_yield(self, peer_url: str, *, label: str) -> None:
        """Best-effort: POST /api/player/yield on an HTTP Peer Locator."""
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
                response = client.post(f"{peer_url.rstrip('/')}/api/player/yield")
                response.raise_for_status()
                yielded = bool(response.json().get("yielded"))
            if yielded:
                self.note(f"peer {label} yielded playback")
        except Exception as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            self.note(
                f"peer yield failed ({peer_url}): {exc}",
                level=logging.WARNING,
            )

    def _ingest(self, event: Event) -> None:
        """Peer Event ingest via CatalogJournal (dedupe / buffer / verify / apply)."""
        self._journal.ingest_foreign(event)

    def _upsert_intent_and_rebuild(
        self,
        intent: Intent,
        *,
        cleared_device_ids: list[UUID] | None = None,
        fill: bool = False,
    ) -> None:
        with self._defer_auto_sync():
            with self._view_notice_batch():
                with self._journal.hold():
                    self._append_and_apply(
                        EventType.INTENT_UPSERTED,
                        encode_intent(intent, cleared_device_ids=cleared_device_ids),
                    )
                    # Catalog may have merged peer device_hours; rebuild from that.
                    # INTENT_UPSERT rebuild+prune must stay under journal.hold() so
                    # export never sees a half-written intent; request_fill
                    # only starts a thread (safe under the lock).
                    merged = self.catalog.intents[intent.id]
                    self._maintenance.after_catalog_change(
                        CatalogChange(
                            CatalogChangeReason.INTENT_UPSERT,
                            intent=merged,
                            fill_async=fill,
                        )
                    )

    def _rebuild_all_sequences(self) -> None:
        with self._defer_auto_sync():
            with self._view_notice_batch():
                with self._journal.hold():
                    for intent in self.intents():
                        self._rebuild_sequence_for_intent(intent)
                    self._prune_unassigned_files()

    def _fillup_all_sequences(self) -> None:
        """Drop retired Releases; keep queued order; append only if under budget."""
        with self._defer_auto_sync():
            with self._view_notice_batch():
                with self._journal.hold():
                    for intent in self.intents():
                        self._fillup_sequence_for_intent(intent)
                    self._prune_unassigned_files()

    def _rebuild_unfilled_sequences(self, *, include_underfilled: bool = True) -> bool:
        """Rebuild intents missing a device assignment and/or still under budget.

        ``include_underfilled`` should be True after local mix adds/refreshes (and
        after peer ingest that added mixes). On a routine sync with no new mixes,
        only missing assignments are rebuilt — otherwise an under-budget Explore
        with too few Catalog mixes would rebuild forever.

        Skip the view-notice batch when nothing needs rebuild so a concurrent
        auto-sync cannot nest an empty batch under a local write and delay its
        flush (notices would stay pending until sync ended).
        """
        to_rebuild = [
            intent
            for intent in self.intents()
            if self._sequence_provisioner.needs_rebuild(
                intent, self.catalog, include_underfilled=include_underfilled
            )
        ]
        if not to_rebuild:
            return False
        with self._defer_auto_sync():
            with self._view_notice_batch():
                with self._journal.hold():
                    rebuilt = False
                    for intent in to_rebuild:
                        # Re-check under the lock; a peer may have filled gaps.
                        if not self._sequence_provisioner.needs_rebuild(
                            intent,
                            self.catalog,
                            include_underfilled=include_underfilled,
                        ):
                            continue
                        self._rebuild_sequence_for_intent(intent)
                        rebuilt = True
                    if rebuilt:
                        self._prune_unassigned_files()
                    return rebuilt

    def _rebuild_sequence_for_intent(self, intent: Intent) -> None:
        """Append SequenceProvisioner full-rebuild drafts (caller holds journal)."""
        for draft in self._sequence_provisioner.provision(intent, self.catalog):
            self._append_and_apply(draft.type, draft.payload)

    def _fillup_sequence_for_intent(self, intent: Intent) -> None:
        """Append SequenceProvisioner fillup drafts (caller holds journal)."""
        for draft in self._sequence_provisioner.provision_fillup(
            intent, self.catalog
        ):
            self._append_and_apply(draft.type, draft.payload)

    def _delete_retired_file_if_replaced(self, retired_mix_id: UUID) -> None:
        """Drop a played/skipped mix's bytes once another assigned mix is local.

        Keeps the blob while it is still the current mix so playback can continue,
        and while the Playlog previous-File cushion still holds.
        """
        if not self._has_local_file(retired_mix_id):
            return
        if retired_mix_id == self._current_mix_id:
            return
        if self._is_playlog_previous_retained(retired_mix_id):
            return
        replacement_local = False
        for intent in self.intents():
            assignment = self.assignment(intent.id)
            if assignment is None:
                continue
            for mix_id in assignment.mix_ids:
                if mix_id != retired_mix_id and self._has_local_file(mix_id):
                    replacement_local = True
                    break
            if replacement_local:
                break
        if replacement_local:
            self.remove_local_file(retired_mix_id)

    def _on_journal_applied(self, event: Event, effects: LocalEffects) -> None:
        """Live apply side effects: LocalEffects, UI notices, and unpair cleanup.

        Unknown-author buffer flush is CatalogJournal policy (before this callback).
        """
        self._run_local_effects(effects)
        if event.type in (EventType.MIX_REJECTED, EventType.MIX_UNREJECTED):
            self._sync_reject_file_delete_schedule(UUID(event.payload["mix_id"]))
        if event.device_id != self.device.id:
            self._record_view_sections_for_event(event.type)
        if event.type is EventType.DEVICE_UNPAIRED:
            device_id = UUID(event.payload["id"])
            if device_id != self.device.id:
                self._cleanup_revoked_peer_session(device_id)

    def _run_local_effects(self, effects: LocalEffects) -> None:
        for mix_id in effects.delete_files:
            self.remove_local_file(mix_id)
        for intent_id in effects.remove_intent_folders:
            self._remove_intent_folder(intent_id)

    def _sign(self, event: Event) -> str:
        signature = self._private_key.sign(_event_bytes(event))
        return base64.b64encode(signature).decode("ascii")

    def _verify(self, event: Event, public_key_pem: str) -> bool:
        if not event.signature:
            return False
        public_key = _load_public_key(public_key_pem)
        try:
            public_key.verify(base64.b64decode(event.signature), _event_bytes(event))
        except InvalidSignature:
            return False
        return True

    def _http_fetch_pairing(self, peer_url: str) -> dict[str, Any]:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.get(f"{peer_url.rstrip('/')}/api/pairing")
            response.raise_for_status()
            return response.json()

    def _http_pair_status(self, peer_url: str) -> dict[str, Any]:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.get(f"{peer_url.rstrip('/')}/api/pair/session")
            response.raise_for_status()
            return response.json()

    def _http_pair_join(self, peer_url: str, body: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.post(
                f"{peer_url.rstrip('/')}/api/pair/session/join",
                json=body,
            )
            if response.status_code >= 400:
                detail = _http_error_detail(response)
                raise ValueError(detail)
            return response.json()

    def _http_pair_confirm(self, peer_url: str, body: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.post(
                f"{peer_url.rstrip('/')}/api/pair/session/confirm",
                json=body,
            )
            if response.status_code >= 400:
                detail = _http_error_detail(response)
                raise ValueError(detail)
            return response.json()

    def _http_pair_cancel(self, peer_url: str, session_id: str) -> None:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.post(
                f"{peer_url.rstrip('/')}/api/pair/session/cancel",
                json={"session_id": session_id},
            )
            response.raise_for_status()

    def _http_prove(self, peer_url: str, nonce: str) -> str:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.post(
                f"{peer_url.rstrip('/')}/api/prove",
                json={"nonce": nonce},
            )
            response.raise_for_status()
            signature = response.json().get("signature")
        if not isinstance(signature, str) or not signature:
            raise ValueError("peer prove response missing signature")
        return signature

    def _http_fetch_events(self, peer_url: str) -> list[Event]:
        """Pull peer events via POST cursors + NDJSON (falls back to GET NDJSON)."""
        cursors = self.event_cursors()
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.post(
                f"{peer_url.rstrip('/')}/api/events/pull",
                json={"cursors": cursors},
            )
            if response.status_code == 404:
                response = client.get(f"{peer_url.rstrip('/')}/api/events")
            response.raise_for_status()
        return _parse_events_ndjson(response.text)


def _parse_events_ndjson(body: str) -> list[Event]:
    """Parse NDJSON Event lines; also accept legacy ``{\"events\": [...]}`` JSON."""
    text = body.strip()
    if not text:
        return []
    if text.startswith("{"):
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            raw = None
        if isinstance(raw, dict) and "events" in raw:
            return [Event.model_validate(item) for item in raw["events"]]
    events: list[Event] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        events.append(Event.model_validate_json(line))
    return events


def _normalize_artist_url(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    return (
        bandcamp_normalize_artist_url(cleaned)
        or youtube_normalize_artist_url(cleaned)
        or cleaned
    )


def _as_naive_utc(dt: datetime | None) -> datetime | None:
    """Normalize to naive UTC so compares match ``datetime.utcnow`` clocks."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def _device_hours_from_spec(entries: list[DeviceHoursSpec]) -> list[DeviceHours]:
    hours: list[DeviceHours] = []
    for entry in entries:
        if len(entry) == 2:
            device_id, budget = entry
            hours.append(DeviceHours(device_id=device_id, budget_seconds=budget))
        elif len(entry) == 3:
            device_id, budget, expires_at = entry
            hours.append(
                DeviceHours(
                    device_id=device_id,
                    budget_seconds=budget,
                    expires_at=_as_naive_utc(expires_at),
                )
            )
        else:
            raise ValueError(
                "device_hours entries must be (device_id, budget) "
                "or (device_id, budget, expires_at)"
            )
    return hours


def _event_bytes(event: Event) -> bytes:
    body = {
        "id": str(event.id),
        "type": event.type.value,
        "device_id": str(event.device_id),
        "created_at": event.created_at.isoformat(),
        "seq": int(event.seq),
        "payload": event.payload,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def _http_error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except Exception:
        return response.text or f"HTTP {response.status_code}"
    detail = data.get("detail") if isinstance(data, dict) else None
    if isinstance(detail, str):
        return detail
    return response.text or f"HTTP {response.status_code}"


def _load_private_key(pem: str) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("expected Ed25519 private key")
    return key


def _load_public_key(pem: str) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(pem.encode())
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("expected Ed25519 public key")
    return key


def _load_later_features() -> list[str]:
    path = Path(__file__).resolve().parents[2] / "docs" / "LATER.md"
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    features: list[str] = []
    in_planned = False
    for line in lines:
        if line.startswith("## Planned features"):
            in_planned = True
            continue
        if in_planned and line.startswith("## "):
            break
        if in_planned and line.startswith("- "):
            features.append(line[2:].strip())
    return features


class _SourceOriginFetch:
    """OriginFetch adapter over the agent's Source + download progress hook."""

    def __init__(
        self,
        source: Source,
        on_progress: Callable[[int, int | None], None],
    ) -> None:
        self._source = source
        self._on_progress = on_progress

    def fetch_mix(self, mix: Mix) -> bytes:
        return self._source.fetch_bytes(mix.url, on_progress=self._on_progress)

    def fetch_album(self, mix: Mix) -> list[bytes]:
        return [
            self._source.fetch_bytes(track.url, on_progress=self._on_progress)
            for track in mix.tracks
        ]
