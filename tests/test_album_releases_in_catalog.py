"""Issue 01: Album Releases in Catalog — DeviceAgent + FakeSource."""

from __future__ import annotations

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, ReleaseKind
from tunebag.source import ArtistListing, FakeSource, Track, Upload


def _bandcamp_album_source() -> FakeSource:
    source = FakeSource()
    source.add_listing(
        "https://chrishuelsbeck.bandcamp.com/music",
        ArtistListing(
            platform=Platform.BANDCAMP,
            platform_id="chrishuelsbeck",
            name="Chris Huelsbeck",
            url="https://chrishuelsbeck.bandcamp.com/music",
            uploads=[
                Upload(
                    platform=Platform.BANDCAMP,
                    platform_id="album-turrican",
                    title="Turrican Soundtrack",
                    url="https://chrishuelsbeck.bandcamp.com/album/turrican",
                    duration_seconds=0,
                    tracks=(
                        Track(
                            platform_id="t1",
                            title="The Great Bath",
                            url="https://chrishuelsbeck.bandcamp.com/track/the-great-bath",
                            duration_seconds=600,
                            size_bytes=1_000_000,
                        ),
                        Track(
                            platform_id="t2",
                            title="Turrican Soundtrack Theme",
                            url=(
                                "https://chrishuelsbeck.bandcamp.com/track/"
                                "turrican-soundtrack-theme"
                            ),
                            duration_seconds=900,
                            size_bytes=2_000_000,
                        ),
                        Track(
                            platform_id="t3",
                            title="Scores",
                            url="https://chrishuelsbeck.bandcamp.com/track/scores",
                            duration_seconds=300,
                            size_bytes=500_000,
                        ),
                    ),
                ),
            ],
        ),
    )
    return source


def test_album_listing_enters_catalog_as_album_without_audio() -> None:
    source = _bandcamp_album_source()
    laptop = DeviceAgent("laptop", source=source)

    added = laptop.add_artists(["https://chrishuelsbeck.bandcamp.com/music"])

    assert len(added) == 1
    album = added[0]
    assert album.kind is ReleaseKind.ALBUM
    assert album.title == "Turrican Soundtrack"
    assert album.url == "https://chrishuelsbeck.bandcamp.com/album/turrican"
    assert album.platform is Platform.BANDCAMP
    assert album.platform_id == "album-turrican"
    assert album.duration_seconds == 1800
    assert album.size_bytes == 3_500_000
    assert [
        (t.platform_id, t.title, t.duration_seconds, t.url, t.size_bytes)
        for t in album.tracks
    ] == [
        (
            "t1",
            "The Great Bath",
            600,
            "https://chrishuelsbeck.bandcamp.com/track/the-great-bath",
            1_000_000,
        ),
        (
            "t2",
            "Turrican Soundtrack Theme",
            900,
            "https://chrishuelsbeck.bandcamp.com/track/turrican-soundtrack-theme",
            2_000_000,
        ),
        (
            "t3",
            "Scores",
            300,
            "https://chrishuelsbeck.bandcamp.com/track/scores",
            500_000,
        ),
    ]
    catalog = laptop.mixes()
    assert len(catalog) == 1
    assert catalog[0].id == album.id
    assert catalog[0].kind is ReleaseKind.ALBUM
    assert catalog[0].tracks == album.tracks
    assert laptop.files() == []
    assert source.fetch_calls == []


def test_soundcloud_and_hearthis_uploads_remain_mix_releases() -> None:
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
                    size_bytes=12_345_678,
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
    laptop = DeviceAgent("laptop", source=source)

    laptop.add_artists(
        [
            "https://soundcloud.com/dj-alpha",
            "https://hearthis.at/dj-beta/",
        ]
    )

    by_title = {m.title: m for m in laptop.mixes()}
    assert by_title["Alpha Long Set"].kind is ReleaseKind.MIX
    assert by_title["Alpha Long Set"].tracks == []
    assert by_title["Alpha Long Set"].duration_seconds == 3600
    assert by_title["Alpha Long Set"].size_bytes == 12_345_678
    assert by_title["Beta Marathon"].kind is ReleaseKind.MIX
    assert by_title["Beta Marathon"].tracks == []
    assert laptop.files() == []


def test_full_album_filter_skips_short_and_one_track_releases() -> None:
    source = FakeSource()
    source.add_listing(
        "https://example.bandcamp.com/music",
        ArtistListing(
            platform=Platform.BANDCAMP,
            platform_id="example",
            name="Example",
            url="https://example.bandcamp.com/music",
            uploads=[
                Upload(
                    platform=Platform.BANDCAMP,
                    platform_id="full",
                    title="Full Album",
                    url="https://example.bandcamp.com/album/full",
                    duration_seconds=0,
                    tracks=(
                        Track(
                            platform_id="f1",
                            title="One",
                            url="https://example.bandcamp.com/track/one",
                            duration_seconds=700,
                        ),
                        Track(
                            platform_id="f2",
                            title="Two",
                            url="https://example.bandcamp.com/track/two",
                            duration_seconds=700,
                        ),
                    ),
                ),
                Upload(
                    platform=Platform.BANDCAMP,
                    platform_id="short-ep",
                    title="Tiny EP",
                    url="https://example.bandcamp.com/album/tiny",
                    duration_seconds=0,
                    tracks=(
                        Track(
                            platform_id="s1",
                            title="A",
                            url="https://example.bandcamp.com/track/a",
                            duration_seconds=400,
                        ),
                        Track(
                            platform_id="s2",
                            title="B",
                            url="https://example.bandcamp.com/track/b",
                            duration_seconds=400,
                        ),
                    ),
                ),
                Upload(
                    platform=Platform.BANDCAMP,
                    platform_id="single",
                    title="One Track",
                    url="https://example.bandcamp.com/album/single",
                    duration_seconds=0,
                    tracks=(
                        Track(
                            platform_id="x1",
                            title="Only",
                            url="https://example.bandcamp.com/track/only",
                            duration_seconds=3600,
                        ),
                    ),
                ),
            ],
        ),
    )
    laptop = DeviceAgent("laptop", source=source)

    added = laptop.add_artists(
        ["https://example.bandcamp.com/music"],
        min_duration_seconds=1200,
    )

    assert [m.title for m in added] == ["Full Album"]
    assert [m.title for m in laptop.mixes()] == ["Full Album"]
    assert laptop.mixes()[0].kind is ReleaseKind.ALBUM
    assert laptop.mixes()[0].duration_seconds == 1400


def test_album_track_metadata_replicates_to_paired_peer() -> None:
    source = _bandcamp_album_source()
    laptop = DeviceAgent("laptop", priority=1, source=source)
    phone = DeviceAgent("phone", priority=10, source=FakeSource())
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())

    laptop.add_artists(["https://chrishuelsbeck.bandcamp.com/music"])
    laptop.sync()
    phone.sync()

    assert len(phone.mixes()) == 1
    album = phone.mixes()[0]
    assert album.kind is ReleaseKind.ALBUM
    assert album.title == "Turrican Soundtrack"
    assert album.duration_seconds == 1800
    assert album.size_bytes == 3_500_000
    assert [
        (t.platform_id, t.title, t.duration_seconds, t.url, t.size_bytes)
        for t in album.tracks
    ] == [
        (
            "t1",
            "The Great Bath",
            600,
            "https://chrishuelsbeck.bandcamp.com/track/the-great-bath",
            1_000_000,
        ),
        (
            "t2",
            "Turrican Soundtrack Theme",
            900,
            "https://chrishuelsbeck.bandcamp.com/track/turrican-soundtrack-theme",
            2_000_000,
        ),
        (
            "t3",
            "Scores",
            300,
            "https://chrishuelsbeck.bandcamp.com/track/scores",
            500_000,
        ),
    ]
    assert phone.files() == []
    assert source.fetch_calls == []


def test_refresh_artists_adds_new_album_releases() -> None:
    source = FakeSource()
    source.add_listing(
        "https://example.bandcamp.com/music",
        ArtistListing(
            platform=Platform.BANDCAMP,
            platform_id="example",
            name="Example",
            url="https://example.bandcamp.com/music",
            uploads=[
                Upload(
                    platform=Platform.BANDCAMP,
                    platform_id="album-a",
                    title="Album A",
                    url="https://example.bandcamp.com/album/a",
                    duration_seconds=0,
                    tracks=(
                        Track(
                            platform_id="a1",
                            title="A1",
                            url="https://example.bandcamp.com/track/a1",
                            duration_seconds=700,
                        ),
                        Track(
                            platform_id="a2",
                            title="A2",
                            url="https://example.bandcamp.com/track/a2",
                            duration_seconds=700,
                        ),
                    ),
                ),
            ],
        ),
    )
    laptop = DeviceAgent("laptop", source=source)
    laptop.add_artists(
        ["https://example.bandcamp.com/music"],
        min_duration_seconds=1200,
    )
    artist_id = laptop.artists()[0].id

    source.add_listing(
        "https://example.bandcamp.com/music",
        ArtistListing(
            platform=Platform.BANDCAMP,
            platform_id="example",
            name="Example",
            url="https://example.bandcamp.com/music",
            uploads=[
                Upload(
                    platform=Platform.BANDCAMP,
                    platform_id="album-a",
                    title="Album A",
                    url="https://example.bandcamp.com/album/a",
                    duration_seconds=0,
                    tracks=(
                        Track(
                            platform_id="a1",
                            title="A1",
                            url="https://example.bandcamp.com/track/a1",
                            duration_seconds=700,
                        ),
                        Track(
                            platform_id="a2",
                            title="A2",
                            url="https://example.bandcamp.com/track/a2",
                            duration_seconds=700,
                        ),
                    ),
                ),
                Upload(
                    platform=Platform.BANDCAMP,
                    platform_id="album-b",
                    title="Album B",
                    url="https://example.bandcamp.com/album/b",
                    duration_seconds=0,
                    tracks=(
                        Track(
                            platform_id="b1",
                            title="B1",
                            url="https://example.bandcamp.com/track/b1",
                            duration_seconds=800,
                        ),
                        Track(
                            platform_id="b2",
                            title="B2",
                            url="https://example.bandcamp.com/track/b2",
                            duration_seconds=800,
                        ),
                    ),
                ),
            ],
        ),
    )
    added = laptop.refresh_artists([artist_id], min_duration_seconds=1200)

    assert [m.title for m in added] == ["Album B"]
    assert {m.title for m in laptop.mixes()} == {"Album A", "Album B"}
    assert all(m.kind is ReleaseKind.ALBUM for m in laptop.mixes())
