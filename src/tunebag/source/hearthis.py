"""hearthis.at artist listing and audio fetch."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from tunebag.domain import Platform
from tunebag.source.models import ArtistListing, Upload, optional_size_bytes
from tunebag.ytdlp_fetch import AudioFetcher, ProgressCallback, fetch_audio_bytes


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
        size_bytes=optional_size_bytes(item),
    )
