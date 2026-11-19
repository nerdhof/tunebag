"""YouTube / YouTube Music album listing and audio fetch."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from tunebag.domain import Platform
from tunebag.source.artist_urls import (
    youtube_artist_releases_url,
    youtube_channel_id_from_url,
    youtube_channel_path,
)
from tunebag.source.models import ArtistListing, Track, Upload
from tunebag.ytdlp_fetch import (
    AudioFetcher,
    ProgressCallback,
    YtdlpCookies,
    apply_ytdlp_cookies,
    fetch_audio_bytes,
    youtube_anonymous_blocked_error,
    youtube_auth_challenge,
)

logger = logging.getLogger(__name__)

YoutubeExtractor = Callable[[str], dict[str, Any]]
YoutubeMusicBrowse = Callable[[str], dict[str, Any]]

_OLAK_ID_RE = re.compile(r"^OLAK[0-9A-Za-z_-]+$")
_OLAK_ID_FIND_RE = re.compile(r"OLAK[0-9A-Za-z_-]+")
# Public WEB_REMIX key used by YouTube Music web (same as ytmusicapi).
_YTM_API_KEY = "AIzaSyC9XL3ZjWTdXmuXJs7zMwGVxWQ70Q5v-mM"
_YTM_CONTEXT: dict[str, Any] = {
    "client": {
        "clientName": "WEB_REMIX",
        "clientVersion": "1.20241118.01.00",
        "hl": "en",
        "gl": "US",
    }
}


class YouTubeSource:
    """List Album Releases from a YouTube channel's releases tab (OLAK playlists).

    Topic / Music-only channels without a releases tab fall back to YouTube Music
    InnerTube browse for the same OLAK album playlists.
    """

    def __init__(
        self,
        *,
        extract_info: YoutubeExtractor | None = None,
        browse_music_artist: YoutubeMusicBrowse | None = None,
        audio_fetcher: AudioFetcher | None = None,
        cookies: YtdlpCookies | None = None,
    ) -> None:
        self._extract_info = extract_info
        self._browse_music_artist = browse_music_artist
        self._audio_fetcher = audio_fetcher
        self._cookies = cookies

    def list_uploads(self, artist_url: str) -> ArtistListing:
        releases_url = youtube_artist_releases_url(artist_url)
        try:
            info = self._extract(releases_url)
        except Exception as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if not _youtube_missing_releases_tab(exc):
                raise
            return self._list_uploads_from_music_browse(
                artist_url,
                releases_url=releases_url,
            )
        channel_id = _youtube_channel_id(info)
        if not channel_id:
            raise ValueError(f"YouTube releases page missing channel id: {releases_url}")
        name = str(
            info.get("channel")
            or info.get("uploader")
            or info.get("title")
            or channel_id
        )
        olak_ids: list[str] = []
        for entry in info.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            olak_id = _youtube_olak_id(entry)
            if olak_id is not None:
                olak_ids.append(olak_id)
        return self._listing_from_olak_ids(
            olak_ids,
            channel_id=channel_id,
            name=name,
            releases_url=releases_url,
        )

    def _list_uploads_from_music_browse(
        self,
        artist_url: str,
        *,
        releases_url: str,
    ) -> ArtistListing:
        channel_id = youtube_channel_id_from_url(artist_url)
        if not channel_id:
            channel_id = self._resolve_channel_id(artist_url)
        if not channel_id:
            raise ValueError(
                "YouTube channel has no releases tab and channel id could not be "
                f"resolved for Music browse fallback: {artist_url}"
            )
        browse = self._browse_music(channel_id)
        name = _youtube_music_artist_name(browse) or channel_id
        olak_ids = _youtube_music_olak_ids(browse)
        return self._listing_from_olak_ids(
            olak_ids,
            channel_id=channel_id,
            name=name,
            releases_url=releases_url,
        )

    def _listing_from_olak_ids(
        self,
        olak_ids: list[str],
        *,
        channel_id: str,
        name: str,
        releases_url: str,
    ) -> ArtistListing:
        uploads: list[Upload] = []
        seen: set[str] = set()
        for olak_id in olak_ids:
            if olak_id in seen:
                continue
            seen.add(olak_id)
            album_url = f"https://www.youtube.com/playlist?list={olak_id}"
            try:
                upload = self._list_album(olak_id, album_url=album_url)
            except Exception as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                logger.warning("youtube album skipped %s: %s", album_url, exc)
                continue
            if upload is not None:
                uploads.append(upload)
        return ArtistListing(
            platform=Platform.YOUTUBE,
            platform_id=channel_id,
            name=name,
            url=releases_url,
            uploads=uploads,
        )

    def _list_album(self, olak_id: str, *, album_url: str) -> Upload | None:
        info = self._extract(album_url)
        title = str(info.get("title") or info.get("playlist_title") or "")
        if not title:
            return None
        raw_entries = info.get("entries") or []
        if not isinstance(raw_entries, list) or not raw_entries:
            return None
        indexed: list[tuple[int, Track]] = []
        for position, item in enumerate(raw_entries):
            if not isinstance(item, dict):
                logger.warning("youtube track skipped on %s: non-dict entry", album_url)
                continue
            track = _youtube_track_from_entry(item)
            if track is None:
                logger.warning("youtube track skipped on %s: incomplete entry", album_url)
                continue
            order = _youtube_playlist_index(item, fallback=position)
            indexed.append((order, track))
        if not indexed:
            return None
        indexed.sort(key=lambda pair: pair[0])
        tracks = [track for _, track in indexed]
        return Upload(
            platform=Platform.YOUTUBE,
            platform_id=olak_id,
            title=title,
            url=album_url,
            duration_seconds=sum(t.duration_seconds for t in tracks),
            size_bytes=None,
            cover_url=_youtube_cover_url(info),
            tracks=tuple(tracks),
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
            cookies=self._cookies,
        )

    def _extract(self, url: str) -> dict[str, Any]:
        if self._extract_info is not None:
            return self._extract_info(url)
        return _youtube_extract_info(url, cookies=self._cookies)

    def _browse_music(self, channel_id: str) -> dict[str, Any]:
        if self._browse_music_artist is not None:
            return self._browse_music_artist(channel_id)
        return _youtube_music_browse_artist(channel_id)

    def _resolve_channel_id(self, artist_url: str) -> str | None:
        """Resolve UC… via channel-root extract when the paste URL has no /channel/ id."""
        parsed = urlparse(artist_url.strip())
        channel_path = youtube_channel_path(parsed.path or "/")
        if channel_path is None:
            return None
        root_url = f"https://www.youtube.com{channel_path}"
        try:
            info = self._extract(root_url)
        except Exception as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            logger.warning("youtube channel id resolve failed for %s: %s", root_url, exc)
            return None
        return _youtube_channel_id(info)


def _youtube_channel_id(info: dict[str, Any]) -> str | None:
    for key in ("channel_id", "uploader_id", "id"):
        value = info.get(key)
        if isinstance(value, str) and value.startswith("UC"):
            return value
    return None


def _youtube_missing_releases_tab(exc: BaseException) -> bool:
    return "does not have a releases tab" in str(exc).lower()


def _youtube_strip_topic_suffix(name: str) -> str:
    suffix = " - Topic"
    if name.endswith(suffix):
        return name[: -len(suffix)].rstrip() or name
    return name


def _youtube_music_browse_artist(channel_id: str) -> dict[str, Any]:
    """Browse a YouTube Music artist / Topic channel for album shelves."""
    endpoint = (
        "https://music.youtube.com/youtubei/v1/browse"
        f"?key={_YTM_API_KEY}&prettyPrint=false"
    )
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://music.youtube.com",
        "Referer": "https://music.youtube.com/",
    }
    body = {"context": _YTM_CONTEXT, "browseId": channel_id}
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(endpoint, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise ValueError(
            f"YouTube Music browse failed for channel {channel_id}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise TypeError(f"YouTube Music browse returned no object for {channel_id}")
    return data


def _youtube_music_artist_name(browse: dict[str, Any]) -> str | None:
    header = browse.get("header")
    if not isinstance(header, dict):
        return None

    def _runs_text(node: dict[str, Any]) -> str | None:
        title = node.get("title")
        if not isinstance(title, dict):
            return None
        runs = title.get("runs")
        if not isinstance(runs, list) or not runs:
            return None
        first = runs[0]
        if isinstance(first, dict) and isinstance(first.get("text"), str):
            text = first["text"].strip()
            return text or None
        return None

    for key in ("musicImmersiveHeaderRenderer", "musicVisualHeaderRenderer"):
        renderer = header.get(key)
        if isinstance(renderer, dict):
            name = _runs_text(renderer)
            if name:
                return _youtube_strip_topic_suffix(name)
    return None


def _youtube_music_olak_ids(browse: dict[str, Any]) -> list[str]:
    """Ordered unique OLAK playlist ids from Music album two-row cards."""
    found: list[str] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            renderer = node.get("musicTwoRowItemRenderer")
            if isinstance(renderer, dict):
                blob = json.dumps(renderer)
                if "MUSIC_PAGE_TYPE_ALBUM" in blob:
                    match = _OLAK_ID_FIND_RE.search(blob)
                    if match is not None:
                        olak_id = match.group(0)
                        if olak_id not in seen:
                            seen.add(olak_id)
                            found.append(olak_id)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(browse)
    return found


def _youtube_olak_id(entry: dict[str, Any]) -> str | None:
    candidates: list[str] = []
    for key in ("id", "url", "webpage_url"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)
    for value in candidates:
        if _OLAK_ID_RE.match(value):
            return value
        parsed = urlparse(value)
        for list_id in parse_qs(parsed.query).get("list") or []:
            if _OLAK_ID_RE.match(list_id):
                return list_id
    return None


def _youtube_playlist_index(item: dict[str, Any], *, fallback: int) -> int:
    raw = item.get("playlist_index")
    if raw is None:
        raw = item.get("playlist_autonumber")
    if raw is None:
        return fallback
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


def _youtube_normalize_thumb_url(url: str) -> str | None:
    cleaned = url.strip()
    if cleaned.startswith("//"):
        cleaned = f"https:{cleaned}"
    if not cleaned.startswith("http"):
        return None
    return cleaned


def _youtube_thumb_is_maxres(url: str) -> bool:
    # OLAK album playlists often advertise a 1200×1200 maxresdefault that 404s.
    return "maxresdefault" in url


def _youtube_cover_url(info: dict[str, Any]) -> str | None:
    """Pick a fetchable cover URL from yt-dlp playlist/video info.

    Prefer the largest non-maxres thumbnail: OLAK ``s_p`` maxresdefault often
    404s while sddefault/hqdefault succeed.
    """
    candidates: list[tuple[int, int, str]] = []

    def add(url: object, *, width: int = 0, height: int = 0) -> None:
        if not isinstance(url, str):
            return
        normalized = _youtube_normalize_thumb_url(url)
        if normalized is None:
            return
        candidates.append((width * height, 0 if _youtube_thumb_is_maxres(normalized) else 1, normalized))

    thumb = info.get("thumbnail")
    add(thumb)
    thumbs = info.get("thumbnails")
    if isinstance(thumbs, list):
        for item in thumbs:
            if not isinstance(item, dict):
                continue
            try:
                width = int(item.get("width") or 0)
                height = int(item.get("height") or 0)
            except (TypeError, ValueError):
                width, height = 0, 0
            add(item.get("url"), width=width, height=height)

    if candidates:
        # Prefer non-maxres (second key), then largest area.
        candidates.sort(key=lambda row: (row[1], row[0]), reverse=True)
        return candidates[0][2]

    entries = info.get("entries") or []
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            nested = _youtube_cover_url(entry)
            if nested is not None:
                return nested
    return None


def _youtube_track_from_entry(item: dict[str, Any]) -> Track | None:
    video_id = item.get("id")
    title = item.get("title")
    duration = item.get("duration")
    if not isinstance(video_id, str) or not video_id or not title:
        return None
    if duration is None:
        duration_seconds = 0
    else:
        try:
            duration_seconds = int(float(duration))
        except (TypeError, ValueError):
            return None
    return Track(
        platform_id=video_id,
        title=str(title),
        url=f"https://www.youtube.com/watch?v={video_id}",
        duration_seconds=duration_seconds,
    )


def _youtube_extract_info(
    url: str,
    *,
    cookies: YtdlpCookies | None = None,
) -> dict[str, Any]:
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "remote_components": ["ejs:github"],
    }
    apply_ytdlp_cookies(opts, cookies, for_youtube=True)
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        if youtube_auth_challenge(exc):
            raise youtube_anonymous_blocked_error(
                url, exc, cookies=cookies
            ) from exc
        raise
    if not isinstance(info, dict):
        raise TypeError(f"yt-dlp returned no info for {url}")
    return info
