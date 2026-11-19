"""Source listing DTOs and Upload → Catalog Release mapping."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from tunebag.domain import AlbumTrack, Mix, Platform, ReleaseKind

DEFAULT_MIN_DURATION_SECONDS = 20 * 60


@dataclass(frozen=True)
class Track:
    """One ordered track on an album-shaped upload listing."""

    platform_id: str
    title: str
    url: str
    duration_seconds: int
    size_bytes: int | None = None


@dataclass(frozen=True)
class Upload:
    platform: Platform
    platform_id: str
    title: str
    url: str
    duration_seconds: int
    size_bytes: int | None = None
    cover_url: str | None = None
    tracks: tuple[Track, ...] = ()


@dataclass(frozen=True)
class ArtistListing:
    platform: Platform
    platform_id: str
    name: str
    url: str
    uploads: list[Upload]


def release_from_upload(
    artist_id: UUID,
    upload: Upload,
    min_duration_seconds: int,
) -> Mix | None:
    """Build a Catalog Release from a source upload, or None if filtered out."""
    if upload.tracks:
        if len(upload.tracks) < 2:
            return None
        duration_seconds = sum(t.duration_seconds for t in upload.tracks)
        if duration_seconds < min_duration_seconds:
            return None
        sizes = [t.size_bytes for t in upload.tracks]
        size_bytes = sum(sizes) if all(s is not None for s in sizes) else None
        return Mix(
            artist_id=artist_id,
            platform=upload.platform,
            platform_id=upload.platform_id,
            title=upload.title,
            url=upload.url,
            duration_seconds=duration_seconds,
            size_bytes=size_bytes,
            cover_url=upload.cover_url,
            kind=ReleaseKind.ALBUM,
            tracks=[
                AlbumTrack(
                    platform_id=t.platform_id,
                    title=t.title,
                    url=t.url,
                    duration_seconds=t.duration_seconds,
                    size_bytes=t.size_bytes,
                )
                for t in upload.tracks
            ],
        )
    if upload.duration_seconds < min_duration_seconds:
        return None
    return Mix(
        artist_id=artist_id,
        platform=upload.platform,
        platform_id=upload.platform_id,
        title=upload.title,
        url=upload.url,
        duration_seconds=upload.duration_seconds,
        size_bytes=upload.size_bytes,
        cover_url=upload.cover_url,
        kind=ReleaseKind.MIX,
    )


def optional_size_bytes(raw: dict) -> int | None:
    for key in ("original_content_size", "filesize", "file_size", "size"):
        value = raw.get(key)
        if value is None:
            continue
        try:
            size = int(value)
        except (TypeError, ValueError):
            continue
        if size > 0:
            return size
    return None
