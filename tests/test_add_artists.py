"""Issue 02: add artists — exercised only through DeviceAgent + FakeSource."""

from __future__ import annotations

from mixy.agent import DeviceAgent
from mixy.domain import Platform
from mixy.source import ArtistListing, FakeSource, Upload


def _source_with_two_artists() -> FakeSource:
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
                Upload(
                    platform=Platform.SOUNDCLOUD,
                    platform_id="a-short",
                    title="Alpha Short",
                    url="https://soundcloud.com/dj-alpha/short",
                    duration_seconds=600,
                ),
            ],
        ),
    )
    source.add_listing(
        "https://hearthis.at/dj-beta/",
        ArtistListing(
            platform=Platform.HEARTHIS,
            platform_id="beta",
            name="DJ Beta",
            url="https://hearthis.at/dj-beta/",
            uploads=[
                Upload(
                    platform=Platform.HEARTHIS,
                    platform_id="b1",
                    title="Beta Marathon",
                    url="https://hearthis.at/dj-beta/marathon/",
                    duration_seconds=7200,
                ),
            ],
        ),
    )
    return source


def test_one_artist_url_adds_catalog_rows_without_audio() -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", source=source)

    mixes = laptop.add_artists(["https://soundcloud.com/dj-alpha"])

    assert [m.title for m in mixes] == ["Alpha Long Set"]
    assert [m.title for m in laptop.mixes()] == ["Alpha Long Set"]
    long = laptop.mixes()[0]
    assert long.duration_seconds == 3600
    assert long.url == "https://soundcloud.com/dj-alpha/long"
    assert [a.name for a in laptop.artists()] == ["DJ Alpha"]
    assert laptop.files() == []
    assert source.fetch_calls == []


def test_several_artist_urls_in_one_step() -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", source=source)

    laptop.add_artists(
        [
            "https://soundcloud.com/dj-alpha",
            "https://hearthis.at/dj-beta/",
        ]
    )

    titles = {m.title for m in laptop.mixes()}
    assert titles == {"Alpha Long Set", "Beta Marathon"}
    assert {a.name for a in laptop.artists()} == {"DJ Alpha", "DJ Beta"}


def test_default_min_duration_drops_short_uploads() -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", source=source)

    laptop.add_artists(["https://soundcloud.com/dj-alpha"])

    assert "Alpha Short" not in {m.title for m in laptop.mixes()}


def test_custom_min_duration_seconds_changes_cut() -> None:
    include_short = DeviceAgent("open", source=_source_with_two_artists())
    include_short.add_artists(
        ["https://soundcloud.com/dj-alpha"],
        min_duration_seconds=0,
    )
    assert {m.title for m in include_short.mixes()} == {"Alpha Long Set", "Alpha Short"}

    only_longer = DeviceAgent("strict", source=_source_with_two_artists())
    only_longer.add_artists(
        ["https://soundcloud.com/dj-alpha"],
        min_duration_seconds=4000,
    )
    assert only_longer.mixes() == []


def test_paired_peer_sees_rows_after_sync_without_files() -> None:
    source = _source_with_two_artists()
    laptop = DeviceAgent("laptop", priority=1, source=source)
    phone = DeviceAgent("phone", priority=10, source=FakeSource())
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())

    laptop.add_artists(
        [
            "https://soundcloud.com/dj-alpha",
            "https://hearthis.at/dj-beta/",
        ]
    )
    laptop.sync()
    phone.sync()

    assert {m.title for m in phone.mixes()} == {"Alpha Long Set", "Beta Marathon"}
    assert {m.url for m in phone.mixes()} == {
        "https://soundcloud.com/dj-alpha/long",
        "https://hearthis.at/dj-beta/marathon/",
    }
    assert phone.files() == []
    assert source.fetch_calls == []
