"""Issue 02: Album Cache fill + intent folders — DeviceAgent + FakeSource."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, ReleaseKind, Stars
from tunebag.source import ArtistListing, FakeSource, Track, Upload


def _pair(
    tmp_path: Path,
    *,
    source: FakeSource | None = None,
) -> tuple[DeviceAgent, DeviceAgent, FakeSource]:
    src = source or FakeSource()
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=tmp_path / "laptop",
    )
    phone = DeviceAgent(
        "phone",
        priority=10,
        source=src,
        data_dir=tmp_path / "phone",
    )
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    return laptop, phone, src


def _bandcamp_album_source() -> FakeSource:
    source = FakeSource()
    track_urls = (
        "https://chrishuelsbeck.bandcamp.com/track/the-great-bath",
        "https://chrishuelsbeck.bandcamp.com/track/turrican-soundtrack-theme",
        "https://chrishuelsbeck.bandcamp.com/track/scores",
    )
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
                            url=track_urls[0],
                            duration_seconds=600,
                            size_bytes=1_000_000,
                        ),
                        Track(
                            platform_id="t2",
                            title="Turrican Soundtrack Theme",
                            url=track_urls[1],
                            duration_seconds=900,
                            size_bytes=2_000_000,
                        ),
                        Track(
                            platform_id="t3",
                            title="Scores",
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
    return source


def _add_and_assign_album(
    laptop: DeviceAgent, source: FakeSource
) -> tuple[UUID, UUID]:
    added = laptop.add_artists(["https://chrishuelsbeck.bandcamp.com/music"])
    assert len(added) == 1
    album = added[0]
    assert album.kind is ReleaseKind.ALBUM
    laptop.rate_mix(album.id, Stars.FIVE)
    intent = laptop.create_intent(
        "Album plan",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    assignment = laptop.assignment(intent.id)
    assert assignment is not None
    assert album.id in assignment.mix_ids
    # add_artists may start a background fill; settle before explicit fill_caches.
    laptop.wait_for_fill()
    return album.id, intent.id


def test_album_fill_fetches_each_track_into_one_cache_directory(tmp_path: Path) -> None:
    source = _bandcamp_album_source()
    laptop, _phone, _ = _pair(tmp_path, source=source)
    album_id, _intent_id = _add_and_assign_album(laptop, source)

    laptop.fill_caches()

    assert album_id in {m.id for m in laptop.files()}
    assert source.fetch_calls == [
        "https://chrishuelsbeck.bandcamp.com/track/the-great-bath",
        "https://chrishuelsbeck.bandcamp.com/track/turrican-soundtrack-theme",
        "https://chrishuelsbeck.bandcamp.com/track/scores",
    ]
    cache_dir = tmp_path / "laptop" / "blobs" / str(album_id)
    assert cache_dir.is_dir()
    track_files = sorted(p.name for p in cache_dir.iterdir() if p.is_file())
    assert len(track_files) == 3
    assert [
        (cache_dir / name).read_bytes() for name in track_files
    ] == [
        source.bytes_by_url[
            "https://chrishuelsbeck.bandcamp.com/track/the-great-bath"
        ],
        source.bytes_by_url[
            "https://chrishuelsbeck.bandcamp.com/track/turrican-soundtrack-theme"
        ],
        source.bytes_by_url["https://chrishuelsbeck.bandcamp.com/track/scores"],
    ]


def test_failed_album_fill_leaves_album_absent_and_clears_partial_dir(
    tmp_path: Path,
) -> None:
    source = _bandcamp_album_source()
    # Second track missing — fill must fail mid-album.
    del source.bytes_by_url[
        "https://chrishuelsbeck.bandcamp.com/track/turrican-soundtrack-theme"
    ]
    laptop, _phone, _ = _pair(tmp_path, source=source)
    album_id, _intent_id = _add_and_assign_album(laptop, source)

    laptop.fill_caches()

    assert album_id not in {m.id for m in laptop.files()}
    assert laptop.file_bytes(album_id) is None
    assert laptop.album_track_bytes(album_id) is None
    blobs = tmp_path / "laptop" / "blobs"
    cache_dir = blobs / str(album_id)
    assert not cache_dir.exists()
    assert not any(
        p.name.startswith(f".{album_id}.") and p.name.endswith(".partial")
        for p in blobs.iterdir()
    ) if blobs.is_dir() else True
    assert (
        "https://chrishuelsbeck.bandcamp.com/track/the-great-bath"
        in source.fetch_calls
    )
    assert (
        "https://chrishuelsbeck.bandcamp.com/track/turrican-soundtrack-theme"
        in source.fetch_calls
    )


def test_incomplete_album_directory_does_not_count_as_present(tmp_path: Path) -> None:
    source = _bandcamp_album_source()
    laptop, _phone, _ = _pair(tmp_path, source=source)
    album_id, _intent_id = _add_and_assign_album(laptop, source)
    album = laptop.catalog.mixes[album_id]
    cache_dir = tmp_path / "laptop" / "blobs" / str(album_id)
    cache_dir.mkdir(parents=True)
    # Only the first track file — incomplete disc.
    first = album.tracks[0]
    (cache_dir / f"01-{first.title}-{first.platform_id}.bin").write_bytes(b"partial")

    assert album_id not in {m.id for m in laptop.files()}
    assert laptop.album_track_bytes(album_id) is None


def test_fill_cleans_incomplete_album_dir_then_retries(tmp_path: Path) -> None:
    source = _bandcamp_album_source()
    laptop, _phone, _ = _pair(tmp_path, source=source)
    album_id, _intent_id = _add_and_assign_album(laptop, source)
    album = laptop.catalog.mixes[album_id]
    cache_dir = tmp_path / "laptop" / "blobs" / str(album_id)
    cache_dir.mkdir(parents=True)
    first = album.tracks[0]
    (cache_dir / f"01-{first.title}-{first.platform_id}.bin").write_bytes(b"partial")
    source.fetch_calls.clear()

    laptop.fill_caches()

    assert album_id in {m.id for m in laptop.files()}
    assert laptop.album_track_bytes(album_id) == [
        source.bytes_by_url[
            "https://chrishuelsbeck.bandcamp.com/track/the-great-bath"
        ],
        source.bytes_by_url[
            "https://chrishuelsbeck.bandcamp.com/track/turrican-soundtrack-theme"
        ],
        source.bytes_by_url["https://chrishuelsbeck.bandcamp.com/track/scores"],
    ]
    assert not any(
        p.read_bytes() == b"partial" for p in cache_dir.iterdir() if p.is_file()
    )


def test_intent_folder_places_mix_as_file_and_album_as_subfolder(
    tmp_path: Path,
) -> None:
    source = _bandcamp_album_source()
    mix_url = "https://example.com/dj-set"
    source.bytes_by_url[mix_url] = b"audio:dj-set"
    laptop, _phone, _ = _pair(tmp_path, source=source)
    added = laptop.add_artists(["https://chrishuelsbeck.bandcamp.com/music"])
    album = added[0]
    mix = laptop.add_mix(
        title="DJ Set",
        url=mix_url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="dj-set",
        artist_name="DJ Example",
    )
    laptop.rate_mix(album.id, Stars.FIVE)
    laptop.rate_mix(mix.id, Stars.FIVE)
    intent = laptop.create_intent(
        "Mixed plan",
        seed=1,
        device_hours=[(laptop.device_id, 7200)],
    )
    # add_artists may have kicked a background fill — wait so we don't race.
    laptop.wait_for_fill()

    laptop.fill_caches()

    folder = laptop.intent_folder(intent.id)
    mix_files = [p for p in folder.iterdir() if p.is_file()]
    album_dirs = [p for p in folder.iterdir() if p.is_dir()]
    assert len(mix_files) == 1
    assert mix_files[0].read_bytes() == b"audio:dj-set"
    assert len(album_dirs) == 1
    track_files = sorted(album_dirs[0].iterdir(), key=lambda p: p.name)
    assert len(track_files) == 3
    assert [p.read_bytes() for p in track_files] == [
        source.bytes_by_url[
            "https://chrishuelsbeck.bandcamp.com/track/the-great-bath"
        ],
        source.bytes_by_url[
            "https://chrishuelsbeck.bandcamp.com/track/turrican-soundtrack-theme"
        ],
        source.bytes_by_url["https://chrishuelsbeck.bandcamp.com/track/scores"],
    ]
    assert {m.id for m in laptop.files()} >= {album.id, mix.id}


def test_phone_copies_complete_album_from_laptop_not_origin(tmp_path: Path) -> None:
    source = _bandcamp_album_source()
    laptop, phone, _ = _pair(tmp_path, source=source)
    added = laptop.add_artists(["https://chrishuelsbeck.bandcamp.com/music"])
    album = added[0]
    laptop.rate_mix(album.id, Stars.FIVE)
    intent = laptop.create_intent(
        "Shared album",
        seed=1,
        device_hours=[
            (phone.device_id, 3600),
            (laptop.device_id, 3600),
        ],
    )
    phone.sync()
    laptop.sync()
    laptop.wait_for_fill()
    laptop.fill_caches()
    assert album.id in {m.id for m in laptop.files()}
    source.fetch_calls.clear()

    phone.fill_caches()

    assert album.id in {m.id for m in phone.files()}
    assert source.fetch_calls == []
    phone_tracks = phone.album_track_bytes(album.id)
    assert phone_tracks is not None
    assert phone_tracks == [
        source.bytes_by_url[
            "https://chrishuelsbeck.bandcamp.com/track/the-great-bath"
        ],
        source.bytes_by_url[
            "https://chrishuelsbeck.bandcamp.com/track/turrican-soundtrack-theme"
        ],
        source.bytes_by_url["https://chrishuelsbeck.bandcamp.com/track/scores"],
    ]
    assignment = phone.assignment(intent.id)
    assert assignment is not None
    assert album.id in assignment.mix_ids


def test_partial_peer_album_does_not_copy(tmp_path: Path) -> None:
    source = _bandcamp_album_source()
    laptop, phone, _ = _pair(tmp_path, source=source)
    added = laptop.add_artists(["https://chrishuelsbeck.bandcamp.com/music"])
    album = added[0]
    laptop.rate_mix(album.id, Stars.FIVE)
    laptop.create_intent(
        "Partial peer",
        seed=1,
        device_hours=[
            (phone.device_id, 3600),
            (laptop.device_id, 3600),
        ],
    )
    phone.sync()
    laptop.sync()
    laptop.wait_for_fill()
    # Replace any complete fill with a stranded half-disc (must not copy).
    laptop.remove_local_file(album.id)
    cache_dir = tmp_path / "laptop" / "blobs" / str(album.id)
    cache_dir.mkdir(parents=True)
    first = album.tracks[0]
    (
        cache_dir / f"01-{first.title}-{first.platform_id}.bin"
    ).write_bytes(b"only-one-track")
    assert album.id not in {m.id for m in laptop.files()}
    assert laptop.album_track_bytes(album.id) is None
    source.fetch_calls.clear()

    phone.fill_caches()

    # Preferred peer (laptop) is reachable but incomplete — phone waits, no copy,
    # no origin fetch of a half-disc.
    assert album.id not in {m.id for m in phone.files()}
    assert source.fetch_calls == []
    assert phone.album_track_bytes(album.id) is None


def test_metered_treats_album_like_any_assigned_release(tmp_path: Path) -> None:
    """Metered origin fill: current Album + one ahead; no special Bandcamp policy."""
    source = FakeSource()
    uploads = []
    for n, slug in enumerate(("one", "two", "three"), start=1):
        t1 = f"https://example.bandcamp.com/track/{slug}-a"
        t2 = f"https://example.bandcamp.com/track/{slug}-b"
        uploads.append(
            Upload(
                platform=Platform.BANDCAMP,
                platform_id=f"album-{slug}",
                title=f"Album {n}",
                url=f"https://example.bandcamp.com/album/{slug}",
                duration_seconds=0,
                tracks=(
                    Track(
                        platform_id=f"{slug}-a",
                        title=f"{slug} a",
                        url=t1,
                        duration_seconds=1800,
                    ),
                    Track(
                        platform_id=f"{slug}-b",
                        title=f"{slug} b",
                        url=t2,
                        duration_seconds=1800,
                    ),
                ),
            )
        )
        source.bytes_by_url[t1] = f"audio:{slug}-a".encode()
        source.bytes_by_url[t2] = f"audio:{slug}-b".encode()
    source.add_listing(
        "https://example.bandcamp.com/music",
        ArtistListing(
            platform=Platform.BANDCAMP,
            platform_id="example",
            name="Example",
            url="https://example.bandcamp.com/music",
            uploads=uploads,
        ),
    )
    laptop, _phone, _ = _pair(tmp_path, source=source)
    added = laptop.add_artists(["https://example.bandcamp.com/music"])
    assert len(added) == 3
    for album in added:
        laptop.rate_mix(album.id, Stars.FIVE)
    intent = laptop.create_intent(
        "Metered albums",
        seed=1,
        device_hours=[(laptop.device_id, 10800)],
    )
    assignment = laptop.assignment(intent.id)
    assert assignment is not None
    assert len(assignment.mix_ids) == 3
    first, second, third = assignment.mix_ids
    laptop.wait_for_fill()
    for mix_id in assignment.mix_ids:
        laptop.remove_local_file(mix_id)
    source.fetch_calls.clear()

    laptop.set_metered(True)
    laptop.set_current_mix(first)
    laptop.fill_caches()

    assert {m.id for m in laptop.files()} == {first, second}
    third_urls = [t.url for t in laptop.catalog.mixes[third].tracks]
    assert all(url not in source.fetch_calls for url in third_urls)
