"""GET /api/mixes includes artist_id; DELETE /api/artists removes catalog rows."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, ReleaseKind, Stars
from tunebag.source import ArtistListing, FakeSource, Track, Upload
from tunebag.web import create_app


def test_mixes_api_includes_artist_fields(tmp_path: Path) -> None:
    source = FakeSource()
    source.bytes_by_url["https://example.com/a"] = b"audio:a"
    agent = DeviceAgent("laptop", source=source, data_dir=tmp_path / "laptop")
    mix = agent.add_mix(
        title="Set A",
        url="https://example.com/a",
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="a",
        artist_name="DJ Example",
        size_bytes=4_000_000,
    )

    client = TestClient(create_app(agent))
    res = client.get("/api/mixes")

    assert res.status_code == 200
    payload = res.json()
    assert len(payload["mixes"]) == 1
    row = payload["mixes"][0]
    assert row["id"] == str(mix.id)
    assert row["artist_id"] == str(mix.artist_id)
    assert row["artist"] == "DJ Example"
    assert row["artist_url"] == "https://example.com/a"
    assert row["platform"] == Platform.SOUNDCLOUD.value
    assert row["title"] == "Set A"
    assert row["size_bytes"] == 4_000_000


def test_player_api_uses_catalog_artist_name(tmp_path: Path) -> None:
    """GET /api/player shows Artist.name from the added SoundCloud/Bandcamp link."""
    source = FakeSource()
    source.bytes_by_url["https://example.com/a"] = b"audio:a"
    agent = DeviceAgent("laptop", source=source, data_dir=tmp_path / "laptop")
    mix = agent.add_mix(
        title="Set A",
        url="https://example.com/a",
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="a",
        artist_name="DJ Example",
        size_bytes=4_000_000,
    )
    intent = agent.create_intent(
        "Play",
        seed=1,
        device_hours=[(agent.device_id, 3600)],
    )
    agent.fill_caches()
    agent.play(intent.id, mix.id)

    client = TestClient(create_app(agent))
    res = client.get("/api/player")

    assert res.status_code == 200
    body = res.json()
    assert body["current_mix_id"] == str(mix.id)
    assert body["artist"] == "DJ Example"
    assert body["artist_url"] == "https://example.com/a"
    assert body["platform"] == Platform.SOUNDCLOUD.value
    assert body["url"] == "https://example.com/a"
    assert body["title"] == "Set A"
    assert body["kind"] == "mix"
    assert body["tracks"] == []
    assert body["has_cover"] is False


def test_player_api_includes_album_track_sections(tmp_path: Path) -> None:
    """GET /api/player exposes album track titles/durations for seek sections."""
    source = FakeSource()
    track_urls = (
        "https://example.bandcamp.com/track/one",
        "https://example.bandcamp.com/track/two",
        "https://example.bandcamp.com/track/three",
    )
    source.add_listing(
        "https://example.bandcamp.com/music",
        ArtistListing(
            platform=Platform.BANDCAMP,
            platform_id="example",
            name="Example Artist",
            url="https://example.bandcamp.com/music",
            uploads=[
                Upload(
                    platform=Platform.BANDCAMP,
                    platform_id="album-1",
                    title="Example Album",
                    url="https://example.bandcamp.com/album/example",
                    duration_seconds=0,
                    tracks=(
                        Track(
                            platform_id="t1",
                            title="One",
                            url=track_urls[0],
                            duration_seconds=600,
                            size_bytes=1_000_000,
                        ),
                        Track(
                            platform_id="t2",
                            title="Two",
                            url=track_urls[1],
                            duration_seconds=900,
                            size_bytes=2_000_000,
                        ),
                        Track(
                            platform_id="t3",
                            title="Three",
                            url=track_urls[2],
                            duration_seconds=300,
                            size_bytes=500_000,
                        ),
                    ),
                ),
            ],
        ),
    )
    for url in track_urls:
        source.bytes_by_url[url] = f"audio:{url}".encode()

    agent = DeviceAgent("laptop", source=source, data_dir=tmp_path / "laptop")
    added = agent.add_artists(["https://example.bandcamp.com/music"])
    assert len(added) == 1
    album = added[0]
    assert album.kind is ReleaseKind.ALBUM
    agent.rate_mix(album.id, Stars.FIVE)
    intent = agent.create_intent(
        "Play",
        seed=1,
        device_hours=[(agent.device_id, 3600)],
    )
    agent.fill_caches()
    agent.play(intent.id, album.id)

    client = TestClient(create_app(agent))
    res = client.get("/api/player")

    assert res.status_code == 200
    body = res.json()
    assert body["current_mix_id"] == str(album.id)
    assert body["kind"] == "album"
    assert body["tracks"] == [
        {"title": "One", "duration_seconds": 600},
        {"title": "Two", "duration_seconds": 900},
        {"title": "Three", "duration_seconds": 300},
    ]


def test_delete_artists_api_removes_artist_and_mixes(tmp_path: Path) -> None:
    source = FakeSource()
    source.add_listing(
        "https://soundcloud.com/dj-alpha",
        ArtistListing(
            platform=Platform.SOUNDCLOUD,
            platform_id="alpha",
            name="DJ Alpha",
            url="https://soundcloud.com/dj-alpha",
            uploads=[
                Upload(
                    platform=Platform.SOUNDCLOUD,
                    platform_id="a1",
                    title="Alpha Long Set",
                    url="https://soundcloud.com/dj-alpha/long",
                    duration_seconds=3600,
                ),
            ],
        ),
    )
    agent = DeviceAgent("laptop", source=source, data_dir=tmp_path / "laptop")
    agent.add_artists(["https://soundcloud.com/dj-alpha"])
    artist = agent.artists()[0]
    client = TestClient(create_app(agent))

    res = client.delete(f"/api/artists/{artist.id}")

    assert res.status_code == 200
    assert res.json() == {"ok": True, "deleted": str(artist.id)}
    assert client.get("/api/artists").json()["artists"] == []
    assert client.get("/api/mixes").json()["mixes"] == []


def test_delete_artists_api_unknown_is_404(tmp_path: Path) -> None:
    agent = DeviceAgent("laptop", source=FakeSource(), data_dir=tmp_path / "laptop")
    client = TestClient(create_app(agent))

    res = client.delete(f"/api/artists/{uuid4()}")

    assert res.status_code == 404
