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


class ReleaseKind(str, Enum):
    """Discriminant for a Catalog Release. Wire/API may still say mix."""

    MIX = "mix"
    ALBUM = "album"


class Artist(BaseModel):
    id: UUID = Field(default_factory=new_id)
    platform: Platform
    platform_id: str
    name: str
    url: str
    added_at: datetime = Field(default_factory=datetime.utcnow)


class AlbumTrack(BaseModel):
    """Ordered track metadata on an Album Release (Catalog only; no bytes)."""

    platform_id: str
    title: str
    url: str
    duration_seconds: int
    size_bytes: int | None = None


class Mix(BaseModel):
    """A Catalog Release (Mix or Album). Wire/API may still say mix."""

    id: UUID = Field(default_factory=new_id)
    artist_id: UUID
    platform: Platform
    platform_id: str
    title: str
    url: str
    duration_seconds: int
    size_bytes: int | None = None
    cover_url: str | None = None
    kind: ReleaseKind = ReleaseKind.MIX
    tracks: list[AlbumTrack] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    stars: Stars | None = None
    rejected: bool = False
    # Author time of the winning Reject Event; None when not Rejected.
    # Soft vs Hard UI visibility and deferred File delete use this + 5 minutes.
    rejected_at: datetime | None = None
    played: bool = False
    skipped: bool = False
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


DEFAULT_INTENT_PLATFORMS: tuple[Platform, ...] = (
    Platform.SOUNDCLOUD,
    Platform.HEARTHIS,
    Platform.BANDCAMP,
    Platform.YOUTUBE,
)


def default_intent_platforms() -> list[Platform]:
    return list(DEFAULT_INTENT_PLATFORMS)


class Intent(BaseModel):
    """Shared plan: tag + artist + platform filter + star distribution. Devices attach hours/expiry."""

    id: UUID = Field(default_factory=new_id)
    name: str
    tags: list[str] = Field(default_factory=list)  # AND; empty+no artists = untagged only
    artist_ids: list[UUID] = Field(default_factory=list)  # OR; empty = no artist filter
    platforms: list[Platform] = Field(default_factory=default_intent_platforms)
    distribution: StarDistribution = Field(default_factory=StarDistribution)
    device_hours: list[DeviceHours] = Field(default_factory=list)
    seed: int
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        return Mix.normalize_tags(tags)

    @field_validator("platforms")
    @classmethod
    def require_platforms(cls, platforms: list[Platform]) -> list[Platform]:
        if not platforms:
            raise ValueError("platforms must include at least one source")
        # Preserve order, drop duplicates.
        seen: set[Platform] = set()
        out: list[Platform] = []
        for platform in platforms:
            if platform not in seen:
                seen.add(platform)
                out.append(platform)
        return out

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


class SkipPending(BaseModel):
    """Local-only skip during the 5 min delay. Not synced until committed."""

    mix_id: UUID
    device_id: UUID
    created_at: datetime = Field(default_factory=datetime.utcnow)
    effective_at: datetime
