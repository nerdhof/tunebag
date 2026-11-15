"""Operational activity log for add_artists and fill."""

from __future__ import annotations

from pathlib import Path

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.source import ArtistListing, FakeSource, Upload


def test_add_artists_records_start_and_end() -> None:
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
    laptop = DeviceAgent("laptop", source=source)

    laptop.add_artists(["https://soundcloud.com/dj-alpha"])

    messages = [entry.message for entry in laptop.activity()]
    assert any(m.startswith("add artists start") for m in messages)
    assert any(m.startswith("fetch artist list start:") for m in messages)
    assert any("DJ Alpha" in m and "end" in m for m in messages)
    assert any(m.startswith("add artists end") for m in messages)


def test_fill_caches_records_download_and_end(tmp_path: Path) -> None:
    source = FakeSource()
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=source,
        data_dir=tmp_path / "laptop",
    )
    url = "https://example.com/a"
    source.bytes_by_url[url] = b"audio:a"
    mix = laptop.add_mix(
        title="Set A",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="a",
        artist_name="DJ Example",
    )
    laptop.rate_mix(mix.id, Stars.FIVE)
    laptop.create_intent(
        "Fill",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    laptop.fill_caches()

    messages = [entry.message for entry in laptop.activity()]
    assert any(m == "fill caches start" for m in messages)
    assert any(m.startswith("download from origin: Set A") for m in messages)
    assert any(m.startswith("cached: Set A") for m in messages)
    assert any(m.startswith("fill caches end") for m in messages)
