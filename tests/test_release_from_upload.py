"""Unit tests for source.release_from_upload (Upload → Catalog Release)."""

from __future__ import annotations

from uuid import uuid4

from tunebag.domain import Platform, ReleaseKind
from tunebag.source import Track, Upload, release_from_upload

ARTIST_ID = uuid4()
MIN = 20 * 60


def test_mix_upload_maps_to_mix_release() -> None:
    upload = Upload(
        platform=Platform.SOUNDCLOUD,
        platform_id="m1",
        title="Long Set",
        url="https://soundcloud.com/dj/long",
        duration_seconds=3600,
        size_bytes=12_000_000,
        cover_url="https://i1.sndcdn.com/artworks-xyz-t500x500.jpg",
    )
    release = release_from_upload(ARTIST_ID, upload, MIN)
    assert release is not None
    assert release.kind is ReleaseKind.MIX
    assert release.artist_id == ARTIST_ID
    assert release.platform_id == "m1"
    assert release.duration_seconds == 3600
    assert release.size_bytes == 12_000_000
    assert release.cover_url == "https://i1.sndcdn.com/artworks-xyz-t500x500.jpg"
    assert release.tracks == []


def test_short_mix_filtered_out() -> None:
    upload = Upload(
        platform=Platform.HEARTHIS,
        platform_id="s1",
        title="Short",
        url="https://hearthis.at/dj/short/",
        duration_seconds=MIN - 1,
    )
    assert release_from_upload(ARTIST_ID, upload, MIN) is None


def test_album_upload_maps_to_album_release() -> None:
    upload = Upload(
        platform=Platform.BANDCAMP,
        platform_id="a1",
        title="Full Album",
        url="https://example.bandcamp.com/album/full",
        duration_seconds=0,
        tracks=(
            Track(
                platform_id="t1",
                title="One",
                url="https://example.bandcamp.com/track/one",
                duration_seconds=700,
                size_bytes=1_000,
            ),
            Track(
                platform_id="t2",
                title="Two",
                url="https://example.bandcamp.com/track/two",
                duration_seconds=700,
                size_bytes=2_000,
            ),
        ),
    )
    release = release_from_upload(ARTIST_ID, upload, MIN)
    assert release is not None
    assert release.kind is ReleaseKind.ALBUM
    assert release.duration_seconds == 1400
    assert release.size_bytes == 3_000
    assert [(t.platform_id, t.title, t.size_bytes) for t in release.tracks] == [
        ("t1", "One", 1_000),
        ("t2", "Two", 2_000),
    ]


def test_one_track_and_short_album_filtered_out() -> None:
    one_track = Upload(
        platform=Platform.BANDCAMP,
        platform_id="one",
        title="Single",
        url="https://example.bandcamp.com/album/single",
        duration_seconds=0,
        tracks=(
            Track(
                platform_id="t1",
                title="Only",
                url="https://example.bandcamp.com/track/only",
                duration_seconds=3600,
            ),
        ),
    )
    short = Upload(
        platform=Platform.BANDCAMP,
        platform_id="short",
        title="Tiny",
        url="https://example.bandcamp.com/album/tiny",
        duration_seconds=0,
        tracks=(
            Track(
                platform_id="a",
                title="A",
                url="https://example.bandcamp.com/track/a",
                duration_seconds=400,
            ),
            Track(
                platform_id="b",
                title="B",
                url="https://example.bandcamp.com/track/b",
                duration_seconds=400,
            ),
        ),
    )
    assert release_from_upload(ARTIST_ID, one_track, MIN) is None
    assert release_from_upload(ARTIST_ID, short, MIN) is None


def test_album_partial_sizes_yield_none_size_bytes() -> None:
    upload = Upload(
        platform=Platform.YOUTUBE,
        platform_id="OLAK1",
        title="Partial Sizes",
        url="https://www.youtube.com/playlist?list=OLAK1",
        duration_seconds=0,
        tracks=(
            Track(
                platform_id="v1",
                title="A",
                url="https://www.youtube.com/watch?v=v1",
                duration_seconds=700,
                size_bytes=100,
            ),
            Track(
                platform_id="v2",
                title="B",
                url="https://www.youtube.com/watch?v=v2",
                duration_seconds=700,
                size_bytes=None,
            ),
        ),
    )
    release = release_from_upload(ARTIST_ID, upload, MIN)
    assert release is not None
    assert release.size_bytes is None
