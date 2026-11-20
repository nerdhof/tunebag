"""Release cover URL ingest, local cache, refresh backfill, and HTTP."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.cover_cache import (
    cover_media_type,
    cover_path,
    hearthis_cover_fallback_urls,
)
from tunebag.domain import Platform
from tunebag.reject import SOFT_REJECT_SECONDS
from tunebag.source import ArtistListing, FakeSource, Upload
from tunebag.source.hearthis import _hearthis_cover_url, _hearthis_upload
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


def test_hearthis_cover_url_prefers_retina() -> None:
    url = _hearthis_cover_url(
        {
            "thumb": "https://img.hearthis.at/x/w200_h200_q70.jpg",
            "thumb_hires": "https://img.hearthis.at/x/w400_h400_q70.jpg",
            "artwork_url": "https://img.hearthis.at/x/w500_h500_q70.jpg",
            "artwork_url_retina": "https://img.hearthis.at/x/w800_h800_q70.jpg",
        }
    )
    assert url == "https://img.hearthis.at/x/w800_h800_q70.jpg"


def test_hearthis_cover_fallback_urls_rewrites_sizes() -> None:
    primary = (
        "https://img.hearthis.at/0/2/7/_/uploads/8338/image_track/14724007/"
        "w200_h200_q70_ptrue_v2_m1792104379----cropped_1792104376720.jpg"
        "?m=1792104379"
    )
    alts = hearthis_cover_fallback_urls(primary)
    assert alts[0].startswith(
        "https://img.hearthis.at/0/2/7/_/uploads/8338/image_track/14724007/w800_h800_"
    )
    assert any("w500_h500" in u for u in alts)
    assert any("w400_h400" in u for u in alts)
    assert any("w80_h80" in u for u in alts)
    assert any("w40_h40" in u for u in alts)
    # Tiny squares come after mid sizes (last-resort).
    assert alts.index(next(u for u in alts if "w80_h80" in u)) > alts.index(
        next(u for u in alts if "w500_h500" in u)
    )
    assert all("w200_h200" not in u for u in alts)
    assert all(u.endswith("?m=1792104379") for u in alts)
    assert hearthis_cover_fallback_urls("https://hearthis.at/thumb/7.jpg") == []


def test_hearthis_cover_fallback_urls_slug_prefixed() -> None:
    """Older art embeds the track slug after the cropped hash; page URLs use it."""
    primary = (
        "https://img.hearthis.at/3/t/s/_/uploads/8338/image_track/41425/"
        "w800_h800_q70_ptrue_v2_----cropped_"
        "4b659f1bc4eac1f057fec60b35cfac70naughtylist3.jpg"
    )
    alts = hearthis_cover_fallback_urls(primary)
    slug = (
        "https://img.hearthis.at/3/t/s/_/uploads/8338/image_track/41425/"
        "naughtylist3----w640_h640_c3a3a3a_q70_ptrue_v2_----cropped_"
        "4b659f1bc4eac1f057fec60b35cfac70naughtylist3.jpg"
    )
    assert slug in alts
    # Prefer slug mid-size over tiny square last-resort.
    assert alts.index(slug) < alts.index(next(u for u in alts if "w80_h80" in u))


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


def test_cover_cache_falls_back_hearthis_size_on_403(tmp_path: Path) -> None:
    from uuid import uuid4

    from tunebag.cover_cache import CoverCache

    primary = (
        "https://img.hearthis.at/0/2/7/_/uploads/8338/image_track/1/"
        "w200_h200_q70_ptrue.jpg?m=1"
    )
    attempted: list[str] = []

    def fetch(url: str) -> bytes:
        attempted.append(url)
        if "w200_h200" in url:
            raise httpx.HTTPStatusError(
                "403",
                request=httpx.Request("GET", url),
                response=httpx.Response(403),
            )
        if "w500_h500" in url:
            return JPEG_BYTES
        raise httpx.HTTPStatusError(
            "403",
            request=httpx.Request("GET", url),
            response=httpx.Response(403),
        )

    cache = CoverCache(tmp_path, fetch=fetch)
    mix_id = uuid4()
    assert cache.ensure(mix_id, primary)
    assert cache.has(mix_id)
    assert attempted[0] == primary
    assert any("w500_h500" in u for u in attempted)


def test_cover_cache_falls_back_hearthis_tiny_or_slug_on_403(tmp_path: Path) -> None:
    """Naughtylist-style: mid sizes 403; slug-prefixed or tiny squares still 200."""
    from uuid import uuid4

    from tunebag.cover_cache import CoverCache

    primary = (
        "https://img.hearthis.at/3/t/s/_/uploads/8338/image_track/41425/"
        "w800_h800_q70_ptrue_v2_----cropped_"
        "4b659f1bc4eac1f057fec60b35cfac70naughtylist3.jpg"
    )
    attempted: list[str] = []

    def fetch(url: str) -> bytes:
        attempted.append(url)
        if "naughtylist3----w640_h640" in url:
            return JPEG_BYTES
        raise httpx.HTTPStatusError(
            "403",
            request=httpx.Request("GET", url),
            response=httpx.Response(403),
        )

    cache = CoverCache(tmp_path, fetch=fetch)
    mix_id = uuid4()
    assert cache.ensure(mix_id, primary)
    assert cache.has(mix_id)
    assert any("naughtylist3----w640_h640" in u for u in attempted)


def test_hearthis_cover_urls_from_html_ranks_square_track_art() -> None:
    from tunebag.cover_cache import hearthis_cover_urls_from_html

    html = """
    <img src="https://img.hearthis.at/x/image_user/1/w64_h64_q70.jpg">
    <img src="https://img.hearthis.at/x/image_track/13107798/banner----w1200_h629_q100.jpg">
    <img src="https://img.hearthis.at/x/image_track/13107798/cover----w880_h880_c3a3a3a_q70.jpg">
    <img src="https://img.hearthis.at/x/image_track/999/other----w640_h640_c3a3a3a_q70.jpg">
    <img src="https://img.hearthis.at/x/image_track/13107798/w800_h800_btrue_c000000_q20_o30.jpg)">
    """
    urls = hearthis_cover_urls_from_html(html, track_id="13107798")
    assert urls[0].endswith("cover----w880_h880_c3a3a3a_q70.jpg")
    assert all("/13107798/" in u for u in urls)
    assert all("/image_user/" not in u for u in urls)
    assert "btrue" in urls[-1]
    assert not urls[-1].endswith(")")


def test_cover_cache_scrapes_hearthis_page_as_last_resort(tmp_path: Path) -> None:
    from uuid import uuid4

    from tunebag.cover_cache import CoverCache

    primary = (
        "https://img.hearthis.at/8/4/5/_/uploads/8338/image_track/13107798/"
        "w800_h800_q70_ptrue_v2_m1----cropped_1.jpg"
    )
    page = "https://hearthis.at/saetchmo/echochamber251113604/"
    page_art = (
        "https://img.hearthis.at/8/4/5/_/uploads/8338/image_track/13107798/"
        "echochamber-604-131125----w880_h880_c3a3a3a_q70_ptrue_v2_m1----cropped_1.jpg"
    )
    attempted: list[str] = []

    def fetch(url: str) -> bytes:
        attempted.append(url)
        if url == page:
            return (
                f'<html><img src="{page_art}"></html>'
            ).encode()
        if url == page_art:
            return JPEG_BYTES
        raise httpx.HTTPStatusError(
            "403",
            request=httpx.Request("GET", url),
            response=httpx.Response(403),
        )

    cache = CoverCache(tmp_path, fetch=fetch)
    mix_id = uuid4()
    assert cache.ensure(mix_id, primary, page_url=page)
    assert cache.has(mix_id)
    assert page in attempted
    assert page_art in attempted
    assert attempted.index(page) < attempted.index(page_art)


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
    # Soft window — cover still present until Soft → Hard File delete.
    assert agent.has_local_cover(mix.id)
    clock.advance(SOFT_REJECT_SECONDS)
    agent.commit_reject_file_deletes()
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
    # Intent on Player heading row; cover + title in .player-now-row above seek.
    assert 'class="player-heading-row"' in html
    assert 'class="player-now-row"' in html
    assert "player-heading-row" in css
    assert "player-now-row" in css
    assert "syncPlayerNowStack" in js
    assert "measurePlayerTitleIntrinsicWidth" in js
    assert "selectNodeContents" in js
    assert "--player-cover-size" in css
    assert 'setProperty("--player-cover-size"' in js
    assert "PLAYER_COVER_MIN_REM" in js
    assert "syncPlayerIntentWrap" in js
    assert "is-stacked" in css
    assert "intent-wrapped" in css
    assert "white-space: nowrap" in css  # title single-line beside cover
    intent_at = html.index('id="player-intent"')
    cover_at = html.index('id="player-cover"')
    text_at = html.index('class="player-below-text"')
    clip_at = html.index('class="player-clip"')
    assert intent_at < cover_at < text_at < clip_at
    assert 'id="player-seekbar"' in html[clip_at:]
    # Seek labels clip via raised .player-clip; tags stay outside that clip.
    assert "--player-seek-clip-rise" in css
    assert "syncPlayerSeekClipRise" in js


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
