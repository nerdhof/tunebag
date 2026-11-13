"""In-memory catalog store. Persistence and sync log land next."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from mixy.domain import (
    Artist,
    Assignment,
    Device,
    Intent,
    Mix,
    Playhead,
    Sequence,
)


class Catalog:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or Path.home() / ".mixy"
        self.artists: dict[UUID, Artist] = {}
        self.mixes: dict[UUID, Mix] = {}
        self.intents: dict[UUID, Intent] = {}
        self.sequences: dict[UUID, Sequence] = {}
        self.assignments: dict[tuple[UUID, UUID], Assignment] = {}
        self.devices: dict[UUID, Device] = {}
        self.playheads: dict[UUID, Playhead] = {}  # keyed by mix_id; latest wins
        self.local_device_id: UUID | None = None

    def add_artist(self, artist: Artist) -> Artist:
        self.artists[artist.id] = artist
        return artist

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

    def add_device(self, device: Device) -> Device:
        self.devices[device.id] = device
        return device

    def set_playhead(self, playhead: Playhead) -> Playhead:
        existing = self.playheads.get(playhead.mix_id)
        if existing is None or playhead.updated_at >= existing.updated_at:
            self.playheads[playhead.mix_id] = playhead
        return self.playheads[playhead.mix_id]

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
