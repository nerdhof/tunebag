"""Platform sources: list own uploads and fetch audio bytes.

Agent tests inject FakeSource. CLI/web use CompositeSource
(SoundCloud + hearthis + Bandcamp + YouTube).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlparse

from tunebag.domain import Platform
from tunebag.source.artist_urls import (
    bandcamp_normalize_artist_url,
    platform_for_url,
    youtube_normalize_artist_url,
)
from tunebag.source.bandcamp import BandcampSource
from tunebag.source.hearthis import HearthisSource
from tunebag.source.models import (
    DEFAULT_MIN_DURATION_SECONDS,
    ArtistListing,
    Track,
    Upload,
    release_from_upload,
)
from tunebag.source.soundcloud import SoundCloudSource
from tunebag.source.youtube import YouTubeSource
from tunebag.ytdlp_fetch import ProgressCallback

__all__ = [
    "DEFAULT_MIN_DURATION_SECONDS",
    "ArtistListing",
    "BandcampSource",
    "CompositeSource",
    "FakeSource",
    "HearthisSource",
    "SoundCloudSource",
    "Source",
    "Track",
    "Upload",
    "YouTubeSource",
    "bandcamp_normalize_artist_url",
    "default_source",
    "platform_for_url",
    "release_from_upload",
    "youtube_normalize_artist_url",
]


class Source(Protocol):
    def list_uploads(self, artist_url: str) -> ArtistListing: ...

    def fetch_bytes(
        self,
        source_url: str,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> bytes: ...


@dataclass
class FakeSource:
    """In-memory source for agent tests. Tracks fetch_bytes calls."""

    listings: dict[str, ArtistListing] = field(default_factory=dict)
    bytes_by_url: dict[str, bytes] = field(default_factory=dict)
    fetch_calls: list[str] = field(default_factory=list)

    def add_listing(self, artist_url: str, listing: ArtistListing) -> None:
        self.listings[artist_url.rstrip("/")] = listing

    def list_uploads(self, artist_url: str) -> ArtistListing:
        key = artist_url.rstrip("/")
        if key not in self.listings:
            raise ValueError(f"unknown artist URL: {artist_url}")
        return self.listings[key]

    def fetch_bytes(
        self,
        source_url: str,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> bytes:
        self.fetch_calls.append(source_url)
        if source_url not in self.bytes_by_url:
            raise ValueError(f"no bytes for {source_url}")
        data = self.bytes_by_url[source_url]
        if on_progress is not None:
            on_progress(len(data), len(data))
        return data


class CompositeSource:
    """Dispatch list_uploads / fetch_bytes by artist or media URL host."""

    def __init__(
        self,
        *,
        soundcloud: Source | None = None,
        hearthis: Source | None = None,
        bandcamp: Source | None = None,
        youtube: Source | None = None,
    ) -> None:
        self._soundcloud: Source = soundcloud or SoundCloudSource()
        self._hearthis: Source = hearthis or HearthisSource()
        self._bandcamp: Source = bandcamp or BandcampSource()
        self._youtube: Source = youtube or YouTubeSource()

    def list_uploads(self, artist_url: str) -> ArtistListing:
        return self._for_url(artist_url).list_uploads(artist_url)

    def fetch_bytes(
        self,
        source_url: str,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> bytes:
        return self._for_url(source_url).fetch_bytes(
            source_url,
            on_progress=on_progress,
        )

    def _for_url(self, url: str) -> Source:
        platform = platform_for_url(url)
        if platform is Platform.SOUNDCLOUD:
            return self._soundcloud
        if platform is Platform.HEARTHIS:
            return self._hearthis
        if platform is Platform.BANDCAMP:
            return self._bandcamp
        if platform is Platform.YOUTUBE:
            return self._youtube
        host = urlparse(url).netloc.lower().removeprefix("www.")
        raise ValueError(
            f"unsupported artist URL host {host!r}; "
            "use soundcloud.com, hearthis.at, *.bandcamp.com, "
            "youtube.com, or music.youtube.com"
        )


def default_source() -> CompositeSource:
    return CompositeSource()
