"""Bandcamp artist album listing and audio fetch."""

from __future__ import annotations

import json
import logging
import re
from html import unescape
from urllib.parse import urljoin, urlparse

import httpx

from tunebag.domain import Platform
from tunebag.source.artist_urls import bandcamp_normalize_artist_url
from tunebag.source.models import ArtistListing, Track, Upload, optional_size_bytes
from tunebag.ytdlp_fetch import AudioFetcher, ProgressCallback, fetch_audio_bytes

logger = logging.getLogger(__name__)


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
                size_bytes=optional_size_bytes(item),
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
