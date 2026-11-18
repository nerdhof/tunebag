"""Catalog projection: pure Event → CatalogState + local File/folder effects.

DeviceAgent owns Event-log I/O and executes ``LocalEffects``. Merge rules match
CONTEXT.md (sticky Played/Skipped/Artist delete, LWW fields, hybrid Playhead).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from tunebag.domain import (
    AlbumTrack,
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
    SequenceEntry,
    StarBucket,
    StarDistribution,
    Stars,
    default_intent_platforms,
)
from tunebag.events import Event, EventType

PLAYHEAD_NEAR_SECONDS = 120.0

MergeKey = tuple[str, ...]
# Author time first (causal on one Device); (device_id, seq, id) breaks ties.
MergeWin = tuple[datetime, UUID, int, UUID]


@dataclass
class LocalEffects:
    """Device-local reactions that are not part of the Catalog projection."""

    delete_files: list[UUID] = field(default_factory=list)
    remove_intent_folders: list[UUID] = field(default_factory=list)


class CatalogState:
    """Projected Catalog plus merge bookkeeping (replayable from the Event log)."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or Path.home() / ".tunebag"
        self.artists: dict[UUID, Artist] = {}
        self.mixes: dict[UUID, Mix] = {}
        self.intents: dict[UUID, Intent] = {}
        self.sequences: dict[UUID, Sequence] = {}
        self.assignments: dict[tuple[UUID, UUID], Assignment] = {}
        self.devices: dict[UUID, Device] = {}
        self.playheads: dict[UUID, Playhead] = {}
        self.local_device_id: UUID | None = None
        # Deterministic merge bookkeeping (same events ⇒ same Catalog).
        self.merge_wins: dict[MergeKey, MergeWin] = {}
        self.deleted_artists: set[UUID] = set()
        self.rejected_mix_ids: set[UUID] = set()
        self.played_mix_ids: set[UUID] = set()
        self.skipped_mix_ids: set[UUID] = set()
        self.pending_tags: dict[UUID, list[str]] = {}
        self.pending_stars: dict[UUID, Stars] = {}
        self.pending_last_heard: dict[UUID, datetime] = {}
        self.pending_sequences: dict[UUID, Sequence] = {}
        self.pending_assignments: dict[tuple[UUID, UUID], Assignment | None] = {}
        # Sticky until local re-pair; remote DEVICE_PAIRED cannot undo.
        self.unpaired_device_ids: set[UUID] = set()
        # Events whose author is not yet in Catalog; flushed on DEVICE_PAIRED / pair.
        self.unknown_author_buffer: dict[UUID, Event] = {}

    def add_artist(self, artist: Artist) -> Artist:
        self.artists[artist.id] = artist
        return artist

    def delete_artist(self, artist_id: UUID) -> list[UUID]:
        """Remove artist and their mixes; return removed mix ids."""
        self.artists.pop(artist_id, None)
        removed: list[UUID] = []
        for mix_id, mix in list(self.mixes.items()):
            if mix.artist_id != artist_id:
                continue
            del self.mixes[mix_id]
            self.playheads.pop(mix_id, None)
            removed.append(mix_id)
        return removed

    def add_mix(self, mix: Mix) -> Mix:
        self.mixes[mix.id] = mix
        return mix

    def upsert_intent(self, intent: Intent) -> Intent:
        self.intents[intent.id] = intent
        return intent

    def delete_intent(self, intent_id: UUID) -> None:
        self.intents.pop(intent_id, None)
        self.sequences.pop(intent_id, None)
        for key in [key for key in self.assignments if key[0] == intent_id]:
            del self.assignments[key]

    def set_sequence(self, sequence: Sequence) -> Sequence:
        self.sequences[sequence.intent_id] = sequence
        return sequence

    def set_assignment(self, assignment: Assignment) -> Assignment:
        self.assignments[(assignment.intent_id, assignment.device_id)] = assignment
        return assignment

    def clear_assignment(self, intent_id: UUID, device_id: UUID) -> None:
        self.assignments.pop((intent_id, device_id), None)

    def add_device(self, device: Device) -> Device:
        self.devices[device.id] = device
        return device

    def remove_device(self, device_id: UUID) -> None:
        self.devices.pop(device_id, None)

    def set_playhead(self, playhead: Playhead) -> Playhead:
        """Store Playhead as given; hybrid merge is decided by ``apply``."""
        self.playheads[playhead.mix_id] = playhead
        return playhead

    def all_tags(self) -> list[str]:
        tags: set[str] = set()
        for mix in self.mixes.values():
            tags.update(mix.tags)
        return sorted(tags)

    def suggest_tags(self, prefix: str, limit: int = 10) -> list[str]:
        needle = prefix.strip().lower()
        return [tag for tag in self.all_tags() if tag.startswith(needle)][:limit]

    def mixes_list(self) -> list[Mix]:
        return list(self.mixes.values())


def apply(
    state: CatalogState,
    event: Event,
    *,
    local_device_id: UUID,
    now: datetime,
) -> tuple[CatalogState, LocalEffects]:
    """Apply one Event to Catalog projection state; return local File/folder effects."""
    effects = LocalEffects()
    payload = event.payload
    if event.type is EventType.DEVICE_PAIRED:
        _apply_device_paired(state, event, payload, local_device_id=local_device_id, now=now)
        return state, effects
    if event.type is EventType.DEVICE_UNPAIRED:
        device_id = UUID(payload["id"])
        if device_id != local_device_id:
            _revoke_peer_in_catalog(state, device_id)
        return state, effects
    if event.type is EventType.ARTIST_ADDED:
        artist_id = UUID(payload["id"])
        if artist_id not in state.deleted_artists:
            state.add_artist(
                Artist(
                    id=artist_id,
                    platform=Platform(payload["platform"]),
                    platform_id=payload["platform_id"],
                    name=payload["name"],
                    url=payload["url"],
                )
            )
        return state, effects
    if event.type is EventType.ARTIST_DELETED:
        artist_id = UUID(payload["id"])
        state.deleted_artists.add(artist_id)
        removed_mix_ids = state.delete_artist(artist_id)
        effects.delete_files.extend(removed_mix_ids)
        return state, effects
    if event.type is EventType.MIX_ADDED:
        _apply_mix_added(state, payload)
        return state, effects
    if event.type is EventType.MIX_TAGGED:
        mix_id = UUID(payload["mix_id"])
        if not _merge_beats(state, ("tags", str(mix_id)), event):
            return state, effects
        tags = list(payload["tags"])
        state.pending_tags[mix_id] = tags
        mix = state.mixes.get(mix_id)
        if mix is not None:
            state.add_mix(mix.model_copy(update={"tags": tags}))
        return state, effects
    if event.type is EventType.MIX_RATED:
        mix_id = UUID(payload["mix_id"])
        if not _merge_beats(state, ("stars", str(mix_id)), event):
            return state, effects
        stars = Stars(int(payload["stars"]))
        state.pending_stars[mix_id] = stars
        mix = state.mixes.get(mix_id)
        if mix is not None:
            state.add_mix(mix.model_copy(update={"stars": stars}))
        return state, effects
    if event.type is EventType.MIX_REJECTED:
        mix_id = UUID(payload["mix_id"])
        if not _merge_beats(state, ("reject", str(mix_id)), event):
            return state, effects
        state.rejected_mix_ids.add(mix_id)
        mix = state.mixes.get(mix_id)
        if mix is not None:
            state.add_mix(mix.model_copy(update={"rejected": True}))
        effects.delete_files.append(mix_id)
        return state, effects
    if event.type is EventType.MIX_UNREJECTED:
        mix_id = UUID(payload["mix_id"])
        if not _merge_beats(state, ("reject", str(mix_id)), event):
            return state, effects
        state.rejected_mix_ids.discard(mix_id)
        mix = state.mixes.get(mix_id)
        if mix is not None:
            state.add_mix(mix.model_copy(update={"rejected": False}))
        return state, effects
    if event.type is EventType.INTENT_UPSERTED:
        _apply_intent_upserted(state, event, payload)
        return state, effects
    if event.type is EventType.INTENT_DELETED:
        intent_id = UUID(payload["id"])
        if not _merge_beats(state, ("intent", str(intent_id)), event):
            return state, effects
        state.delete_intent(intent_id)
        state.pending_sequences.pop(intent_id, None)
        for key in [k for k in state.pending_assignments if k[0] == intent_id]:
            del state.pending_assignments[key]
        effects.remove_intent_folders.append(intent_id)
        return state, effects
    if event.type is EventType.SEQUENCE_BUILT:
        intent_id = UUID(payload["intent_id"])
        if not _merge_beats(state, ("sequence", str(intent_id)), event):
            return state, effects
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
        if intent_id not in state.intents:
            state.pending_sequences[intent_id] = sequence
            return state, effects
        state.set_sequence(sequence)
        return state, effects
    if event.type is EventType.ASSIGNMENT_SET:
        intent_id = UUID(payload["intent_id"])
        device_id = UUID(payload["device_id"])
        if device_id in state.unpaired_device_ids:
            state.clear_assignment(intent_id, device_id)
            state.pending_assignments.pop((intent_id, device_id), None)
            return state, effects
        if not _merge_beats(state, ("assignment", str(intent_id), str(device_id)), event):
            return state, effects
        assignment = Assignment(
            intent_id=intent_id,
            device_id=device_id,
            mix_ids=[UUID(mix_id) for mix_id in payload["mix_ids"]],
            budget_seconds=int(payload["budget_seconds"]),
        )
        if intent_id not in state.intents:
            state.pending_assignments[(intent_id, device_id)] = assignment
            return state, effects
        state.set_assignment(assignment)
        return state, effects
    if event.type is EventType.ASSIGNMENT_CLEARED:
        intent_id = UUID(payload["intent_id"])
        device_id = UUID(payload["device_id"])
        if not _merge_beats(state, ("assignment", str(intent_id), str(device_id)), event):
            return state, effects
        if intent_id not in state.intents:
            state.pending_assignments[(intent_id, device_id)] = None
            return state, effects
        state.clear_assignment(intent_id, device_id)
        return state, effects
    if event.type is EventType.PLAYHEAD:
        mix_id = UUID(payload["mix_id"])
        position = float(payload["position_seconds"])
        existing = state.playheads.get(mix_id)
        if not _playhead_should_apply(state, existing, event, position):
            return state, effects
        state.set_playhead(
            Playhead(
                mix_id=mix_id,
                device_id=event.device_id,
                position_seconds=position,
                updated_at=event.created_at,
            )
        )
        return state, effects
    if event.type is EventType.PLAYED:
        mix_id = UUID(payload["mix_id"])
        state.played_mix_ids.add(mix_id)
        mix = state.mixes.get(mix_id)
        if mix is not None and not mix.played:
            state.add_mix(mix.model_copy(update={"played": True}))
        return state, effects
    if event.type is EventType.SKIPPED:
        mix_id = UUID(payload["mix_id"])
        state.skipped_mix_ids.add(mix_id)
        mix = state.mixes.get(mix_id)
        if mix is not None and not mix.skipped:
            state.add_mix(mix.model_copy(update={"skipped": True}))
        return state, effects
    if event.type is EventType.LAST_HEARD:
        mix_id = UUID(payload["mix_id"])
        if not _merge_beats(state, ("last_heard", str(mix_id)), event):
            return state, effects
        heard_at = event.created_at
        state.pending_last_heard[mix_id] = heard_at
        mix = state.mixes.get(mix_id)
        if mix is not None:
            state.add_mix(mix.model_copy(update={"last_heard_at": heard_at}))
        return state, effects
    return state, effects


def replay(
    state: CatalogState,
    events: list[Event],
    *,
    local_device_id: UUID,
    now: datetime,
) -> tuple[CatalogState, LocalEffects]:
    """Apply many Events in order; accumulate local effects."""
    combined = LocalEffects()
    for event in events:
        state, effects = apply(
            state, event, local_device_id=local_device_id, now=now
        )
        combined.delete_files.extend(effects.delete_files)
        combined.remove_intent_folders.extend(effects.remove_intent_folders)
    return state, combined


def _merge_win_for(event: Event) -> MergeWin:
    return (event.created_at, event.device_id, int(event.seq), event.id)


def _merge_beats(state: CatalogState, key: MergeKey, event: Event) -> bool:
    """Last-by author time, then (device_id, seq, event.id)."""
    incoming = _merge_win_for(event)
    current = state.merge_wins.get(key)
    if current is None or incoming > current:
        state.merge_wins[key] = incoming
        return True
    return False


def _playhead_should_apply(
    state: CatalogState,
    existing: Playhead | None,
    event: Event,
    position: float,
) -> bool:
    """Hybrid Playhead merge using signed author time (event.created_at)."""
    key: MergeKey = ("playhead", str(event.payload["mix_id"]))
    incoming = _merge_win_for(event)
    if existing is None:
        state.merge_wins[key] = incoming
        return True
    delta = abs((event.created_at - existing.updated_at).total_seconds())
    if delta <= PLAYHEAD_NEAR_SECONDS:
        if position > existing.position_seconds:
            state.merge_wins[key] = incoming
            return True
        if position < existing.position_seconds:
            return False
        # Equal position: later author time, else last-by-(device_id, seq, event.id).
        if event.created_at > existing.updated_at:
            state.merge_wins[key] = incoming
            return True
        if event.created_at < existing.updated_at:
            return False
        return _merge_beats(state, key, event)
    if event.created_at > existing.updated_at:
        state.merge_wins[key] = incoming
        return True
    if event.created_at < existing.updated_at:
        return False
    return _merge_beats(state, key, event)


def _flush_pending_intent_projection(state: CatalogState, intent_id: UUID) -> None:
    """Apply buffered Sequence/Assignment after Intent upsert wins."""
    sequence = state.pending_sequences.pop(intent_id, None)
    if sequence is not None:
        state.set_sequence(sequence)
    for key, assignment in list(state.pending_assignments.items()):
        if key[0] != intent_id:
            continue
        del state.pending_assignments[key]
        if assignment is None:
            state.clear_assignment(intent_id, key[1])
        else:
            state.set_assignment(assignment)


def _apply_device_paired(
    state: CatalogState,
    event: Event,
    payload: dict[str, Any],
    *,
    local_device_id: UUID,
    now: datetime,
) -> None:
    device_id = UUID(payload["id"])
    if device_id == local_device_id:
        return
    if device_id in state.unpaired_device_ids:
        # Only a local re-pair (QR / short code) may restore trust.
        if event.device_id != local_device_id:
            return
        state.unpaired_device_ids.discard(device_id)
    public_key_pem = payload["public_key_pem"]
    existing = state.devices.get(device_id)
    if existing is None and any(
        d.public_key_pem == public_key_pem for d in state.devices.values()
    ):
        return
    # Idempotent upsert by device id (and by public key when already trusted).
    state.add_device(
        Device(
            id=device_id if existing is None else existing.id,
            name=payload["name"],
            public_key_pem=public_key_pem,
            priority=int(payload.get("priority", 100)),
            paired_at=(existing.paired_at if existing is not None else now),
        )
    )


def _revoke_peer_in_catalog(state: CatalogState, device_id: UUID) -> None:
    """Drop trust and hours/assignments/buffer for a Peer; Catalog rows stay."""
    state.unpaired_device_ids.add(device_id)
    state.remove_device(device_id)
    for intent in list(state.intents.values()):
        if any(dh.device_id == device_id for dh in intent.device_hours):
            remaining = [dh for dh in intent.device_hours if dh.device_id != device_id]
            state.upsert_intent(intent.model_copy(update={"device_hours": remaining}))
        state.clear_assignment(intent.id, device_id)
    for key in [k for k in state.pending_assignments if k[1] == device_id]:
        del state.pending_assignments[key]
    for event_id, buffered in list(state.unknown_author_buffer.items()):
        if buffered.device_id == device_id:
            state.unknown_author_buffer.pop(event_id, None)


def _apply_mix_added(state: CatalogState, payload: dict[str, Any]) -> None:
    mix_id = UUID(payload["id"])
    artist_id = UUID(payload["artist_id"])
    if artist_id in state.deleted_artists:
        return
    raw_size = payload.get("size_bytes")
    size_bytes = None if raw_size is None else int(raw_size)
    existing = state.mixes.get(mix_id)
    tags = list(existing.tags) if existing is not None else []
    stars = existing.stars if existing is not None else None
    if mix_id in state.pending_tags:
        tags = list(state.pending_tags[mix_id])
    if mix_id in state.pending_stars:
        stars = state.pending_stars[mix_id]
    kind_raw = payload.get("kind", ReleaseKind.MIX.value)
    kind = ReleaseKind(kind_raw)
    tracks = [
        AlbumTrack(
            platform_id=str(t["platform_id"]),
            title=str(t["title"]),
            url=str(t["url"]),
            duration_seconds=int(t["duration_seconds"]),
            size_bytes=(None if t.get("size_bytes") is None else int(t["size_bytes"])),
        )
        for t in payload.get("tracks", [])
    ]
    mix = Mix(
        id=mix_id,
        artist_id=artist_id,
        platform=Platform(payload["platform"]),
        platform_id=payload["platform_id"],
        title=payload["title"],
        url=payload["url"],
        duration_seconds=int(payload["duration_seconds"]),
        size_bytes=size_bytes,
        kind=kind,
        tracks=tracks,
        tags=tags,
        stars=stars,
        rejected=(
            True
            if mix_id in state.rejected_mix_ids
            else (existing.rejected if existing is not None else False)
        ),
        played=(
            True
            if mix_id in state.played_mix_ids
            else (existing.played if existing is not None else False)
        ),
        skipped=(
            True
            if mix_id in state.skipped_mix_ids
            else (existing.skipped if existing is not None else False)
        ),
        last_heard_at=(
            state.pending_last_heard.get(mix_id)
            if mix_id in state.pending_last_heard
            else (existing.last_heard_at if existing is not None else None)
        ),
    )
    state.add_mix(mix)


def _apply_intent_upserted(
    state: CatalogState, event: Event, payload: dict[str, Any]
) -> None:
    intent_id = UUID(payload["id"])
    meta_wins = _merge_beats(state, ("intent", str(intent_id)), event)
    existing = state.intents.get(intent_id)
    hours_map: dict[UUID, DeviceHours] = {
        dh.device_id: dh for dh in (existing.device_hours if existing else [])
    }
    hours_changed = False
    for raw in payload.get("device_hours") or []:
        device_id = UUID(raw["device_id"])
        if device_id in state.unpaired_device_ids:
            continue
        if not _merge_beats(
            state, ("intent_hours", str(intent_id), str(device_id)), event
        ):
            continue
        hours_map[device_id] = DeviceHours(
            device_id=device_id,
            budget_seconds=int(raw["budget_seconds"]),
            expires_at=(
                _as_naive_utc(datetime.fromisoformat(raw["expires_at"]))
                if raw.get("expires_at")
                else None
            ),
        )
        hours_changed = True
    for raw_cleared in payload.get("cleared_device_ids") or []:
        device_id = UUID(raw_cleared)
        if not _merge_beats(
            state, ("intent_hours", str(intent_id), str(device_id)), event
        ):
            continue
        if hours_map.pop(device_id, None) is not None:
            hours_changed = True
    for unpaired_id in list(hours_map):
        if unpaired_id in state.unpaired_device_ids:
            hours_map.pop(unpaired_id, None)
            hours_changed = True
    merged_hours = list(hours_map.values())
    if meta_wins:
        intent = _intent_from_payload(payload).model_copy(
            update={"device_hours": merged_hours}
        )
        state.upsert_intent(intent)
        _flush_pending_intent_projection(state, intent_id)
    elif existing is not None and hours_changed:
        state.upsert_intent(existing.model_copy(update={"device_hours": merged_hours}))


def _as_naive_utc(dt: datetime | None) -> datetime | None:
    """Normalize to naive UTC so compares match ``datetime.utcnow`` clocks."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


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


def _platforms_from_payload(payload: dict[str, Any]) -> list[Platform]:
    raw = payload.get("platforms")
    if raw is None:
        return default_intent_platforms()
    return [Platform(value) for value in raw]


def _intent_from_payload(payload: dict[str, Any]) -> Intent:
    dist = payload.get("distribution") or {}
    return Intent(
        id=UUID(payload["id"]),
        name=payload["name"],
        tags=list(payload.get("tags") or []),
        artist_ids=[UUID(artist_id) for artist_id in payload.get("artist_ids") or []],
        platforms=_platforms_from_payload(payload),
        distribution=_distribution_from_payload(dist),
        device_hours=[
            DeviceHours(
                device_id=UUID(dh["device_id"]),
                budget_seconds=int(dh["budget_seconds"]),
                expires_at=(
                    _as_naive_utc(datetime.fromisoformat(dh["expires_at"]))
                    if dh.get("expires_at")
                    else None
                ),
            )
            for dh in payload.get("device_hours") or []
        ],
        seed=int(payload["seed"]),
    )
