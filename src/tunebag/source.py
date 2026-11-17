"""Platform sources: list own uploads and fetch audio bytes.

Agent tests inject FakeSource. CLI/web use CompositeSource
(SoundCloud + hearthis + Bandcamp).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from html import unescape
from typing import Protocol
from urllib.parse import urljoin, urlparse

import httpx

from tunebag.domain import Platform
from tunebag.ytdlp_fetch import AudioFetcher, ProgressCallback, fetch_audio_bytes

logger = logging.getLogger(__name__)

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
    tracks: tuple[Track, ...] = ()


@dataclass(frozen=True)
class ArtistListing:
    platform: Platform
    platform_id: str
    name: str
    url: str
    uploads: list[Upload]


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


class HearthisSource:
    """List own uploads via the public hearthis.at API v2."""

    API = "https://api-v2.hearthis.at"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        audio_fetcher: AudioFetcher | None = None,
    ) -> None:
        self._client = client
        self._audio_fetcher = audio_fetcher

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=30.0, follow_redirects=True)
        return self._client

    def list_uploads(self, artist_url: str) -> ArtistListing:
        username = _hearthis_username(artist_url)
        profile_url = f"{self.API}/{username}/"
        user = self._http().get(profile_url)
        user.raise_for_status()
        user_data = user.json()
        platform_id = str(user_data.get("id") or username)
        name = str(user_data.get("username") or user_data.get("permalink") or username)
        canonical = str(user_data.get("permalink_url") or f"https://hearthis.at/{username}/")

        uploads: list[Upload] = []
        page = 1
        while True:
            response = self._http().get(
                f"{self.API}/{username}/",
                params={"type": "tracks", "page": page, "count": 20},
            )
            response.raise_for_status()
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                break
            for item in batch:
                upload = _hearthis_upload(item, owner_id=platform_id, owner_permalink=username)
                if upload is not None:
                    uploads.append(upload)
            if len(batch) < 20:
                break
            page += 1

        return ArtistListing(
            platform=Platform.HEARTHIS,
            platform_id=platform_id,
            name=name,
            url=canonical.rstrip("/") + "/",
            uploads=uploads,
        )

    def fetch_bytes(
        self,
        source_url: str,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> bytes:
        return fetch_audio_bytes(
            source_url,
            fetcher=self._audio_fetcher,
            on_progress=on_progress,
        )


class SoundCloudSource:
    """List own uploads via SoundCloud API (client_id from env or page resolve)."""

    API = "https://api-v2.soundcloud.com"

    def __init__(
        self,
        *,
        client_id: str | None = None,
        client: httpx.Client | None = None,
        audio_fetcher: AudioFetcher | None = None,
    ) -> None:
        self._client_id = client_id or os.environ.get("MIXY_SOUNDCLOUD_CLIENT_ID")
        self._client = client
        self._audio_fetcher = audio_fetcher

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=30.0, follow_redirects=True)
        return self._client

    def _ensure_client_id(self) -> str:
        if self._client_id:
            return self._client_id
        # SoundCloud embeds a client_id in its web assets; resolve for demo use.
        home = self._http().get("https://soundcloud.com")
        home.raise_for_status()
        script_urls = re.findall(
            r'src="(https://[^"]+/assets/[^"]+\.js)"',
            home.text,
        )
        for script_url in script_urls[-5:]:
            script = self._http().get(script_url)
            if script.status_code != 200:
                continue
            match = re.search(r'client_id\s*:\s*"([a-zA-Z0-9]{32})"', script.text)
            if not match:
                match = re.search(r'client_id=([a-zA-Z0-9]{32})', script.text)
            if match:
                self._client_id = match.group(1)
                return self._client_id
        raise ValueError(
            "SoundCloud client_id not found; set MIXY_SOUNDCLOUD_CLIENT_ID"
        )

    def list_uploads(self, artist_url: str) -> ArtistListing:
        client_id = self._ensure_client_id()
        resolved = self._http().get(
            f"{self.API}/resolve",
            params={"url": artist_url, "client_id": client_id},
        )
        resolved.raise_for_status()
        user = resolved.json()
        if user.get("kind") != "user" and "username" not in user:
            raise ValueError(f"SoundCloud URL is not a user profile: {artist_url}")
        user_id = str(user["id"])
        name = str(user.get("username") or user.get("permalink") or user_id)
        canonical = str(user.get("permalink_url") or artist_url)

        uploads: list[Upload] = []
        next_href: str | None = (
            f"{self.API}/users/{user_id}/tracks"
            f"?client_id={client_id}&limit=50&linked_partitioning=1"
        )
        while next_href:
            response = self._http().get(next_href)
            response.raise_for_status()
            payload = response.json()
            collection = payload.get("collection", payload if isinstance(payload, list) else [])
            for item in collection:
                # Own uploads endpoint; skip repost wrappers if present.
                if item.get("type") == "track-repost":
                    continue
                track = item.get("track", item)
                if track.get("user_id") is not None and str(track["user_id"]) != user_id:
                    continue
                upload = _soundcloud_upload(track)
                if upload is not None:
                    uploads.append(upload)
            next_href = payload.get("next_href")
            if next_href and "client_id=" not in next_href:
                sep = "&" if "?" in next_href else "?"
                next_href = f"{next_href}{sep}client_id={client_id}"

        return ArtistListing(
            platform=Platform.SOUNDCLOUD,
            platform_id=user_id,
            name=name,
            url=canonical,
            uploads=uploads,
        )

    def fetch_bytes(
        self,
        source_url: str,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> bytes:
        return fetch_audio_bytes(
            source_url,
            fetcher=self._audio_fetcher,
            on_progress=on_progress,
        )


class BandcampSource:
    """List full albums from a Bandcamp artist page; fetch free/streamable audio."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        audio_fetcher: AudioFetcher | None = None,
    ) -> None:
        self._client = client
        self._audio_fetcher = audio_fetcher

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=30.0, follow_redirects=True)
        return self._client

    def list_uploads(self, artist_url: str) -> ArtistListing:
        music_url = _bandcamp_artist_music_url(artist_url)
        response = self._http().get(music_url)
        response.raise_for_status()
        band = _bandcamp_parse_data_attr(response.text, "data-band")
        if not isinstance(band, dict):
            raise ValueError(f"Bandcamp artist page missing data-band: {music_url}")
        platform_id = str(band.get("id") or "")
        name = str(band.get("name") or urlparse(music_url).netloc.split(".")[0])
        if not platform_id:
            raise ValueError(f"Bandcamp artist page missing band id: {music_url}")

        base = f"{urlparse(music_url).scheme}://{urlparse(music_url).netloc}"
        album_paths = _bandcamp_album_paths(response.text)
        uploads: list[Upload] = []
        for path in album_paths:
            album_url = urljoin(base + "/", path.lstrip("/"))
            try:
                upload = self._list_album(album_url)
            except Exception as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                logger.warning("bandcamp album skipped %s: %s", album_url, exc)
                continue
            if upload is not None:
                uploads.append(upload)

        return ArtistListing(
            platform=Platform.BANDCAMP,
            platform_id=platform_id,
            name=name,
            url=music_url,
            uploads=uploads,
        )

    def _list_album(self, album_url: str) -> Upload | None:
        response = self._http().get(album_url)
        response.raise_for_status()
        tralbum = _bandcamp_parse_data_attr(response.text, "data-tralbum")
        if not isinstance(tralbum, dict):
            return None
        return _bandcamp_upload_from_tralbum(tralbum, album_url=album_url)

    def fetch_bytes(
        self,
        source_url: str,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> bytes:
        return fetch_audio_bytes(
            source_url,
            fetcher=self._audio_fetcher,
            on_progress=on_progress,
        )


class CompositeSource:
    """Dispatch list_uploads / fetch_bytes by artist or media URL host."""

    def __init__(
        self,
        *,
        soundcloud: Source | None = None,
        hearthis: Source | None = None,
        bandcamp: Source | None = None,
    ) -> None:
        self._soundcloud: Source = soundcloud or SoundCloudSource()
        self._hearthis: Source = hearthis or HearthisSource()
        self._bandcamp: Source = bandcamp or BandcampSource()

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
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if "soundcloud.com" in host:
            return self._soundcloud
        if "hearthis.at" in host:
            return self._hearthis
        if "bandcamp.com" in host:
            return self._bandcamp
        raise ValueError(
            f"unsupported artist URL host {host!r}; "
            "use soundcloud.com, hearthis.at, or *.bandcamp.com"
        )


def default_source() -> CompositeSource:
    return CompositeSource()


def _hearthis_username(artist_url: str) -> str:
    path = urlparse(artist_url).path.strip("/")
    if not path:
        raise ValueError(f"hearthis URL missing username: {artist_url}")
    return path.split("/")[0]


def _hearthis_upload(
    item: dict,
    *,
    owner_id: str,
    owner_permalink: str,
) -> Upload | None:
    user = item.get("user") or {}
    user_id = str(user.get("id") or "")
    user_permalink = str(user.get("permalink") or user.get("username") or "")
    if user_id and user_id != owner_id:
        return None
    if user_permalink and user_permalink.lower() != owner_permalink.lower():
        return None
    track_id = item.get("id")
    title = item.get("title")
    permalink = item.get("permalink_url") or item.get("uri")
    if track_id is None or not title or not permalink:
        return None
    raw_duration = item.get("duration")
    if raw_duration is None:
        return None
    duration_seconds = int(raw_duration)
    # API usually returns seconds; values that huge are milliseconds.
    if duration_seconds >= 100_000:
        duration_seconds //= 1000
    return Upload(
        platform=Platform.HEARTHIS,
        platform_id=str(track_id),
        title=str(title),
        url=str(permalink),
        duration_seconds=duration_seconds,
        size_bytes=_optional_size_bytes(item),
    )


def _soundcloud_upload(track: dict) -> Upload | None:
    track_id = track.get("id")
    title = track.get("title")
    permalink = track.get("permalink_url")
    duration_ms = track.get("duration")
    if track_id is None or not title or not permalink or duration_ms is None:
        return None
    return Upload(
        platform=Platform.SOUNDCLOUD,
        platform_id=str(track_id),
        title=str(title),
        url=str(permalink),
        duration_seconds=int(duration_ms) // 1000,
        size_bytes=_optional_size_bytes(track),
    )


def _optional_size_bytes(raw: dict) -> int | None:
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


def bandcamp_normalize_artist_url(url: str) -> str | None:
    """Canonical `/music` URL for artist root or `/music`; else None."""
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    if not host.endswith(".bandcamp.com") or host == "bandcamp.com":
        return None
    path = (parsed.path or "").rstrip("/").lower()
    if path not in ("", "/music"):
        return None
    scheme = parsed.scheme or "https"
    return f"{scheme}://{host}/music"


def _bandcamp_artist_music_url(artist_url: str) -> str:
    """Normalize artist root or /music to the canonical /music URL.

    Album and track page URLs are rejected with an actionable error.
    """
    parsed = urlparse(artist_url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    if "bandcamp.com" not in host:
        raise ValueError(f"not a Bandcamp URL: {artist_url}")
    if host == "bandcamp.com":
        raise ValueError(
            "Bandcamp artist URL needs an artist subdomain "
            f"(https://<artist>.bandcamp.com/music); got {artist_url}"
        )
    path_lower = (parsed.path or "/").lower()
    if "/album/" in path_lower:
        raise ValueError(
            "Bandcamp album URLs are not supported; "
            "add the artist /music page "
            f"(https://{host}/music) instead of {artist_url}"
        )
    if "/track/" in path_lower:
        raise ValueError(
            "Bandcamp track URLs are not supported; "
            "add the artist /music page "
            f"(https://{host}/music) instead of {artist_url}"
        )
    canonical = bandcamp_normalize_artist_url(artist_url)
    if canonical is not None:
        return canonical
    scheme = parsed.scheme or "https"
    return f"{scheme}://{host}/music"


def _bandcamp_parse_data_attr(html: str, attr: str) -> object | None:
    match = re.search(rf'{attr}="([^"]*)"', html)
    if not match:
        return None
    try:
        return json.loads(unescape(match.group(1)))
    except json.JSONDecodeError:
        return None


def _bandcamp_album_paths(html: str) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    for path in re.findall(r'href="(/album/[^"?#]+)"', html):
        if path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def _bandcamp_upload_from_tralbum(
    tralbum: dict,
    *,
    album_url: str,
) -> Upload | None:
    current = tralbum.get("current") or {}
    album_id = tralbum.get("id")
    if album_id is None:
        album_id = current.get("id")
    title = current.get("title")
    if album_id is None or not title:
        return None

    raw_tracks = tralbum.get("trackinfo") or []
    if not isinstance(raw_tracks, list) or not raw_tracks:
        return None
    if not _bandcamp_is_free_downloadable(tralbum):
        return None

    # Free/downloadable only, and every track must expose a stream file so
    # origin fetch can proceed without purchase/login. Partial discs skipped.
    tracks: list[Track] = []
    parsed = urlparse(album_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    for item in raw_tracks:
        if not isinstance(item, dict):
            return None
        file_info = item.get("file")
        if not isinstance(file_info, dict) or not file_info:
            return None
        track_id = item.get("track_id")
        if track_id is None:
            track_id = item.get("id")
        track_title = item.get("title")
        duration = item.get("duration")
        title_link = str(item.get("title_link") or "")
        if track_id is None or not track_title or duration is None or not title_link:
            return None
        if title_link.startswith("http"):
            track_url = title_link
        else:
            track_url = urljoin(base + "/", title_link.lstrip("/"))
        tracks.append(
            Track(
                platform_id=str(track_id),
                title=str(track_title),
                url=track_url,
                duration_seconds=int(float(duration)),
                size_bytes=_optional_size_bytes(item),
            )
        )

    duration_seconds = sum(t.duration_seconds for t in tracks)
    size_parts = [t.size_bytes for t in tracks if t.size_bytes is not None]
    size_bytes = sum(size_parts) if len(size_parts) == len(tracks) else None
    canonical = str(tralbum.get("url") or album_url).split("?")[0]
    return Upload(
        platform=Platform.BANDCAMP,
        platform_id=str(album_id),
        title=str(title),
        url=canonical.rstrip("/") if canonical.endswith("/") else canonical,
        duration_seconds=duration_seconds,
        size_bytes=size_bytes,
        tracks=tuple(tracks),
    )


def _bandcamp_is_free_downloadable(tralbum: dict) -> bool:
    """True when the album is free to download or name-your-price at $0."""
    if tralbum.get("freeDownloadPage"):
        return True
    current = tralbum.get("current") or {}
    price = current.get("minimum_price")
    if price is None:
        return False
    try:
        return float(price) == 0.0
    except (TypeError, ValueError):
        return False
