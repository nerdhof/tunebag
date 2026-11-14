"""GET /api/mixes includes artist_id; DELETE /api/artists removes catalog rows."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from mixy.agent import DeviceAgent
from mixy.domain import Platform
from mixy.source import ArtistListing, FakeSource, Upload
from mixy.web import create_app


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
    assert row["title"] == "Set A"


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
