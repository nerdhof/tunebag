"""Canonical domain types for Tunebag.

See CONTEXT.md for vocabulary. Keep this module aligned with that glossary.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


def new_id() -> UUID:
    return uuid4()


class Platform(str, Enum):
    SOUNDCLOUD = "soundcloud"
    HEARTHIS = "hearthisat"
    BANDCAMP = "bandcamp"
    YOUTUBE = "youtube"
    OTHER = "other"


class Stars(int, Enum):
    ONE = 1
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5


class Artist(BaseModel):
    id: UUID = Field(default_factory=new_id)
    platform: Platform
    platform_id: str
    name: str
    url: str
    added_at: datetime = Field(default_factory=datetime.utcnow)


class Mix(BaseModel):
    """One audio file treated as a single listening item."""

    id: UUID = Field(default_factory=new_id)
    artist_id: UUID
    platform: Platform
    platform_id: str
    title: str
    url: str
    duration_seconds: int
    size_bytes: int | None = None
    tags: list[str] = Field(default_factory=list)
    stars: Stars | None = None
    rejected: bool = False
    played: bool = False
    last_heard_at: datetime | None = None
    added_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for tag in tags:
            cleaned = tag.strip().lower()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                out.append(cleaned)
        return out


class StarBucket(str, Enum):
    FIVE = "5"
    FOUR = "4"
    THREE = "3"
    TWO = "2"
    ONE = "1"
    UNRATED = "unrated"


class StarDistribution(BaseModel):
    """Draw probabilities for sequence building. Must sum to 1.0."""

    five: Annotated[float, Field(ge=0, le=1)] = 0.3
    four: Annotated[float, Field(ge=0, le=1)] = 0.2
    three: Annotated[float, Field(ge=0, le=1)] = 0.1
    two: Annotated[float, Field(ge=0, le=1)] = 0.05
    one: Annotated[float, Field(ge=0, le=1)] = 0.05
    unrated: Annotated[float, Field(ge=0, le=1)] = 0.3

    @model_validator(mode="after")
    def probabilities_sum_to_one(self) -> Self:
        total = (
            self.five
            + self.four
            + self.three
            + self.two
            + self.one
            + self.unrated
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"star distribution must sum to 1.0, got {total}")
        return self

    def as_map(self) -> dict[StarBucket, float]:
        return {
            StarBucket.FIVE: self.five,
            StarBucket.FOUR: self.four,
            StarBucket.THREE: self.three,
            StarBucket.TWO: self.two,
            StarBucket.ONE: self.one,
            StarBucket.UNRATED: self.unrated,
        }


class DeviceHours(BaseModel):
    device_id: UUID
    budget_seconds: int = Field(gt=0)
    expires_at: datetime | None = None


class Intent(BaseModel):
    """Shared plan: tag filter + star distribution. Devices attach hours/expiry."""

    id: UUID = Field(default_factory=new_id)
    name: str
    tags: list[str] = Field(default_factory=list)  # AND; empty = untagged / exploratory
    distribution: StarDistribution = Field(default_factory=StarDistribution)
    device_hours: list[DeviceHours] = Field(default_factory=list)
    seed: int
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        return Mix.normalize_tags(tags)

    @property
    def max_budget_seconds(self) -> int:
        if not self.device_hours:
            return 0
        return max(dh.budget_seconds for dh in self.device_hours)


class SequenceEntry(BaseModel):
    mix_id: UUID
    position: int
    bucket: StarBucket


class Sequence(BaseModel):
    """Seeded ordered list for one intent, length up to the largest device budget."""

    intent_id: UUID
    entries: list[SequenceEntry] = Field(default_factory=list)
    built_at: datetime = Field(default_factory=datetime.utcnow)


class Assignment(BaseModel):
    """Which device hours cover which prefix of the sequence."""

    intent_id: UUID
    device_id: UUID
    mix_ids: list[UUID]
    budget_seconds: int


class Device(BaseModel):
    id: UUID = Field(default_factory=new_id)
    name: str
    public_key_pem: str
    priority: int = 100  # lower = preferred fetcher; laptop default ahead of phone
    paired_at: datetime = Field(default_factory=datetime.utcnow)


class Playhead(BaseModel):
    mix_id: UUID
    device_id: UUID
    position_seconds: float
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RejectPending(BaseModel):
    """Local-only reject during the 20s undo window. Not synced until committed."""

    mix_id: UUID
    device_id: UUID
    created_at: datetime = Field(default_factory=datetime.utcnow)
    undo_until: datetime
