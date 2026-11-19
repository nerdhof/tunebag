"""Signed append-only event log (sync spine). Signing hooks land with pairing."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from tunebag.durable_store import DurableStore


class EventType(str, Enum):
    ARTIST_ADDED = "artist_added"
    ARTIST_DELETED = "artist_deleted"
    MIX_ADDED = "mix_added"
    MIX_TAGGED = "mix_tagged"
    MIX_TAG_ADDED = "mix_tag_added"
    MIX_TAG_REMOVED = "mix_tag_removed"
    MIX_RATED = "mix_rated"
    MIX_REJECTED = "mix_rejected"
    MIX_UNREJECTED = "mix_unrejected"
    INTENT_UPSERTED = "intent_upserted"
    INTENT_DELETED = "intent_deleted"
    SEQUENCE_BUILT = "sequence_built"
    ASSIGNMENT_SET = "assignment_set"
    ASSIGNMENT_CLEARED = "assignment_cleared"
    PLAYED = "played"
    SKIPPED = "skipped"
    PLAYHEAD = "playhead"
    LAST_HEARD = "last_heard"
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
    """Append-only Event log: in-memory list, or SQLite-backed without a full RAM copy."""

    def __init__(self, store: DurableStore | None = None) -> None:
        self._store = store
        self._events: list[Event] = []
        self._lock = threading.Lock()

    @property
    def store(self) -> DurableStore | None:
        return self._store

    def append(self, event: Event) -> Event:
        if self._store is not None:
            with self._lock:
                self._store.append_event(event)
            return event
        with self._lock:
            self._events.append(event)
        return event

    def since(self, after: datetime | None = None) -> list[Event]:
        events = self.all()
        if after is None:
            return events
        return [event for event in events if event.created_at > after]

    def all(self) -> list[Event]:
        """Materialize the full log (tests / in-process sync). Prefer iterators for HTTP."""
        if self._store is not None:
            with self._lock:
                return list(self._store.iter_events())
        with self._lock:
            return list(self._events)

    def is_empty(self) -> bool:
        if self._store is not None:
            return self._store.is_empty()
        with self._lock:
            return not self._events

    def iter_all(self) -> Iterator[Event]:
        if self._store is not None:
            yield from self._store.iter_events()
            return
        with self._lock:
            snapshot = list(self._events)
        yield from snapshot

    def iter_with_rowids(self) -> Iterator[tuple[int, Event]]:
        """Yield (rowid, event). In-memory mode uses 1-based list indexes as rowids."""
        if self._store is not None:
            yield from self._store.iter_events_with_rowids()
            return
        with self._lock:
            snapshot = list(self._events)
        yield from enumerate(snapshot, start=1)

    def iter_since_rowid(self, after_rowid: int) -> Iterator[tuple[int, Event]]:
        if self._store is not None:
            yield from self._store.iter_events_since_rowid(after_rowid)
            return
        for rowid, event in self.iter_with_rowids():
            if rowid > after_rowid:
                yield rowid, event

    def iter_after_cursors(self, cursors: dict[str, int]) -> Iterator[Event]:
        """Events where author is missing from cursors or ``seq > cursor``."""
        if self._store is not None:
            yield from self._store.iter_events_after_cursors(cursors)
            return
        for event in self.iter_all():
            key = str(event.device_id)
            if key in cursors and int(event.seq) <= int(cursors[key]):
                continue
            yield event

    def max_seq_by_device(self) -> dict[UUID, int]:
        if self._store is not None:
            return self._store.max_seq_by_device()
        out: dict[UUID, int] = {}
        for event in self.iter_all():
            current = out.get(event.device_id, 0)
            if int(event.seq) > current:
                out[event.device_id] = int(event.seq)
        return out

    def max_rowid(self) -> int:
        if self._store is not None:
            return self._store.max_rowid()
        with self._lock:
            return len(self._events)
