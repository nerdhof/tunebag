"""Signed append-only event log (sync spine). Signing hooks land with pairing."""

from __future__ import annotations

import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, TextIO
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventType(str, Enum):
    ARTIST_ADDED = "artist_added"
    ARTIST_DELETED = "artist_deleted"
    MIX_ADDED = "mix_added"
    MIX_TAGGED = "mix_tagged"
    MIX_RATED = "mix_rated"
    MIX_REJECTED = "mix_rejected"
    MIX_UNREJECTED = "mix_unrejected"
    INTENT_UPSERTED = "intent_upserted"
    INTENT_DELETED = "intent_deleted"
    SEQUENCE_BUILT = "sequence_built"
    ASSIGNMENT_SET = "assignment_set"
    ASSIGNMENT_CLEARED = "assignment_cleared"
    PLAYED = "played"
    PLAYHEAD = "playhead"
    DEVICE_PAIRED = "device_paired"
    DEVICE_UNPAIRED = "device_unpaired"


class Event(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: EventType
    device_id: UUID
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Per-author monotonic counter for last-by-(device_id, seq) merge (signed).
    seq: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)
    signature: str | None = None  # set when device keys are wired


class EventLog:
    """In-memory event list; optionally durable as append-only JSONL."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._events: list[Event] = []
        self._lock = threading.Lock()
        self._file: TextIO | None = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file():
                for line in path.read_text().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    self._events.append(Event.model_validate_json(line))
            self._file = path.open("a", encoding="utf-8")

    def append(self, event: Event) -> Event:
        with self._lock:
            self._events.append(event)
            if self._file is not None:
                self._file.write(event.model_dump_json() + "\n")
                self._file.flush()
        return event

    def since(self, after: datetime | None = None) -> list[Event]:
        with self._lock:
            if after is None:
                return list(self._events)
            return [event for event in self._events if event.created_at > after]

    def all(self) -> list[Event]:
        with self._lock:
            return list(self._events)
