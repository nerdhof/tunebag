"""SoundCloud artist listing and audio fetch."""

from __future__ import annotations

import os
import re

import httpx

from tunebag.domain import Platform
from tunebag.source.models import ArtistListing, Upload, optional_size_bytes
from tunebag.ytdlp_fetch import AudioFetcher, ProgressCallback, fetch_audio_bytes


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
        size_bytes=optional_size_bytes(track),
        cover_url=_soundcloud_cover_url(track),
    )


def _soundcloud_cover_url(track: dict) -> str | None:
    raw = track.get("artwork_url") or track.get("avatar_url")
    if not raw or not isinstance(raw, str):
        return None
    # API often returns "-large"; prefer a sharper square for UI.
    if "-large." in raw:
        return raw.replace("-large.", "-t500x500.")
    return raw
