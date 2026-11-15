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
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
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
from tunebag.catalog import Catalog
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
    RejectPending,
    Sequence,
    SequenceEntry,
    StarBucket,
    StarDistribution,
    Stars,
    new_id,
)
from tunebag.events import Event, EventLog, EventType
from tunebag.pairing import (
    DeviceIdentity,
    generate_identity,
    load_locator_hints,
    resolve_persisted_identity,
    save_locator_hints,
    short_code_from_key,
)
from tunebag.pairing import (
    pairing_payload as build_pairing_payload,
)
from tunebag.player import AudioPlayer, default_player
from tunebag.reject import RejectBuffer
from tunebag.sequence import assign_by_budget, build_sequence
from tunebag.source import (
    DEFAULT_MIN_DURATION_SECONDS,
    Source,
    default_source,
)
from tunebag.ui_notices import UIViewNotice, UIViewSection, ViewNoticeBus

_HTTP_TIMEOUT = 5.0
PLAYED_THRESHOLD = 0.75
PLAYHEAD_NEAR_SECONDS = 120.0
# Meaningful listen: position reaches max(120s, 5% of duration); rising edge only.
LAST_HEARD_FLOOR_SECONDS = 120.0
LAST_HEARD_DURATION_FRACTION = 0.05
_UNSET = object()
# Default first-boot Explore intent: even 1★–5★ shares, half unrated (10|10|10|10|10|50).
# Well-known id + seed so independently seeded devices merge to one Explore on pair.
EXPLORE_INTENT_ID = UUID("00000000-0000-4000-8000-000000000001")
EXPLORE_SEED = 1
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
MergeKey = tuple[str, ...]
# Author time first (causal on one Device); (device_id, seq, id) breaks ties.
MergeWin = tuple[datetime, UUID, int, UUID]

# Catalog Event → UI section notices (Device-local; see ui-view-notices spec).
_MIXES = (UIViewSection.MIXES,)
_MIXES_AND_HISTORY = (UIViewSection.MIXES, UIViewSection.PLAY_HISTORY)
_INTENTS = (UIViewSection.INTENTS,)
_PEERS = (UIViewSection.PEERS,)
_VIEW_SECTIONS_FOR_EVENT: dict[EventType, tuple[UIViewSection, ...]] = {
    EventType.ARTIST_ADDED: _MIXES,
    EventType.ARTIST_DELETED: _MIXES,
    EventType.MIX_ADDED: _MIXES,
    EventType.MIX_TAGGED: _MIXES_AND_HISTORY,
    EventType.MIX_RATED: _MIXES_AND_HISTORY,
    EventType.MIX_REJECTED: _MIXES_AND_HISTORY,
    EventType.MIX_UNREJECTED: _MIXES_AND_HISTORY,
    EventType.PLAYHEAD: _MIXES_AND_HISTORY,
    EventType.PLAYED: _MIXES_AND_HISTORY,
    EventType.LAST_HEARD: _MIXES_AND_HISTORY,
    EventType.INTENT_UPSERTED: _INTENTS,
    EventType.INTENT_DELETED: _INTENTS,
    EventType.SEQUENCE_BUILT: _INTENTS,
    EventType.ASSIGNMENT_SET: _INTENTS,
    EventType.ASSIGNMENT_CLEARED: _INTENTS,
    EventType.DEVICE_PAIRED: _PEERS,
    EventType.DEVICE_UNPAIRED: _PEERS,
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
        data_dir: Path | None = None,
        player: AudioPlayer | None = None,
        clock: Callable[[], datetime] | None = None,
        discovery: LanDiscovery | None = None,
    ) -> None:
        # Persist identity/log/hints only for an explicit data_dir so in-process
        # multi-agent tests (default ~/.tunebag) do not collide on one identity.json.
        persist = data_dir is not None
        self._persist = persist
        self.catalog = Catalog(data_dir=data_dir)
        self.data_dir = self.catalog.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._locator_hints_path = self.data_dir / "locator_hints.json"
        if persist:
            self._identity, device_id = resolve_persisted_identity(
                self.data_dir / "identity.json",
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
        self.source = source if source is not None else default_source()
        self._discovery: LanDiscovery = (
            discovery if discovery is not None else NullLanDiscovery()
        )
        self.catalog.local_device_id = self.device.id
        self.catalog.add_device(self.device)
        self._log = EventLog(
            path=(self.data_dir / "events.jsonl") if persist else None
        )
        self._activity = ActivityLog()
        self._view_notices = ViewNoticeBus()
        self._reachable: list[DeviceAgent] = []
        # In-process meet sessions: proved until disconnect.
        self._proved_agents: set[int] = set()
        self._peer_urls: dict[UUID, str] = (
            load_locator_hints(self._locator_hints_path) if persist else {}
        )
        self._pair_candidates: dict[str, dict[str, Any]] = {}
        self._seen_event_ids: set[UUID] = set()
        # Events whose author is not yet in Catalog; flushed on DEVICE_PAIRED / pair.
        self._unknown_author_buffer: dict[UUID, Event] = {}
        # Sticky until local re-pair (QR / short code); remote DEVICE_PAIRED cannot undo.
        self._unpaired_device_ids: set[UUID] = set()
        self._local_files: dict[UUID, bytes] = {}
        # Deterministic merge bookkeeping (same events ⇒ same Catalog).
        self._merge_wins: dict[MergeKey, MergeWin] = {}
        self._deleted_artists: set[UUID] = set()
        self._rejected_mix_ids: set[UUID] = set()
        self._played_mix_ids: set[UUID] = set()
        self._pending_tags: dict[UUID, list[str]] = {}
        self._pending_stars: dict[UUID, Stars] = {}
        self._pending_last_heard: dict[UUID, datetime] = {}
        self._pending_sequences: dict[UUID, Sequence] = {}
        self._pending_assignments: dict[tuple[UUID, UUID], Assignment | None] = {}
        self._event_seq = 0
        # Serialize append/ingest/apply against background sync threads.
        self._event_lock = threading.Lock()
        # Local-only (not events): simulated link mode, reject undo window, now-playing.
        self._metered = False
        self._current_mix_id: UUID | None = None
        self._clock: Callable[[], datetime] = clock or datetime.utcnow
        self._rejects = RejectBuffer()
        # Local player supervision (browser is remote control; closing it does not stop).
        self._player: AudioPlayer = player if player is not None else default_player()
        self._playing = False
        self._playing_intent_id: UUID | None = None
        self._playback_position: float = 0.0
        self._play_anchor_position: float = 0.0
        self._play_anchor_at: datetime | None = None
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
        self._downloading_mix_id: UUID | None = None
        self._download_bytes: int = 0
        self._download_total_bytes: int | None = None
        self._download_lock = threading.Lock()
        self._last_discovery_at: datetime | None = None
        if persist:
            self._replay_event_log()
            # Drop hints for Peers no longer trusted after replay (e.g. unpaired).
            self._prune_stale_locator_hints()
        self._start_discovery()

    def seed_default_intents_if_empty(self) -> bool:
        """On first durable boot (empty Event log), create the Explore intent.

        Returns True if Explore was created. Idempotent for non-empty logs.
        """
        if self._log.all():
            return False
        self.create_intent(
            "Explore",
            tags=[],
            distribution=EXPLORE_DISTRIBUTION,
            seed=EXPLORE_SEED,
            intent_id=EXPLORE_INTENT_ID,
        )
        return True

    def note(self, message: str, *, level: int = logging.INFO) -> None:
        """Record an operational progress line (terminal + UI activity feed)."""
        self._activity.note(message, level=level)

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

    def _mark_view_sections(self, *sections: UIViewSection) -> None:
        self._view_notices.mark(*sections)

    def _mark_view_sections_for_event(self, event_type: EventType) -> None:
        sections = _VIEW_SECTIONS_FOR_EVENT.get(event_type)
        if sections:
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

    def short_code(self) -> str:
        return short_code_from_key(self.public_key_pem)

    def pairing_payload(self) -> dict[str, Any]:
        return build_pairing_payload(
            self.name,
            self.public_key_pem,
            device_id=str(self.device.id),
            priority=self.device.priority,
            url=self.base_url,
        )

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
            for mix_id in self._local_file_ids()
            if mix_id in self.catalog.mixes
        ]

    @property
    def downloading_mix_id(self) -> UUID | None:
        with self._download_lock:
            return self._downloading_mix_id

    @property
    def download_progress(self) -> dict[str, Any] | None:
        with self._download_lock:
            if self._downloading_mix_id is None:
                return None
            return {
                "mix_id": self._downloading_mix_id,
                "downloaded_bytes": self._download_bytes,
                "total_bytes": self._download_total_bytes,
            }

    def cache_groups(self) -> list[dict[str, Any]]:
        """Assignments for this device, grouped for the Cache UI.

        Each group has mixes in assignment order with status cached / loading /
        pending, plus overview count, duration, and on-disk size totals. Local
        files with no remaining assignment appear under a synthetic Other group.
        """
        local_ids = self._local_file_ids()
        progress = self.download_progress
        downloading = None if progress is None else progress["mix_id"]
        assigned_ids: set[UUID] = set()
        groups: list[dict[str, Any]] = []

        for intent in self.intents():
            assignment = self.assignment(intent.id)
            if assignment is None:
                continue
            mixes: list[dict[str, Any]] = []
            overview = {
                "cached": {"count": 0, "duration_seconds": 0, "size_bytes": 0},
                "loading": {"count": 0, "duration_seconds": 0, "size_bytes": 0},
                "pending": {"count": 0, "duration_seconds": 0, "size_bytes": 0},
            }
            for mix_id in assignment.mix_ids:
                assigned_ids.add(mix_id)
                mix = self.catalog.mixes.get(mix_id)
                if mix is None:
                    continue
                if mix_id in local_ids:
                    status = "cached"
                elif downloading is not None and mix_id == downloading:
                    status = "loading"
                else:
                    status = "pending"
                duration = int(mix.duration_seconds)
                entry: dict[str, Any] = {
                    "id": mix_id,
                    "title": mix.title,
                    "duration_seconds": duration,
                    "status": status,
                }
                if status == "cached":
                    size = self._local_file_size(mix_id)
                    if size is not None:
                        entry["size_bytes"] = size
                        overview[status]["size_bytes"] += size
                if status == "loading" and progress is not None:
                    entry["downloaded_bytes"] = int(progress["downloaded_bytes"])
                    entry["total_bytes"] = progress["total_bytes"]
                mixes.append(entry)
                overview[status]["count"] += 1
                overview[status]["duration_seconds"] += duration
            groups.append(
                {
                    "id": intent.id,
                    "name": intent.name,
                    "mixes": mixes,
                    "overview": overview,
                }
            )

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
            entry: dict[str, Any] = {
                "id": mix_id,
                "title": mix.title,
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
        """Local audio bytes for a mix, if present (peer handoff)."""
        if mix_id in self._local_files:
            return self._local_files[mix_id]
        blob = self._blob_path(mix_id)
        if blob.is_file():
            data = blob.read_bytes()
            self._local_files[mix_id] = data
            return data
        return None

    def remove_local_file(self, mix_id: UUID) -> None:
        """Drop local audio for a mix so it can be fetched again."""
        had = mix_id in self._local_files or self._blob_path(mix_id).is_file()
        self._local_files.pop(mix_id, None)
        blob = self._blob_path(mix_id)
        if blob.exists():
            blob.unlink()
        self._refresh_intent_folders()
        if had:
            self._mark_view_sections(UIViewSection.CACHE)

    def intent_folder(self, intent_id: UUID) -> Path:
        """Directory of this device's assigned files for an intent."""
        path = self.data_dir / "intents" / str(intent_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def is_metered(self) -> bool:
        return self._metered

    def set_metered(self, metered: bool) -> None:
        """Simulate a metered link (demo switch; no SIM required)."""
        self._metered = bool(metered)

    def current_mix(self) -> UUID | None:
        return self._current_mix_id

    def set_current_mix(self, mix_id: UUID | None) -> None:
        """Mark the mix in progress (including a resumed one) for the metered cap."""
        if mix_id is not None and mix_id not in self.catalog.mixes:
            raise KeyError(f"unknown mix {mix_id}")
        self._current_mix_id = mix_id

    def is_playing(self) -> bool:
        if self._playing and not self._player.is_alive():
            # External player exited; keep catalog current_mix for metered/resume.
            self._freeze_playback_position()
            self._playing = False
        return self._playing

    def play(self, intent_id: UUID, mix_id: UUID | None = None) -> Mix:
        """Supervise local playback of an assigned mix that has a file on this device.

        Resumes from the latest synced playhead when one exists for the mix.
        Starts the local audio player against the cached blob (browser is remote only).
        """
        if intent_id not in self.catalog.intents:
            raise KeyError(f"unknown intent {intent_id}")
        assignment = self.assignment(intent_id)
        if assignment is None or not assignment.mix_ids:
            raise ValueError("intent has no assignment on this device")
        if mix_id is not None:
            target = mix_id
        elif (
            self._current_mix_id is not None
            and self._current_mix_id in assignment.mix_ids
            and self._has_local_file(self._current_mix_id)
        ):
            target = self._current_mix_id
        else:
            target = assignment.mix_ids[0]
        if target not in assignment.mix_ids:
            raise ValueError("mix is not in this device's assignment")
        if not self._has_local_file(target):
            raise ValueError("mix has no local file")
        mix = self.catalog.mixes[target]
        existing = self.catalog.playheads.get(target)
        start = float(existing.position_seconds) if existing is not None else 0.0
        blob = self._ensure_blob_on_disk(target)
        self._player.play(blob, start_seconds=start)
        self._playing = True
        self._playing_intent_id = intent_id
        self.set_current_mix(target)
        self._set_play_anchor(start)
        return mix

    def stop(self) -> None:
        """Stop local playback without marking the mix played."""
        self._freeze_playback_position()
        self._player.stop()
        self._playing = False
        self._playing_intent_id = None
        # Expiry may have deferred deletion of the mix that was playing.
        self._prune_unassigned_files()

    def pause(self, position_seconds: float | None = None) -> None:
        """Pause local playback; keep current mix and intent for resume.

        Always commits the playhead (optional explicit position, else frozen clock).
        """
        if self.is_playing():
            self._freeze_playback_position()
        pos = (
            float(position_seconds)
            if position_seconds is not None
            else self._playback_position
        )
        if self._current_mix_id is not None:
            self.report_playhead(pos)
        if self.is_playing():
            self._player.stop()
            self._playing = False
            self._clear_play_anchor()

    def skip(self, intent_id: UUID | None = None) -> Mix:
        """Advance to the next local assigned mix without marking the current played."""
        resolved = intent_id if intent_id is not None else self._playing_intent_id
        if resolved is None:
            raise ValueError("no intent to skip within")
        if resolved not in self.catalog.intents:
            raise KeyError(f"unknown intent {resolved}")
        assignment = self.assignment(resolved)
        if assignment is None or not assignment.mix_ids:
            raise ValueError("intent has no assignment on this device")
        local_ids = [mid for mid in assignment.mix_ids if self._has_local_file(mid)]
        if not local_ids:
            raise ValueError("no local mixes to skip to")
        current = self._current_mix_id
        if current in local_ids:
            idx = local_ids.index(current)
            next_id = local_ids[(idx + 1) % len(local_ids)]
        else:
            next_id = local_ids[0]
        if next_id == current:
            raise ValueError("no other local mix to skip to")
        self._freeze_playback_position()
        return self.play(resolved, next_id)

    def playback_position(self) -> float:
        """Current local playback position (including a mid-mix resume point)."""
        if self._playing and self._play_anchor_at is not None:
            return self._computed_playback_position()
        return self._playback_position

    def playing_intent_id(self) -> UUID | None:
        return self._playing_intent_id

    def report_playhead(self, position_seconds: float) -> Playhead:
        """Update the playhead for the current mix; mark played at or past 75%.

        Emits Last heard on the rising edge when position crosses
        max(120s, 5% of duration) from below.
        """
        mix_id = self._current_mix_id
        if mix_id is None:
            raise ValueError("no current mix")
        mix = self.catalog.mixes.get(mix_id)
        if mix is None:
            raise KeyError(f"unknown mix {mix_id}")
        pos = float(position_seconds)
        previous = 0.0
        existing_head = self.catalog.playheads.get(mix_id)
        if existing_head is not None:
            previous = float(existing_head.position_seconds)
        self._playback_position = pos
        if self._playing and self._play_anchor_at is not None:
            self._play_anchor_position = pos
            self._play_anchor_at = self._clock()
        with self._view_notice_batch():
            self._append_and_apply(
                EventType.PLAYHEAD,
                {
                    "mix_id": str(mix_id),
                    "position_seconds": pos,
                },
            )
            threshold = _last_heard_threshold(mix.duration_seconds)
            if previous < threshold <= pos:
                self._append_and_apply(
                    EventType.LAST_HEARD,
                    {"mix_id": str(mix_id)},
                )
            mix = self.catalog.mixes[mix_id]
            if (
                not mix.played
                and mix.duration_seconds > 0
                and pos >= PLAYED_THRESHOLD * mix.duration_seconds
            ):
                self.mark_played(mix_id)
        return self.catalog.playheads[mix_id]

    def seek(self, position_seconds: float) -> Playhead:
        """Seek the current mix: sync playhead and restart local audio if playing."""
        mix_id = self._current_mix_id
        if mix_id is None:
            raise ValueError("no current mix")
        mix = self.catalog.mixes.get(mix_id)
        if mix is None:
            raise KeyError(f"unknown mix {mix_id}")
        duration = float(mix.duration_seconds)
        pos = max(0.0, float(position_seconds))
        if duration > 0:
            pos = min(duration, pos)
        was_playing = self.is_playing()
        intent_id = self._playing_intent_id
        head = self.report_playhead(pos)
        if was_playing and self.is_playing() and intent_id is not None:
            blob = self._ensure_blob_on_disk(mix_id)
            self._player.play(blob, start_seconds=pos)
            self._playing = True
            self._playing_intent_id = intent_id
            self._set_play_anchor(pos)
        else:
            self._playback_position = pos
            self._clear_play_anchor()
        return head

    def _set_play_anchor(self, position: float) -> None:
        self._playback_position = float(position)
        self._play_anchor_position = float(position)
        self._play_anchor_at = self._clock()

    def _clear_play_anchor(self) -> None:
        self._play_anchor_at = None

    def _computed_playback_position(self) -> float:
        if self._play_anchor_at is None:
            return self._playback_position
        elapsed = (self._clock() - self._play_anchor_at).total_seconds()
        pos = self._play_anchor_position + max(0.0, elapsed)
        mix_id = self._current_mix_id
        if mix_id is not None:
            mix = self.catalog.mixes.get(mix_id)
            if mix is not None and mix.duration_seconds > 0:
                pos = min(float(mix.duration_seconds), pos)
        return round(pos, 3)

    def _freeze_playback_position(self) -> None:
        if self._play_anchor_at is not None:
            self._playback_position = self._computed_playback_position()
            self._clear_play_anchor()

    def mark_played(self, mix_id: UUID | None = None) -> Mix:
        """Mark a mix played (explicit control or auto at 75%).

        Rebuilds sequences so the mix goes to the back of the pool, fills the
        next assignment, then deletes the played file once a replacement is local.
        """
        target = mix_id if mix_id is not None else self._current_mix_id
        if target is None:
            raise ValueError("no mix to mark played")
        if target not in self.catalog.mixes:
            raise KeyError(f"unknown mix {target}")
        if not self.catalog.mixes[target].played:
            with self._view_notice_batch():
                self._append_and_apply(EventType.PLAYED, {"mix_id": str(target)})
                self._rebuild_all_sequences()
                self.fill_caches()
                self._delete_played_file_if_replaced(target)
        if self._current_mix_id == target:
            self._player.stop()
            self._playing = False
            self._playing_intent_id = None
            self._playback_position = 0.0
            self._clear_play_anchor()
        return self.catalog.mixes[target]

    def mix(self, mix_id: UUID) -> Mix | None:
        return self.catalog.mixes.get(mix_id)

    def playhead(self, mix_id: UUID) -> Playhead | None:
        return self.catalog.playheads.get(mix_id)

    def suggest_tags(self, prefix: str = "", limit: int = 10) -> list[str]:
        """Tags already in the catalog that match the prefix."""
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

        When metered, origin fetches are limited to the current mix plus one
        ahead per intent, unless ``override_intent_id`` is that intent (Fill now).
        Peer copies always ignore the metered cap. Files already local stay.

        Returns the number of mixes with local audio after the pass. Per-mix
        fetch failures are skipped so one bad URL does not abort the fill.
        """
        if override_intent_id is not None:
            self.note(f"fill caches start (fill-now intent={override_intent_id})")
        else:
            self.note("fill caches start")
        with self._view_notice_batch():
            for intent in self.intents():
                assignment = self.assignment(intent.id)
                if assignment is None:
                    if intent.device_hours:
                        other = ", ".join(
                            str(dh.device_id) for dh in intent.device_hours
                        )
                        self.note(
                            f"fill skip: {intent.name} has hours for {other} "
                            f"(not this device {self.device.id})",
                            level=logging.WARNING,
                        )
                    continue
                for mix_id in assignment.mix_ids:
                    try:
                        self._ensure_local_file(
                            intent.id,
                            mix_id,
                            override_intent_id=override_intent_id,
                        )
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
            # Drop leftovers from prior assignments / deleted intents before
            # rewriting intent folders.
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
        """List own uploads for each artist URL and write catalog rows only."""
        self.note(f"add artists start · {len(urls)} URL(s)")
        added: list[Mix] = []
        with self._view_notice_batch():
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
                for upload in listing.uploads:
                    if upload.duration_seconds < min_duration_seconds:
                        continue
                    mix = Mix(
                        artist_id=artist.id,
                        platform=upload.platform,
                        platform_id=upload.platform_id,
                        title=upload.title,
                        url=upload.url,
                        duration_seconds=upload.duration_seconds,
                        size_bytes=upload.size_bytes,
                    )
                    self._append_and_apply(EventType.MIX_ADDED, _mix_added_payload(mix))
                    added.append(self.catalog.mixes[mix.id])
                    kept += 1
                self.note(
                    f"fetch artist list end: {listing.name} · "
                    f"{len(listing.uploads)} upload(s), {kept} mix(es) added"
                )
        self.note(f"add artists end · {len(added)} mix(es)")
        return added

    def refresh_artists(
        self,
        artist_ids: list[UUID] | None = None,
        *,
        min_duration_seconds: int = DEFAULT_MIN_DURATION_SECONDS,
    ) -> list[Mix]:
        """Re-list known artists' own uploads; add new catalog rows only."""
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
        added: list[Mix] = []
        with self._view_notice_batch():
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
                kept = 0
                for upload in listing.uploads:
                    if upload.duration_seconds < min_duration_seconds:
                        continue
                    key = (upload.platform, upload.platform_id)
                    if key in known:
                        continue
                    mix = Mix(
                        artist_id=artist.id,
                        platform=upload.platform,
                        platform_id=upload.platform_id,
                        title=upload.title,
                        url=upload.url,
                        duration_seconds=upload.duration_seconds,
                        size_bytes=upload.size_bytes,
                    )
                    self._append_and_apply(EventType.MIX_ADDED, _mix_added_payload(mix))
                    known.add(key)
                    added.append(self.catalog.mixes[mix.id])
                    kept += 1
                self.note(
                    f"fetch artist list end: {artist.name} · "
                    f"{len(listing.uploads)} upload(s), {kept} mix(es) added"
                )
        self.note(f"refresh artists end · {len(added)} mix(es)")
        return added

    def _known_platform_keys(self) -> set[tuple[Platform, str]]:
        return {(m.platform, m.platform_id) for m in self.catalog.mixes.values()}

    def pair(self, payload: dict[str, Any]) -> Device:
        peer = self._trust_payload(payload)
        for agent in self._reachable:
            if agent.public_key_pem == payload["public_key_pem"]:
                agent.accept_pair_offer(self.pairing_payload())
                return peer
        if url := payload.get("url"):
            peer_agent = self._discovery_agent_at(url)
            if peer_agent is not None and peer_agent is not self:
                peer_agent.accept_pair_offer(self.pairing_payload())
                self.connect(peer_agent)
                return peer
            if not str(url).startswith("inproc://"):
                self._http_offer_pair(url)
        return peer

    def unpair(self, device_id: UUID) -> None:
        """Revoke trust in a Peer via a replicated DEVICE_UNPAIRED event."""
        if device_id == self.device.id:
            raise ValueError("cannot unpair this Device")
        self._append_and_apply(EventType.DEVICE_UNPAIRED, {"id": str(device_id)})

    def pair_by_short_code(self, code: str, *, peer_url: str | None = None) -> Device:
        needle = code.strip().upper()
        if peer_url:
            payload = self._http_fetch_pairing(peer_url)
            if payload.get("short_code", "").upper() != needle:
                raise ValueError("short code does not match peer")
            payload["url"] = payload.get("url") or peer_url.rstrip("/")
            return self.pair(payload)
        for agent in self._reachable:
            if agent.short_code() == needle:
                return self.pair(agent.pairing_payload())
        raise ValueError(f"no reachable peer with short code {needle}")

    def accept_pair_offer(self, payload: dict[str, Any]) -> Device:
        """Remote peer completed pairing and is offering their identity."""
        return self._trust_payload(payload)

    def remember_peer_url(self, peer_id: UUID, url: str) -> None:
        self._peer_urls[peer_id] = url
        self._persist_locator_hints()

    def peer_urls(self) -> dict[UUID, str]:
        return dict(self._peer_urls)

    def _persist_locator_hints(self) -> None:
        if not self._persist:
            return
        save_locator_hints(self._locator_hints_path, self._peer_urls)

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
        if self.base_url:
            self._discovery.advertise(
                LanAdvertisement(
                    name=self.name,
                    short_code=self.short_code(),
                    locator=self.base_url,
                )
            )
            # FakeLanDiscovery.publish registers pairing + in-process handle.
            publish = getattr(self._discovery, "publish", None)
            if callable(publish):
                publish(self, locator=self.base_url)
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
            self._pair_candidates[ad.locator] = {
                "name": payload.get("name") or ad.name,
                "short_code": payload.get("short_code") or ad.short_code,
                "locator": ad.locator,
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

    def ingest_events(self, events: list[Event]) -> None:
        for event in events:
            self._ingest(event)

    def tag_mix(self, mix_id: UUID, tags: list[str]) -> Mix:
        if mix_id not in self.catalog.mixes:
            raise KeyError(f"unknown mix {mix_id}")
        with self._view_notice_batch():
            self._append_and_apply(
                EventType.MIX_TAGGED,
                {"mix_id": str(mix_id), "tags": list(tags)},
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
        """Start a local 20s undo window; nothing syncs until commit."""
        self.commit_pending_rejects()
        if mix_id not in self.catalog.mixes:
            raise KeyError(f"unknown mix {mix_id}")
        if self.catalog.mixes[mix_id].rejected:
            return self.catalog.mixes[mix_id]
        self._rejects.start(mix_id, self.device.id, now=self._clock())
        return self.catalog.mixes[mix_id]

    def undo_reject(self, mix_id: UUID) -> bool:
        """Cancel a pending reject during the undo window."""
        return self._rejects.undo(mix_id)

    def un_reject_mix(self, mix_id: UUID) -> Mix:
        """Clear a committed Reject so the Mix may re-enter sequences again."""
        self.commit_pending_rejects()
        if mix_id not in self.catalog.mixes:
            raise KeyError(f"unknown mix {mix_id}")
        if not self.catalog.mixes[mix_id].rejected:
            return self.catalog.mixes[mix_id]
        with self._view_notice_batch():
            self._append_and_apply(
                EventType.MIX_UNREJECTED,
                {"mix_id": str(mix_id)},
            )
            self._rebuild_all_sequences()
        return self.catalog.mixes[mix_id]

    def pending_rejects(self) -> list[RejectPending]:
        self.commit_pending_rejects()
        return self._rejects.pending()

    def commit_pending_rejects(self) -> list[UUID]:
        """Commit rejects whose undo windows have ended; delete + rebuild."""
        committed: list[UUID] = []
        with self._view_notice_batch():
            for pending in self._rejects.ready_to_commit(now=self._clock()):
                if pending.mix_id not in self.catalog.mixes:
                    continue
                if self.catalog.mixes[pending.mix_id].rejected:
                    committed.append(pending.mix_id)
                    continue
                self._append_and_apply(
                    EventType.MIX_REJECTED,
                    {"mix_id": str(pending.mix_id)},
                )
                self._rebuild_all_sequences()
                self.fill_caches()
                committed.append(pending.mix_id)
        return committed

    def create_intent(
        self,
        name: str,
        *,
        tags: list[str] | None = None,
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
            distribution=distribution or StarDistribution(),
            device_hours=hours,
            seed=seed if seed is not None else random.randrange(1 << 31),
        )
        self._upsert_intent_and_rebuild(intent)
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
            resolved_expiry = expires_at  # type: ignore[assignment]
        hours = [dh for dh in intent.device_hours if dh.device_id != device_id]
        hours.append(
            DeviceHours(
                device_id=device_id,
                budget_seconds=budget_seconds,
                expires_at=resolved_expiry,
            )
        )
        updated = intent.model_copy(update={"device_hours": hours})
        self._upsert_intent_and_rebuild(updated)
        return self.catalog.intents[intent_id]

    def delete_artist(self, artist_id: UUID) -> None:
        if artist_id not in self.catalog.artists:
            raise KeyError(f"unknown artist {artist_id}")
        self._append_and_apply(
            EventType.ARTIST_DELETED,
            {"id": str(artist_id)},
        )
        self._rebuild_all_sequences()
        self.fill_caches()

    def delete_intent(self, intent_id: UUID) -> None:
        if intent_id not in self.catalog.intents:
            raise KeyError(f"unknown intent {intent_id}")
        self._append_and_apply(
            EventType.INTENT_DELETED,
            {"id": str(intent_id)},
        )
        self._prune_unassigned_files()

    def update_intent(
        self,
        intent_id: UUID,
        *,
        name: str | None = None,
        tags: list[str] | None = None,
        distribution: StarDistribution | None = None,
        device_hours: list[DeviceHoursSpec] | None = None,
    ) -> Intent:
        intent = self.catalog.intents.get(intent_id)
        if intent is None:
            raise KeyError(f"unknown intent {intent_id}")
        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if tags is not None:
            updates["tags"] = list(tags)
        if distribution is not None:
            updates["distribution"] = distribution
        if device_hours is not None:
            hours = _device_hours_from_spec(device_hours)
            self._require_known_devices([dh.device_id for dh in hours])
            updates["device_hours"] = hours
        if not updates:
            return intent
        updated = intent.model_copy(update=updates)
        self._upsert_intent_and_rebuild(updated)
        return self.catalog.intents[intent_id]

    def refresh_intent_sequence(self, intent_id: UUID) -> Intent:
        """Re-roll the intent seed and rebuild shared sequence + assignments."""
        intent = self.catalog.intents.get(intent_id)
        if intent is None:
            raise KeyError(f"unknown intent {intent_id}")
        updated = intent.model_copy(update={"seed": random.randrange(1 << 31)})
        self._upsert_intent_and_rebuild(updated)
        return self.catalog.intents[intent_id]

    def apply_expired_hours(self) -> list[tuple[UUID, UUID]]:
        """Remove device hours whose expires_at has passed; prune exclusive files."""
        now = self._clock()
        applied: list[tuple[UUID, UUID]] = []
        for intent in list(self.intents()):
            expired_ids = [
                dh.device_id
                for dh in intent.device_hours
                if dh.expires_at is not None and dh.expires_at <= now
            ]
            if not expired_ids:
                continue
            expired_set = set(expired_ids)
            remaining = [
                dh for dh in intent.device_hours if dh.device_id not in expired_set
            ]
            updated = intent.model_copy(update={"device_hours": remaining})
            self._upsert_intent_and_rebuild(updated)
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
        """Drop local blobs no remaining assignment wants (except currently playing)."""
        wanted: set[UUID] = set()
        for intent in self.intents():
            assignment = self.assignment(intent.id)
            if assignment is None:
                continue
            wanted.update(assignment.mix_ids)
        playing = self.current_mix() if self.is_playing() else None
        for mix_id in list(self._local_file_ids()):
            if mix_id in wanted:
                continue
            if playing is not None and mix_id == playing:
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
            self._append_and_apply(EventType.MIX_ADDED, _mix_added_payload(mix))
        return self.catalog.mixes[mix.id]

    def export_events(self) -> list[Event]:
        return self._log.all()

    def sync(self, *, fill: bool = True) -> None:
        self.commit_pending_rejects()
        self.apply_expired_hours()
        self.note("sync start")
        for agent in list(self._reachable):
            if not self._trusts_public_key(agent.public_key_pem):
                continue
            if not self._ensure_agent_proved(agent):
                continue
            before = len(self._seen_event_ids)
            for event in agent.export_events():
                self._ingest(event)
            ingested = len(self._seen_event_ids) - before
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
            before = len(self._seen_event_ids)
            self.ingest_events(self._http_fetch_events(url))
            ingested = len(self._seen_event_ids) - before
            self.note(f"sync peer {label} ({url}): {ingested} new event(s)")
        # Peer may have applied our expiry; drop exclusive locals after ingest.
        self.apply_expired_hours()
        self._prune_unassigned_files()
        if fill:
            self.note("sync catalog end · filling caches")
            # Unmetered standing fill after catalog catches up with peers.
            self.fill_caches()
        else:
            self.note("sync catalog end")

    def _ensure_local_file(
        self,
        intent_id: UUID,
        mix_id: UUID,
        *,
        override_intent_id: UUID | None = None,
    ) -> None:
        if self._has_local_file(mix_id):
            return
        mix = self.catalog.mixes.get(mix_id)
        if mix is None:
            return
        label = mix.title

        # Prefer a copy from any reachable peer that already has the bytes.
        # Peer / USB copies ignore the metered cap.
        for peer in self._reachable:
            if not self._trusts_public_key(peer.public_key_pem):
                continue
            peer_bytes = peer.file_bytes(mix_id)
            if peer_bytes is not None:
                self.note(f"copy from peer {peer.name}: {label}")
                self._with_download(mix_id, lambda: self._store_local_file(mix_id, peer_bytes))
                self.note(f"cached: {label}")
                return

        preferred = self._preferred_origin_agent(intent_id, mix_id)
        if preferred is self:
            if not self._origin_fetch_allowed(intent_id, mix_id, override_intent_id):
                return
            self.note(f"download from origin: {label}")
            self._with_download(
                mix_id,
                lambda: self._store_local_file(
                    mix_id,
                    self.source.fetch_bytes(mix.url, on_progress=self._on_download_progress),
                ),
            )
            self.note(f"cached: {label}")
            return
        if preferred is not None:
            # Preferred peer is reachable but does not have the file yet — wait.
            return
        # Preferred unreachable (or no other assignee): fetch our own hours.
        if not self._origin_fetch_allowed(intent_id, mix_id, override_intent_id):
            return
        self.note(f"download from origin: {label}")
        self._with_download(
            mix_id,
            lambda: self._store_local_file(
                mix_id,
                self.source.fetch_bytes(mix.url, on_progress=self._on_download_progress),
            ),
        )
        self.note(f"cached: {label}")

    def _on_download_progress(self, downloaded: int, total: int | None) -> None:
        with self._download_lock:
            self._download_bytes = max(0, int(downloaded))
            self._download_total_bytes = None if total is None else max(0, int(total))

    def _with_download(self, mix_id: UUID, action: Callable[[], None]) -> None:
        with self._download_lock:
            self._downloading_mix_id = mix_id
            self._download_bytes = 0
            self._download_total_bytes = None
        try:
            action()
        finally:
            with self._download_lock:
                if self._downloading_mix_id == mix_id:
                    self._downloading_mix_id = None
                    self._download_bytes = 0
                    self._download_total_bytes = None

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
        self._local_files[mix_id] = data
        blob = self._blob_path(mix_id)
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(data)
        self._mark_view_sections(UIViewSection.CACHE)

    def _local_file_size(self, mix_id: UUID) -> int | None:
        blob = self._blob_path(mix_id)
        if blob.is_file():
            return blob.stat().st_size
        data = self._local_files.get(mix_id)
        if data is not None:
            return len(data)
        return None

    def _has_local_file(self, mix_id: UUID) -> bool:
        return mix_id in self._local_files or self._blob_path(mix_id).is_file()

    def _local_file_ids(self) -> set[UUID]:
        ids = set(self._local_files)
        blobs = self.data_dir / "blobs"
        if blobs.is_dir():
            for path in blobs.iterdir():
                if not path.is_file():
                    continue
                try:
                    ids.add(UUID(path.name))
                except ValueError:
                    continue
        return ids

    def _ensure_blob_on_disk(self, mix_id: UUID) -> Path:
        blob = self._blob_path(mix_id)
        if blob.is_file():
            return blob
        data = self._local_files.get(mix_id)
        if data is None:
            raise ValueError("mix has no local file")
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(data)
        return blob

    def _blob_path(self, mix_id: UUID) -> Path:
        return self.data_dir / "blobs" / str(mix_id)

    def _refresh_intent_folders(self) -> None:
        self._remove_orphan_intent_folders()
        for intent in self.intents():
            folder = self.intent_folder(intent.id)
            # Clear previous links/files so folder matches current assignment.
            for existing in folder.iterdir():
                if existing.is_file() or existing.is_symlink():
                    existing.unlink()
            assignment = self.assignment(intent.id)
            if assignment is None:
                continue
            for mix_id in assignment.mix_ids:
                if not self._has_local_file(mix_id):
                    continue
                mix = self.catalog.mixes.get(mix_id)
                if mix is None:
                    continue
                blob = self._ensure_blob_on_disk(mix_id)
                target = folder / _safe_filename(mix.title, mix_id)
                if target.exists() or target.is_symlink():
                    target.unlink()
                try:
                    target.hardlink_to(blob)
                except OSError:
                    target.write_bytes(blob.read_bytes())

    def _remove_orphan_intent_folders(self) -> None:
        """Drop intent folder trees whose intent no longer exists."""
        root = self.data_dir / "intents"
        if not root.is_dir():
            return
        live = {str(intent.id) for intent in self.intents()}
        for path in list(root.iterdir()):
            if not path.is_dir():
                continue
            if path.name in live:
                continue
            shutil.rmtree(path, ignore_errors=True)

    def _remove_intent_folder(self, intent_id: UUID) -> None:
        folder = self.data_dir / "intents" / str(intent_id)
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)

    def _revoke_peer(self, device_id: UUID) -> None:
        """Drop trust, Locator hints, and buffered events for a Peer."""
        self._unpaired_device_ids.add(device_id)
        self.catalog.remove_device(device_id)
        if device_id in self._peer_urls:
            self._peer_urls.pop(device_id, None)
            self._persist_locator_hints()
        for event_id, event in list(self._unknown_author_buffer.items()):
            if event.device_id == device_id:
                self._unknown_author_buffer.pop(event_id, None)
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
        expected = short_code_from_key(public_key_pem)
        if payload.get("short_code") and payload["short_code"].upper() != expected:
            raise ValueError("short code does not match public key")
        existing = self.catalog.devices.get(peer_id)
        if existing is None:
            existing = next(
                (d for d in self.catalog.devices.values() if d.public_key_pem == public_key_pem),
                None,
            )
        self._unpaired_device_ids.discard(peer_id)
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

    def _replay_event_log(self) -> None:
        """Rebuild Catalog from the durable Event log (cold start; no re-append)."""
        with self._event_lock:
            for event in self._log.all():
                if event.device_id == self.device.id:
                    if not self._verify(event, self.public_key_pem):
                        raise InvalidSignature("event signature mismatch")
                    self._event_seq = max(self._event_seq, int(event.seq))
                else:
                    if event.device_id in self._unpaired_device_ids:
                        self._seen_event_ids.add(event.id)
                        continue
                    author = self.catalog.devices.get(event.device_id)
                    # Unknown author: still apply; event was verified when ingested to this log.
                    if author is not None and not self._verify(event, author.public_key_pem):
                        raise InvalidSignature("event signature mismatch")
                self._seen_event_ids.add(event.id)
                self._apply(event)

    def _append_and_apply(self, event_type: EventType, payload: dict[str, Any]) -> Event:
        with self._event_lock:
            self._event_seq += 1
            event = Event(
                type=event_type,
                device_id=self.device.id,
                created_at=self._clock(),
                seq=self._event_seq,
                payload=payload,
            )
            event.signature = self._sign(event)
            self._log.append(event)
            self._seen_event_ids.add(event.id)
            self._apply(event)
        self._mark_view_sections_for_event(event_type)
        self._schedule_auto_sync()
        return event

    def _merge_win_for(self, event: Event) -> MergeWin:
        return (event.created_at, event.device_id, int(event.seq), event.id)

    def _merge_beats(self, key: MergeKey, event: Event) -> bool:
        """Last-by author time, then (device_id, seq, event.id)."""
        incoming = self._merge_win_for(event)
        current = self._merge_wins.get(key)
        if current is None or incoming > current:
            self._merge_wins[key] = incoming
            return True
        return False

    def _flush_pending_intent_projection(self, intent_id: UUID) -> None:
        """Apply buffered Sequence/Assignment after Intent upsert wins."""
        sequence = self._pending_sequences.pop(intent_id, None)
        if sequence is not None:
            self.catalog.set_sequence(sequence)
        for key, assignment in list(self._pending_assignments.items()):
            if key[0] != intent_id:
                continue
            del self._pending_assignments[key]
            if assignment is None:
                self.catalog.clear_assignment(intent_id, key[1])
            else:
                self.catalog.set_assignment(assignment)

    def _playhead_should_apply(
        self, existing: Playhead | None, event: Event, position: float
    ) -> bool:
        """Hybrid Playhead merge using signed author time (event.created_at)."""
        key: MergeKey = ("playhead", str(event.payload["mix_id"]))
        incoming = self._merge_win_for(event)
        if existing is None:
            self._merge_wins[key] = incoming
            return True
        delta = abs((event.created_at - existing.updated_at).total_seconds())
        if delta <= PLAYHEAD_NEAR_SECONDS:
            if position > existing.position_seconds:
                self._merge_wins[key] = incoming
                return True
            if position < existing.position_seconds:
                return False
            # Equal position: later author time, else last-by-(device_id, seq, event.id).
            if event.created_at > existing.updated_at:
                self._merge_wins[key] = incoming
                return True
            if event.created_at < existing.updated_at:
                return False
            return self._merge_beats(key, event)
        if event.created_at > existing.updated_at:
            self._merge_wins[key] = incoming
            return True
        if event.created_at < existing.updated_at:
            return False
        return self._merge_beats(key, event)
    def _schedule_auto_sync(self) -> None:
        """Pull on this device and nudge trusted reachable peers to pull too.

        Each side's ``sync`` still runs the key-proof meet gate before ingest.
        """
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

    def _ingest(self, event: Event) -> None:
        with self._event_lock:
            if event.id in self._seen_event_ids:
                return
            if event.device_id == self.device.id:
                return
            if event.device_id in self._unpaired_device_ids:
                return
            author = self.catalog.devices.get(event.device_id)
            if author is None:
                self._unknown_author_buffer[event.id] = event
                return
            self._unknown_author_buffer.pop(event.id, None)
            self._commit_foreign_event(event, author.public_key_pem)

    def _commit_foreign_event(self, event: Event, public_key_pem: str) -> None:
        """Verify, append, and apply a peer event. Caller must hold ``_event_lock``."""
        if not self._verify(event, public_key_pem):
            raise InvalidSignature("event signature mismatch")
        self._seen_event_ids.add(event.id)
        self._log.append(event)
        self._apply(event)

    def _flush_buffered_events_for(self, author_id: UUID) -> None:
        """Verify and apply buffered events for a newly known author.

        Caller must hold ``_event_lock``. Applying a buffered ``DEVICE_PAIRED``
        may flush further authors. Order follows signed author time then seq.
        """
        pending = sorted(
            (
                event
                for event in self._unknown_author_buffer.values()
                if event.device_id == author_id
            ),
            key=lambda e: (e.created_at, int(e.seq), e.id),
        )
        for event in pending:
            self._unknown_author_buffer.pop(event.id, None)
            if event.id in self._seen_event_ids:
                continue
            author = self.catalog.devices.get(event.device_id)
            if author is None:
                self._unknown_author_buffer[event.id] = event
                continue
            self._commit_foreign_event(event, author.public_key_pem)

    def _upsert_intent_and_rebuild(self, intent: Intent) -> None:
        with self._view_notice_batch():
            self._append_and_apply(EventType.INTENT_UPSERTED, _intent_payload(intent))
            self._rebuild_sequence_for_intent(intent)
            self._prune_unassigned_files()

    def _rebuild_all_sequences(self) -> None:
        with self._view_notice_batch():
            for intent in self.intents():
                self._rebuild_sequence_for_intent(intent)
            self._prune_unassigned_files()

    def _rebuild_sequence_for_intent(self, intent: Intent) -> None:
        active_devices = {dh.device_id for dh in intent.device_hours}
        for iid, device_id in list(self.catalog.assignments):
            if iid == intent.id and device_id not in active_devices:
                self._append_and_apply(
                    EventType.ASSIGNMENT_CLEARED,
                    {
                        "intent_id": str(intent.id),
                        "device_id": str(device_id),
                    },
                )
        sequence = build_sequence(intent, self.catalog.mixes_list())
        self._append_and_apply(
            EventType.SEQUENCE_BUILT,
            {
                "intent_id": str(sequence.intent_id),
                "entries": [
                    {
                        "mix_id": str(entry.mix_id),
                        "position": entry.position,
                        "bucket": entry.bucket.value,
                    }
                    for entry in sequence.entries
                ],
            },
        )
        duration_by_mix = {
            mix_id: mix.duration_seconds for mix_id, mix in self.catalog.mixes.items()
        }
        for device_hours in intent.device_hours:
            mix_ids = assign_by_budget(
                sequence,
                device_hours.device_id,
                device_hours.budget_seconds,
                duration_by_mix,
            )
            self._append_and_apply(
                EventType.ASSIGNMENT_SET,
                {
                    "intent_id": str(intent.id),
                    "device_id": str(device_hours.device_id),
                    "mix_ids": [str(mix_id) for mix_id in mix_ids],
                    "budget_seconds": device_hours.budget_seconds,
                },
            )

    def _delete_played_file_if_replaced(self, played_mix_id: UUID) -> None:
        """Drop a played mix's bytes once another assigned mix is local."""
        if not self._has_local_file(played_mix_id):
            return
        replacement_local = False
        for intent in self.intents():
            assignment = self.assignment(intent.id)
            if assignment is None:
                continue
            for mix_id in assignment.mix_ids:
                if mix_id != played_mix_id and self._has_local_file(mix_id):
                    replacement_local = True
                    break
            if replacement_local:
                break
        if replacement_local:
            self.remove_local_file(played_mix_id)

    def _apply(self, event: Event) -> None:
        payload = event.payload
        if event.type is EventType.DEVICE_PAIRED:
            device_id = UUID(payload["id"])
            if device_id == self.device.id:
                return
            if device_id in self._unpaired_device_ids:
                # Only a local re-pair (QR / short code) may restore trust.
                if event.device_id != self.device.id:
                    return
                self._unpaired_device_ids.discard(device_id)
            public_key_pem = payload["public_key_pem"]
            existing = self.catalog.devices.get(device_id)
            if existing is None and any(
                d.public_key_pem == public_key_pem for d in self.catalog.devices.values()
            ):
                return
            # Idempotent upsert by device id (and by public key when already trusted).
            self.catalog.add_device(
                Device(
                    id=device_id if existing is None else existing.id,
                    name=payload["name"],
                    public_key_pem=public_key_pem,
                    priority=int(payload.get("priority", 100)),
                    paired_at=(
                        existing.paired_at if existing is not None else self._clock()
                    ),
                )
            )
            self._flush_buffered_events_for(device_id)
            return
        if event.type is EventType.DEVICE_UNPAIRED:
            device_id = UUID(payload["id"])
            if device_id == self.device.id:
                return
            self._revoke_peer(device_id)
            return
        if event.type is EventType.ARTIST_ADDED:
            artist_id = UUID(payload["id"])
            if artist_id in self._deleted_artists:
                return
            self.catalog.add_artist(
                Artist(
                    id=artist_id,
                    platform=Platform(payload["platform"]),
                    platform_id=payload["platform_id"],
                    name=payload["name"],
                    url=payload["url"],
                )
            )
            return
        if event.type is EventType.ARTIST_DELETED:
            artist_id = UUID(payload["id"])
            self._deleted_artists.add(artist_id)
            removed_mix_ids = self.catalog.delete_artist(artist_id)
            for mix_id in removed_mix_ids:
                self.remove_local_file(mix_id)
            return
        if event.type is EventType.MIX_ADDED:
            mix_id = UUID(payload["id"])
            artist_id = UUID(payload["artist_id"])
            if artist_id in self._deleted_artists:
                return
            raw_size = payload.get("size_bytes")
            size_bytes = None if raw_size is None else int(raw_size)
            existing = self.catalog.mixes.get(mix_id)
            tags = list(existing.tags) if existing is not None else []
            stars = existing.stars if existing is not None else None
            if mix_id in self._pending_tags:
                tags = list(self._pending_tags[mix_id])
            if mix_id in self._pending_stars:
                stars = self._pending_stars[mix_id]
            mix = Mix(
                id=mix_id,
                artist_id=artist_id,
                platform=Platform(payload["platform"]),
                platform_id=payload["platform_id"],
                title=payload["title"],
                url=payload["url"],
                duration_seconds=int(payload["duration_seconds"]),
                size_bytes=size_bytes,
                tags=tags,
                stars=stars,
                rejected=(
                    True
                    if mix_id in self._rejected_mix_ids
                    else (existing.rejected if existing is not None else False)
                ),
                played=(
                    True
                    if mix_id in self._played_mix_ids
                    else (existing.played if existing is not None else False)
                ),
                last_heard_at=(
                    self._pending_last_heard.get(mix_id)
                    if mix_id in self._pending_last_heard
                    else (existing.last_heard_at if existing is not None else None)
                ),
            )
            self.catalog.add_mix(mix)
            return
        if event.type is EventType.MIX_TAGGED:
            mix_id = UUID(payload["mix_id"])
            if not self._merge_beats(("tags", str(mix_id)), event):
                return
            tags = list(payload["tags"])
            self._pending_tags[mix_id] = tags
            mix = self.catalog.mixes.get(mix_id)
            if mix is not None:
                self.catalog.add_mix(mix.model_copy(update={"tags": tags}))
            return
        if event.type is EventType.MIX_RATED:
            mix_id = UUID(payload["mix_id"])
            if not self._merge_beats(("stars", str(mix_id)), event):
                return
            stars = Stars(int(payload["stars"]))
            self._pending_stars[mix_id] = stars
            mix = self.catalog.mixes.get(mix_id)
            if mix is not None:
                self.catalog.add_mix(mix.model_copy(update={"stars": stars}))
            return
        if event.type is EventType.MIX_REJECTED:
            mix_id = UUID(payload["mix_id"])
            if not self._merge_beats(("reject", str(mix_id)), event):
                return
            self._rejected_mix_ids.add(mix_id)
            mix = self.catalog.mixes.get(mix_id)
            if mix is not None:
                self.catalog.add_mix(mix.model_copy(update={"rejected": True}))
            self.remove_local_file(mix_id)
            return
        if event.type is EventType.MIX_UNREJECTED:
            mix_id = UUID(payload["mix_id"])
            if not self._merge_beats(("reject", str(mix_id)), event):
                return
            self._rejected_mix_ids.discard(mix_id)
            mix = self.catalog.mixes.get(mix_id)
            if mix is not None:
                self.catalog.add_mix(mix.model_copy(update={"rejected": False}))
            return
        if event.type is EventType.INTENT_UPSERTED:
            intent_id = UUID(payload["id"])
            if not self._merge_beats(("intent", str(intent_id)), event):
                return
            self.catalog.upsert_intent(_intent_from_payload(payload))
            self._flush_pending_intent_projection(intent_id)
            return
        if event.type is EventType.INTENT_DELETED:
            intent_id = UUID(payload["id"])
            if not self._merge_beats(("intent", str(intent_id)), event):
                return
            self.catalog.delete_intent(intent_id)
            self._pending_sequences.pop(intent_id, None)
            for key in [k for k in self._pending_assignments if k[0] == intent_id]:
                del self._pending_assignments[key]
            self._remove_intent_folder(intent_id)
            return
        if event.type is EventType.SEQUENCE_BUILT:
            intent_id = UUID(payload["intent_id"])
            if not self._merge_beats(("sequence", str(intent_id)), event):
                return
            sequence = Sequence(
                intent_id=intent_id,
                entries=[
                    SequenceEntry(
                        mix_id=UUID(entry["mix_id"]),
                        position=int(entry["position"]),
                        bucket=_bucket_from_payload(entry["bucket"]),
                    )
                    for entry in payload["entries"]
                ],
            )
            if intent_id not in self.catalog.intents:
                self._pending_sequences[intent_id] = sequence
                return
            self.catalog.set_sequence(sequence)
            return
        if event.type is EventType.ASSIGNMENT_SET:
            intent_id = UUID(payload["intent_id"])
            device_id = UUID(payload["device_id"])
            if not self._merge_beats(
                ("assignment", str(intent_id), str(device_id)), event
            ):
                return
            assignment = Assignment(
                intent_id=intent_id,
                device_id=device_id,
                mix_ids=[UUID(mix_id) for mix_id in payload["mix_ids"]],
                budget_seconds=int(payload["budget_seconds"]),
            )
            if intent_id not in self.catalog.intents:
                self._pending_assignments[(intent_id, device_id)] = assignment
                return
            self.catalog.set_assignment(assignment)
            return
        if event.type is EventType.ASSIGNMENT_CLEARED:
            intent_id = UUID(payload["intent_id"])
            device_id = UUID(payload["device_id"])
            if not self._merge_beats(
                ("assignment", str(intent_id), str(device_id)), event
            ):
                return
            if intent_id not in self.catalog.intents:
                self._pending_assignments[(intent_id, device_id)] = None
                return
            self.catalog.clear_assignment(intent_id, device_id)
            return
        if event.type is EventType.PLAYHEAD:
            mix_id = UUID(payload["mix_id"])
            position = float(payload["position_seconds"])
            existing = self.catalog.playheads.get(mix_id)
            if not self._playhead_should_apply(existing, event, position):
                return
            self.catalog.set_playhead(
                Playhead(
                    mix_id=mix_id,
                    device_id=event.device_id,
                    position_seconds=position,
                    updated_at=event.created_at,
                )
            )
            return
        if event.type is EventType.PLAYED:
            mix_id = UUID(payload["mix_id"])
            self._played_mix_ids.add(mix_id)
            mix = self.catalog.mixes.get(mix_id)
            if mix is not None and not mix.played:
                self.catalog.add_mix(mix.model_copy(update={"played": True}))
            return
        if event.type is EventType.LAST_HEARD:
            mix_id = UUID(payload["mix_id"])
            if not self._merge_beats(("last_heard", str(mix_id)), event):
                return
            heard_at = event.created_at
            self._pending_last_heard[mix_id] = heard_at
            mix = self.catalog.mixes.get(mix_id)
            if mix is not None:
                self.catalog.add_mix(mix.model_copy(update={"last_heard_at": heard_at}))
            return

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

    def _http_offer_pair(self, peer_url: str) -> None:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.post(
                f"{peer_url.rstrip('/')}/api/pair/accept",
                json={"payload": self.pairing_payload()},
            )
            response.raise_for_status()

    def _http_fetch_pairing(self, peer_url: str) -> dict[str, Any]:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.get(f"{peer_url.rstrip('/')}/api/pairing")
            response.raise_for_status()
            return response.json()

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
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.get(f"{peer_url.rstrip('/')}/api/events")
            response.raise_for_status()
            raw_events = response.json().get("events", [])
        return [Event.model_validate(raw) for raw in raw_events]


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
                    expires_at=expires_at,
                )
            )
        else:
            raise ValueError(
                "device_hours entries must be (device_id, budget) "
                "or (device_id, budget, expires_at)"
            )
    return hours


def _mix_added_payload(mix: Mix) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(mix.id),
        "artist_id": str(mix.artist_id),
        "platform": mix.platform.value,
        "platform_id": mix.platform_id,
        "title": mix.title,
        "url": mix.url,
        "duration_seconds": mix.duration_seconds,
    }
    if mix.size_bytes is not None:
        payload["size_bytes"] = int(mix.size_bytes)
    return payload


def _intent_payload(intent: Intent) -> dict[str, Any]:
    return {
        "id": str(intent.id),
        "name": intent.name,
        "tags": list(intent.tags),
        "distribution": {
            "five": intent.distribution.five,
            "four": intent.distribution.four,
            "three": intent.distribution.three,
            "two": intent.distribution.two,
            "one": intent.distribution.one,
            "unrated": intent.distribution.unrated,
        },
        "device_hours": [
            {
                "device_id": str(dh.device_id),
                "budget_seconds": dh.budget_seconds,
                "expires_at": dh.expires_at.isoformat() if dh.expires_at else None,
            }
            for dh in intent.device_hours
        ],
        "seed": intent.seed,
    }


def _bucket_from_payload(raw: str) -> StarBucket:
    # Older sequences stored unrated+1★+2★ as "rest".
    if raw == "rest":
        return StarBucket.UNRATED
    return StarBucket(raw)


def _distribution_from_payload(dist: dict[str, Any]) -> StarDistribution:
    if "unrated" not in dist and "rest" in dist:
        return StarDistribution(
            five=float(dist.get("five", 0.3)),
            four=float(dist.get("four", 0.2)),
            three=float(dist.get("three", 0.1)),
            two=0.0,
            one=0.0,
            unrated=float(dist["rest"]),
        )
    return StarDistribution(
        five=float(dist.get("five", 0.3)),
        four=float(dist.get("four", 0.2)),
        three=float(dist.get("three", 0.1)),
        two=float(dist.get("two", 0.05)),
        one=float(dist.get("one", 0.05)),
        unrated=float(dist.get("unrated", 0.3)),
    )


def _intent_from_payload(payload: dict[str, Any]) -> Intent:
    dist = payload.get("distribution") or {}
    return Intent(
        id=UUID(payload["id"]),
        name=payload["name"],
        tags=list(payload.get("tags") or []),
        distribution=_distribution_from_payload(dist),
        device_hours=[
            DeviceHours(
                device_id=UUID(dh["device_id"]),
                budget_seconds=int(dh["budget_seconds"]),
                expires_at=(
                    datetime.fromisoformat(dh["expires_at"])
                    if dh.get("expires_at")
                    else None
                ),
            )
            for dh in payload.get("device_hours") or []
        ],
        seed=int(payload["seed"]),
    )


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


def _last_heard_threshold(duration_seconds: int) -> float:
    """Meaningful-listen threshold: max(120s, 5% of duration)."""
    return max(
        LAST_HEARD_FLOOR_SECONDS,
        LAST_HEARD_DURATION_FRACTION * float(duration_seconds),
    )


def _safe_filename(title: str, mix_id: UUID) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in title).strip()
    if not cleaned:
        cleaned = "mix"
    return f"{cleaned[:80]}-{mix_id}.bin"
