"""Catalog projection: pure Event → CatalogState + local File/folder effects.

DeviceAgent owns Event-log I/O and executes ``LocalEffects``. Merge rules match
CONTEXT.md (sticky Played/Skipped/Artist delete, LWW fields, hybrid Playhead).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from tunebag.domain import (
    Artist,
    Assignment,
    Device,
    DeviceHours,
    Intent,
    Mix,
    Platform,
    Playhead,
    Sequence,
    SequenceEntry,
    StarBucket,
    Stars,
)
from tunebag.event_payloads import decode_intent, decode_mix_added
from tunebag.events import Event, EventType

PLAYHEAD_NEAR_SECONDS = 120.0
# Bump when apply/merge shape or snapshot codec fields change.
PROJECTION_VERSION = 1

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
        # Winning Reject Event author time (for Soft window / API snapshots).
        self.rejected_at_by_mix: dict[UUID, datetime] = {}
        self.played_mix_ids: set[UUID] = set()
        self.skipped_mix_ids: set[UUID] = set()
        self.pending_tag_presence: dict[UUID, dict[str, bool]] = {}
        self.pending_stars: dict[UUID, Stars] = {}
        self.pending_last_heard: dict[UUID, datetime] = {}
        self.pending_sequences: dict[UUID, Sequence] = {}
        self.pending_assignments: dict[tuple[UUID, UUID], Assignment | None] = {}
        # Sticky until local re-pair; remote DEVICE_PAIRED cannot undo.
        self.unpaired_device_ids: set[UUID] = set()

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

    def tag_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for mix in self.mixes.values():
            for tag in mix.tags:
                counts[tag] = counts.get(tag, 0) + 1
        return counts

    def all_tags(self) -> list[str]:
        return sorted(self.tag_counts())

    def suggest_tags(self, prefix: str, limit: int = 6) -> list[str]:
        needle = prefix.strip().lower()
        counts = self.tag_counts()
        matches = [name for name in counts if name.startswith(needle)]
        matches.sort(key=lambda name: (-counts[name], name))
        return matches[:limit]

    def mixes_list(self) -> list[Mix]:
        return list(self.mixes.values())

    def clear_projection(self) -> None:
        """Drop projected Catalog + merge bookkeeping (keep data_dir)."""
        self.artists.clear()
        self.mixes.clear()
        self.intents.clear()
        self.sequences.clear()
        self.assignments.clear()
        self.devices.clear()
        self.playheads.clear()
        self.merge_wins.clear()
        self.deleted_artists.clear()
        self.rejected_mix_ids.clear()
        self.rejected_at_by_mix.clear()
        self.played_mix_ids.clear()
        self.skipped_mix_ids.clear()
        self.pending_tag_presence.clear()
        self.pending_stars.clear()
        self.pending_last_heard.clear()
        self.pending_sequences.clear()
        self.pending_assignments.clear()
        self.unpaired_device_ids.clear()


def dump_catalog_snapshot(state: CatalogState) -> bytes:
    """Serialize Catalog projection + merge bookkeeping as an opaque versioned blob."""

    def _dt(value: datetime | None) -> str | None:
        return None if value is None else value.isoformat()

    def _merge_win(win: MergeWin) -> list[Any]:
        created_at, device_id, seq, event_id = win
        return [created_at.isoformat(), str(device_id), seq, str(event_id)]

    payload: dict[str, Any] = {
        "projection_version": PROJECTION_VERSION,
        "local_device_id": None
        if state.local_device_id is None
        else str(state.local_device_id),
        "artists": {
            str(k): v.model_dump(mode="json") for k, v in state.artists.items()
        },
        "mixes": {str(k): v.model_dump(mode="json") for k, v in state.mixes.items()},
        "intents": {
            str(k): v.model_dump(mode="json") for k, v in state.intents.items()
        },
        "sequences": {
            str(k): v.model_dump(mode="json") for k, v in state.sequences.items()
        },
        "assignments": {
            f"{intent_id}/{device_id}": assignment.model_dump(mode="json")
            for (intent_id, device_id), assignment in state.assignments.items()
        },
        "devices": {
            str(k): v.model_dump(mode="json") for k, v in state.devices.items()
        },
        "playheads": {
            str(k): v.model_dump(mode="json") for k, v in state.playheads.items()
        },
        "merge_wins": {
            "\x1f".join(key): _merge_win(win) for key, win in state.merge_wins.items()
        },
        "deleted_artists": [str(x) for x in state.deleted_artists],
        "rejected_mix_ids": [str(x) for x in state.rejected_mix_ids],
        "rejected_at_by_mix": {
            str(k): _dt(v) for k, v in state.rejected_at_by_mix.items()
        },
        "played_mix_ids": [str(x) for x in state.played_mix_ids],
        "skipped_mix_ids": [str(x) for x in state.skipped_mix_ids],
        "pending_tag_presence": {
            str(mix_id): dict(tags)
            for mix_id, tags in state.pending_tag_presence.items()
        },
        "pending_stars": {
            str(k): int(v.value) for k, v in state.pending_stars.items()
        },
        "pending_last_heard": {
            str(k): _dt(v) for k, v in state.pending_last_heard.items()
        },
        "pending_sequences": {
            str(k): v.model_dump(mode="json") for k, v in state.pending_sequences.items()
        },
        "pending_assignments": {
            f"{intent_id}/{device_id}": (
                None if assignment is None else assignment.model_dump(mode="json")
            )
            for (intent_id, device_id), assignment in state.pending_assignments.items()
        },
        "unpaired_device_ids": [str(x) for x in state.unpaired_device_ids],
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def load_catalog_snapshot(state: CatalogState, blob: bytes) -> None:
    """Replace projected Catalog fields from a snapshot blob (fail-fast on bad data)."""
    raw = json.loads(blob.decode("utf-8"))
    if int(raw.get("projection_version", -1)) != PROJECTION_VERSION:
        raise ValueError("catalog snapshot projection_version mismatch")

    def _parse_dt(value: str | None) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(value)

    def _parse_merge_win(value: list[Any]) -> MergeWin:
        created_at, device_id, seq, event_id = value
        return (
            datetime.fromisoformat(created_at),
            UUID(device_id),
            int(seq),
            UUID(event_id),
        )

    def _pair_key(raw_key: str) -> tuple[UUID, UUID]:
        intent_id, device_id = raw_key.split("/", 1)
        return UUID(intent_id), UUID(device_id)

    state.clear_projection()
    local = raw.get("local_device_id")
    state.local_device_id = None if local is None else UUID(local)
    state.artists = {
        UUID(k): Artist.model_validate(v) for k, v in raw.get("artists", {}).items()
    }
    state.mixes = {
        UUID(k): Mix.model_validate(v) for k, v in raw.get("mixes", {}).items()
    }
    state.intents = {
        UUID(k): Intent.model_validate(v) for k, v in raw.get("intents", {}).items()
    }
    state.sequences = {
        UUID(k): Sequence.model_validate(v) for k, v in raw.get("sequences", {}).items()
    }
    state.assignments = {
        _pair_key(k): Assignment.model_validate(v)
        for k, v in raw.get("assignments", {}).items()
    }
    state.devices = {
        UUID(k): Device.model_validate(v) for k, v in raw.get("devices", {}).items()
    }
    state.playheads = {
        UUID(k): Playhead.model_validate(v) for k, v in raw.get("playheads", {}).items()
    }
    state.merge_wins = {
        tuple(k.split("\x1f")): _parse_merge_win(v)
        for k, v in raw.get("merge_wins", {}).items()
    }
    state.deleted_artists = {UUID(x) for x in raw.get("deleted_artists", [])}
    state.rejected_mix_ids = {UUID(x) for x in raw.get("rejected_mix_ids", [])}
    state.rejected_at_by_mix = {
        UUID(k): dt
        for k, v in raw.get("rejected_at_by_mix", {}).items()
        if (dt := _parse_dt(v)) is not None
    }
    state.played_mix_ids = {UUID(x) for x in raw.get("played_mix_ids", [])}
    state.skipped_mix_ids = {UUID(x) for x in raw.get("skipped_mix_ids", [])}
    state.pending_tag_presence = {
        UUID(mix_id): {str(tag): bool(present) for tag, present in tags.items()}
        for mix_id, tags in raw.get("pending_tag_presence", {}).items()
    }
    state.pending_stars = {
        UUID(k): Stars(int(v)) for k, v in raw.get("pending_stars", {}).items()
    }
    state.pending_last_heard = {
        UUID(k): dt
        for k, v in raw.get("pending_last_heard", {}).items()
        if (dt := _parse_dt(v)) is not None
    }
    state.pending_sequences = {
        UUID(k): Sequence.model_validate(v)
        for k, v in raw.get("pending_sequences", {}).items()
    }
    pending_assignments: dict[tuple[UUID, UUID], Assignment | None] = {}
    for key, value in raw.get("pending_assignments", {}).items():
        pair = _pair_key(key)
        pending_assignments[pair] = (
            None if value is None else Assignment.model_validate(value)
        )
    state.pending_assignments = pending_assignments
    state.unpaired_device_ids = {UUID(x) for x in raw.get("unpaired_device_ids", [])}


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
        _strip_deleted_artist_from_intents(state, event, artist_id, effects)
        return state, effects
    if event.type is EventType.MIX_ADDED:
        _apply_mix_added(state, payload)
        return state, effects
    if event.type is EventType.MIX_TAG_ADDED:
        mix_id = UUID(payload["mix_id"])
        tag = _normalize_tag(str(payload["tag"]))
        _set_mix_tag_presence(state, mix_id, tag, True, event)
        return state, effects
    if event.type is EventType.MIX_TAG_REMOVED:
        mix_id = UUID(payload["mix_id"])
        tag = _normalize_tag(str(payload["tag"]))
        _set_mix_tag_presence(state, mix_id, tag, False, event)
        return state, effects
    if event.type is EventType.MIX_TAGGED:
        mix_id = UUID(payload["mix_id"])
        if not _merge_beats(state, ("mix_tagged", str(mix_id)), event):
            return state, effects
        desired = Mix.normalize_tags(list(payload["tags"]))
        desired_set = set(desired)
        universe = _known_tags_for_mix(state, mix_id) | desired_set
        for tag in sorted(universe):
            _set_mix_tag_presence(state, mix_id, tag, tag in desired_set, event)
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
        state.rejected_at_by_mix[mix_id] = event.created_at
        mix = state.mixes.get(mix_id)
        if mix is not None:
            state.add_mix(
                mix.model_copy(
                    update={"rejected": True, "rejected_at": event.created_at}
                )
            )
        # File byte deletion waits for Soft → Hard (agent-local schedule).
        return state, effects
    if event.type is EventType.MIX_UNREJECTED:
        mix_id = UUID(payload["mix_id"])
        if not _merge_beats(state, ("reject", str(mix_id)), event):
            return state, effects
        state.rejected_mix_ids.discard(mix_id)
        state.rejected_at_by_mix.pop(mix_id, None)
        mix = state.mixes.get(mix_id)
        if mix is not None:
            state.add_mix(
                mix.model_copy(update={"rejected": False, "rejected_at": None})
            )
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


def _normalize_tag(tag: str) -> str:
    return tag.strip().lower()


def _known_tags_for_mix(state: CatalogState, mix_id: UUID) -> set[str]:
    known: set[str] = set()
    mix = state.mixes.get(mix_id)
    if mix is not None:
        known.update(mix.tags)
    pending = state.pending_tag_presence.get(mix_id)
    if pending is not None:
        known.update(pending.keys())
    return known


def _set_mix_tag_presence(
    state: CatalogState,
    mix_id: UUID,
    tag: str,
    present: bool,
    event: Event,
) -> None:
    if not tag:
        return
    if not _merge_beats(state, ("mix_tag", str(mix_id), tag), event):
        return
    bucket = state.pending_tag_presence.setdefault(mix_id, {})
    bucket[tag] = present
    mix = state.mixes.get(mix_id)
    if mix is None:
        return
    tag_set = set(mix.tags)
    if present:
        tag_set.add(tag)
    else:
        tag_set.discard(tag)
    # Sorted for deterministic Catalog regardless of Event apply order.
    state.add_mix(mix.model_copy(update={"tags": Mix.normalize_tags(sorted(tag_set))}))


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
    """Playhead merge: same-Device causal LWW; cross-Device hybrid conflict rule.

    Same Device (``existing.device_id == event.device_id``): later author time /
    seq wins — rewinds (Stop → 0, seek back) are accepted. The near-window
    higher-position rule applies only when two Devices conflict.
    """
    key: MergeKey = ("playhead", str(event.payload["mix_id"]))
    incoming = _merge_win_for(event)
    if existing is None:
        state.merge_wins[key] = incoming
        return True
    if existing.device_id == event.device_id:
        if event.created_at > existing.updated_at:
            state.merge_wins[key] = incoming
            return True
        if event.created_at < existing.updated_at:
            return False
        return _merge_beats(state, key, event)
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


def _strip_deleted_artist_from_intents(
    state: CatalogState,
    event: Event,
    artist_id: UUID,
    effects: LocalEffects,
) -> None:
    """Drop deleted artist from intent filters; remove artistless intents.

    When the last ``artist_ids`` entry is removed, delete the intent and advance
    the intent merge beat with this artist-delete event so an older
    ``INTENT_UPSERTED`` cannot resurrect it. Multi-artist intents keep the
    remaining ids (no merge-beat change).
    """
    for intent in list(state.intents.values()):
        if artist_id not in intent.artist_ids:
            continue
        remaining = [aid for aid in intent.artist_ids if aid != artist_id]
        if remaining:
            state.upsert_intent(intent.model_copy(update={"artist_ids": remaining}))
            continue
        _merge_beats(state, ("intent", str(intent.id)), event)
        state.delete_intent(intent.id)
        state.pending_sequences.pop(intent.id, None)
        for key in [k for k in state.pending_assignments if k[0] == intent.id]:
            del state.pending_assignments[key]
        effects.remove_intent_folders.append(intent.id)


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
    tls_fp = payload.get("tls_cert_fingerprint")
    tls_pem = payload.get("tls_cert_pem")
    if isinstance(tls_fp, str) and tls_fp:
        pinned_fp: str | None = tls_fp
    elif existing is not None:
        pinned_fp = existing.tls_cert_fingerprint
    else:
        pinned_fp = None
    if isinstance(tls_pem, str) and tls_pem:
        pinned_pem: str | None = tls_pem
    elif existing is not None:
        pinned_pem = existing.tls_cert_pem
    else:
        pinned_pem = None
    # Idempotent upsert by device id (and by public key when already trusted).
    state.add_device(
        Device(
            id=device_id if existing is None else existing.id,
            name=payload["name"],
            public_key_pem=public_key_pem,
            priority=int(payload.get("priority", 100)),
            paired_at=(existing.paired_at if existing is not None else now),
            tls_cert_fingerprint=pinned_fp,
            tls_cert_pem=pinned_pem,
        )
    )


def _revoke_peer_in_catalog(state: CatalogState, device_id: UUID) -> None:
    """Drop trust and hours/assignments for a Peer; Catalog rows stay.

    Unknown-author buffer clearing is CatalogJournal policy, not projection state.
    """
    state.unpaired_device_ids.add(device_id)
    state.remove_device(device_id)
    for intent in list(state.intents.values()):
        if any(dh.device_id == device_id for dh in intent.device_hours):
            remaining = [dh for dh in intent.device_hours if dh.device_id != device_id]
            state.upsert_intent(intent.model_copy(update={"device_hours": remaining}))
        state.clear_assignment(intent.id, device_id)
    for key in [k for k in state.pending_assignments if k[1] == device_id]:
        del state.pending_assignments[key]


def _apply_mix_added(state: CatalogState, payload: dict[str, Any]) -> None:
    decoded = decode_mix_added(payload)
    if decoded.artist_id in state.deleted_artists:
        return
    mix_id = decoded.id
    existing = state.mixes.get(mix_id)
    tags = list(existing.tags) if existing is not None else []
    stars = existing.stars if existing is not None else None
    if mix_id in state.pending_tag_presence:
        pending = state.pending_tag_presence[mix_id]
        tags = Mix.normalize_tags(sorted(t for t, present in pending.items() if present))
    if mix_id in state.pending_stars:
        stars = state.pending_stars[mix_id]
    mix = decoded.model_copy(
        update={
            "tags": tags,
            "stars": stars,
            "rejected": (
                True
                if mix_id in state.rejected_mix_ids
                else (existing.rejected if existing is not None else False)
            ),
            "rejected_at": (
                state.rejected_at_by_mix.get(mix_id)
                if mix_id in state.rejected_mix_ids
                else (
                    existing.rejected_at
                    if existing is not None and existing.rejected
                    else None
                )
            ),
            "played": (
                True
                if mix_id in state.played_mix_ids
                else (existing.played if existing is not None else False)
            ),
            "skipped": (
                True
                if mix_id in state.skipped_mix_ids
                else (existing.skipped if existing is not None else False)
            ),
            "last_heard_at": (
                state.pending_last_heard.get(mix_id)
                if mix_id in state.pending_last_heard
                else (existing.last_heard_at if existing is not None else None)
            ),
        }
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
        intent = decode_intent(payload).model_copy(
            update={"device_hours": merged_hours}
        )
        cleaned_artists = [
            artist_id
            for artist_id in intent.artist_ids
            if artist_id not in state.deleted_artists
        ]
        if cleaned_artists != list(intent.artist_ids):
            intent = intent.model_copy(update={"artist_ids": cleaned_artists})
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
