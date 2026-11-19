"""Release cover URL ingest, local cache, refresh backfill, and HTTP."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.cover_cache import cover_media_type, cover_path
from tunebag.domain import Platform
from tunebag.reject import UNDO_SECONDS
from tunebag.source import ArtistListing, FakeSource, Upload
from tunebag.source.hearthis import _hearthis_upload
from tunebag.source.youtube import _youtube_cover_url
from tunebag.web import create_app

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32 + b"\xff\xd9"


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 1, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def test_cover_media_type_sniffs_jpeg() -> None:
    assert cover_media_type(JPEG_BYTES) == "image/jpeg"
    assert cover_media_type(b"\x89PNG\r\n\x1a\n") == "image/png"


def test_hearthis_upload_reads_thumb() -> None:
    upload = _hearthis_upload(
        {
            "id": 7,
            "title": "Long",
            "permalink_url": "https://hearthis.at/dj/long/",
            "duration": 3600,
            "thumb": "https://hearthis.at/thumb/7.jpg",
            "user": {"id": "dj", "permalink": "dj"},
        },
        owner_id="dj",
        owner_permalink="dj",
    )
    assert upload is not None
    assert upload.cover_url == "https://hearthis.at/thumb/7.jpg"


def test_youtube_cover_url_prefers_largest_thumbnail() -> None:
    url = _youtube_cover_url(
        {
            "thumbnails": [
                {"url": "https://i.ytimg.com/vi/a/default.jpg", "width": 120, "height": 90},
                {"url": "https://i.ytimg.com/vi/a/hqdefault.jpg", "width": 480, "height": 360},
            ]
        }
    )
    assert url == "https://i.ytimg.com/vi/a/hqdefault.jpg"


def test_youtube_cover_url_skips_olak_maxresdefault() -> None:
    """OLAK playlists advertise a 1200×1200 maxresdefault that often 404s."""
    url = _youtube_cover_url(
        {
            "thumbnails": [
                {
                    "url": "https://i9.ytimg.com/s_p/OLAK/mqdefault.jpg",
                    "width": 180,
                    "height": 180,
                },
                {
                    "url": "https://i9.ytimg.com/s_p/OLAK/sddefault.jpg",
                    "width": 640,
                    "height": 640,
                },
                {
                    "url": "https://i9.ytimg.com/s_p/OLAK/maxresdefault.jpg",
                    "width": 1200,
                    "height": 1200,
                },
            ]
        }
    )
    assert url == "https://i9.ytimg.com/s_p/OLAK/sddefault.jpg"


def test_youtube_cover_url_normalizes_protocol_relative() -> None:
    url = _youtube_cover_url(
        {
            "entries": [
                {
                    "thumbnails": [
                        {
                            "url": "//i.ytimg.com/vi/abc/hqdefault.jpg",
                            "width": 480,
                            "height": 360,
                        }
                    ]
                }
            ]
        }
    )
    assert url == "https://i.ytimg.com/vi/abc/hqdefault.jpg"


def test_cover_cache_falls_back_from_maxresdefault(tmp_path: Path) -> None:
    from uuid import uuid4

    from tunebag.cover_cache import CoverCache

    attempted: list[str] = []

    def fetch(url: str) -> bytes:
        attempted.append(url)
        if "maxresdefault" in url:
            raise httpx.HTTPStatusError(
                "404",
                request=httpx.Request("GET", url),
                response=httpx.Response(404),
            )
        return JPEG_BYTES

    cache = CoverCache(tmp_path, fetch=fetch)
    mix_id = uuid4()
    assert cache.ensure(
        mix_id, "https://i9.ytimg.com/s_p/OLAK/maxresdefault.jpg"
    )
    assert cache.has(mix_id)
    assert attempted[0].endswith("maxresdefault.jpg")
    assert any(u.endswith("sddefault.jpg") for u in attempted)


def test_add_artists_caches_cover_and_player_api(tmp_path: Path) -> None:
    fetches: list[str] = []

    def cover_fetch(url: str) -> bytes:
        fetches.append(url)
        return JPEG_BYTES

    source = FakeSource()
    source.add_listing(
        "https://soundcloud.com/dj",
        ArtistListing(
            platform=Platform.SOUNDCLOUD,
            platform_id="dj",
            name="DJ",
            url="https://soundcloud.com/dj",
            uploads=[
                Upload(
                    platform=Platform.SOUNDCLOUD,
                    platform_id="m1",
                    title="Long Set",
                    url="https://soundcloud.com/dj/long",
                    duration_seconds=3600,
                    cover_url="https://cdn.example/cover.jpg",
                ),
            ],
        ),
    )
    agent = DeviceAgent(
        "laptop",
        source=source,
        data_dir=tmp_path / "laptop",
        cover_fetch=cover_fetch,
    )
    mixes = agent.add_artists(["https://soundcloud.com/dj"])
    assert len(mixes) == 1
    mix = mixes[0]
    assert mix.cover_url == "https://cdn.example/cover.jpg"
    assert agent.has_local_cover(mix.id)
    assert fetches == ["https://cdn.example/cover.jpg"]
    assert cover_path(agent.data_dir, mix.id).read_bytes() == JPEG_BYTES

    source.bytes_by_url[mix.url] = b"audio"
    intent = agent.create_intent(
        "Play",
        seed=1,
        device_hours=[(agent.device_id, 3600)],
    )
    agent.fill_caches()
    agent.play(intent.id, mix.id)

    client = TestClient(create_app(agent))
    player = client.get("/api/player")
    assert player.status_code == 200
    body = player.json()
    assert body["has_cover"] is True
    assert body["current_mix_id"] == str(mix.id)

    cover = client.get(f"/api/mixes/{mix.id}/cover")
    assert cover.status_code == 200
    assert cover.headers["content-type"].startswith("image/jpeg")
    assert cover.content == JPEG_BYTES


def test_refresh_backfills_cover_for_known_mix(tmp_path: Path) -> None:
    fetches: list[str] = []

    def cover_fetch(url: str) -> bytes:
        fetches.append(url)
        return JPEG_BYTES

    source = FakeSource()
    listing = ArtistListing(
        platform=Platform.SOUNDCLOUD,
        platform_id="dj",
        name="DJ",
        url="https://soundcloud.com/dj",
        uploads=[
            Upload(
                platform=Platform.SOUNDCLOUD,
                platform_id="m1",
                title="Long Set",
                url="https://soundcloud.com/dj/long",
                duration_seconds=3600,
                # First ingest has no cover URL (legacy listing).
            ),
        ],
    )
    source.add_listing("https://soundcloud.com/dj", listing)
    agent = DeviceAgent(
        "laptop",
        source=source,
        data_dir=tmp_path / "laptop",
        cover_fetch=cover_fetch,
    )
    mixes = agent.add_artists(["https://soundcloud.com/dj"])
    mix = mixes[0]
    assert mix.cover_url is None
    assert not agent.has_local_cover(mix.id)
    assert fetches == []

    source.add_listing(
        "https://soundcloud.com/dj",
        ArtistListing(
            platform=Platform.SOUNDCLOUD,
            platform_id="dj",
            name="DJ",
            url="https://soundcloud.com/dj",
            uploads=[
                Upload(
                    platform=Platform.SOUNDCLOUD,
                    platform_id="m1",
                    title="Long Set",
                    url="https://soundcloud.com/dj/long",
                    duration_seconds=3600,
                    cover_url="https://cdn.example/later.jpg",
                ),
            ],
        ),
    )
    added = agent.refresh_artists()
    assert added == []
    assert agent.has_local_cover(mix.id)
    assert fetches == ["https://cdn.example/later.jpg"]
    # Catalog cover_url stays unset for legacy MIX_ADDED (no new event type).
    assert agent.catalog.mixes[mix.id].cover_url is None
    assert agent.has_cover(mix.id) is True


def test_reject_deletes_local_cover(tmp_path: Path) -> None:
    clock = FakeClock()
    source = FakeSource()
    source.add_listing(
        "https://soundcloud.com/dj",
        ArtistListing(
            platform=Platform.SOUNDCLOUD,
            platform_id="dj",
            name="DJ",
            url="https://soundcloud.com/dj",
            uploads=[
                Upload(
                    platform=Platform.SOUNDCLOUD,
                    platform_id="m1",
                    title="Long Set",
                    url="https://soundcloud.com/dj/long",
                    duration_seconds=3600,
                    cover_url="https://cdn.example/cover.jpg",
                ),
            ],
        ),
    )
    agent = DeviceAgent(
        "laptop",
        source=source,
        data_dir=tmp_path / "laptop",
        cover_fetch=lambda _url: JPEG_BYTES,
        clock=clock,
    )
    mix = agent.add_artists(["https://soundcloud.com/dj"])[0]
    assert agent.has_local_cover(mix.id)

    agent.reject_mix(mix.id)
    # Pending undo window — cover still present until commit.
    assert agent.has_local_cover(mix.id)
    clock.advance(UNDO_SECONDS)
    agent.commit_pending_rejects()
    assert not agent.has_local_cover(mix.id)


def test_player_ui_has_cover_slot() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    html = (root / "index.html").read_text()
    css = (root / "app.css").read_text()
    js = (root / "app.js").read_text()
    assert 'id="player-cover"' in html
    assert "player-below-text" in html
    assert ".player-cover" in css
    assert "renderPlayerCover" in js
    assert "has_cover" in js


def test_cover_endpoint_404_without_art(tmp_path: Path) -> None:
    agent = DeviceAgent(
        "laptop",
        source=FakeSource(),
        data_dir=tmp_path / "laptop",
    )
    mix = agent.add_mix(
        title="Bare",
        url="https://example.com/bare",
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="bare",
        artist_name="DJ",
    )
    client = TestClient(create_app(agent))
    res = client.get(f"/api/mixes/{mix.id}/cover")
    assert res.status_code == 404
    player = client.get("/api/player")
    assert player.json()["has_cover"] is False
