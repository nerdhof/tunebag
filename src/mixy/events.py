"""Signed append-only event log (sync spine). Signing hooks land with pairing."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventType(str, Enum):
    ARTIST_ADDED = "artist_added"
    MIX_ADDED = "mix_added"
    MIX_TAGGED = "mix_tagged"
    MIX_RATED = "mix_rated"
    MIX_REJECTED = "mix_rejected"
    INTENT_UPSERTED = "intent_upserted"
    INTENT_DELETED = "intent_deleted"
    SEQUENCE_BUILT = "sequence_built"
    ASSIGNMENT_SET = "assignment_set"
    PLAYED = "played"
    PLAYHEAD = "playhead"
    DEVICE_PAIRED = "device_paired"


class Event(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: EventType
    device_id: UUID
    created_at: datetime = Field(default_factory=datetime.utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)
    signature: str | None = None  # set when device keys are wired


class EventLog:
    def __init__(self) -> None:
        self._events: list[Event] = []

    def append(self, event: Event) -> Event:
        self._events.append(event)
        return event

    def since(self, after: datetime | None = None) -> list[Event]:
        if after is None:
            return list(self._events)
        return [event for event in self._events if event.created_at > after]

    def all(self) -> list[Event]:
        return list(self._events)
