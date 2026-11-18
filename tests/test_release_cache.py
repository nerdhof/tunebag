"""Unit tests for Release Cache + layout (fake fetch ports, no DeviceAgent fill)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from tunebag.domain import (
    AlbumTrack,
    Artist,
    Mix,
    Platform,
    ReleaseKind,
    new_id,
)
from tunebag.projection import CatalogState
from tunebag.release_cache import ReleaseCache
from tunebag.release_layout import (
    album_timeline_location,
    album_track_filename,
    album_track_path,
    blob_path,
)


def _mix(*, mix_id: UUID | None = None, title: str = "Set") -> Mix:
    artist_id = new_id()
    return Mix(
        id=mix_id or new_id(),
        artist_id=artist_id,
        platform=Platform.SOUNDCLOUD,
        platform_id="mix-1",
        title=title,
        url="https://example.com/mix",
        duration_seconds=3600,
        size_bytes=100,
    )


def _album(*, mix_id: UUID | None = None) -> Mix:
    artist_id = new_id()
    tracks = (
        AlbumTrack(
            platform_id="t1",
            title="One",
            url="https://example.com/t1",
            duration_seconds=60,
            size_bytes=10,
        ),
        AlbumTrack(
            platform_id="t2",
            title="Two",
            url="https://example.com/t2",
            duration_seconds=90,
            size_bytes=20,
        ),
    )
    return Mix(
        id=mix_id or new_id(),
        artist_id=artist_id,
        platform=Platform.BANDCAMP,
        platform_id="album-1",
        title="Disc",
        url="https://example.com/album",
        duration_seconds=150,
        size_bytes=30,
        kind=ReleaseKind.ALBUM,
        tracks=tracks,
    )


def _seed(catalog: CatalogState, mix: Mix) -> None:
    catalog.artists[mix.artist_id] = Artist(
        id=mix.artist_id,
        platform=mix.platform,
        platform_id=f"artist:{mix.platform_id}",
        name="Artist",
        url="https://example.com/artist",
    )
    catalog.mixes[mix.id] = mix


class _FakePeer:
    def __init__(
        self,
        name: str = "peer",
        *,
        mixes: dict[UUID, bytes] | None = None,
        albums: dict[UUID, list[bytes]] | None = None,
    ) -> None:
        self.name = name
        self._mixes = mixes or {}
        self._albums = albums or {}

    def file_bytes(self, mix_id: UUID) -> bytes | None:
        return self._mixes.get(mix_id)

    def album_track_bytes(self, mix_id: UUID) -> list[bytes] | None:
        return self._albums.get(mix_id)


class _FakeOrigin:
    def __init__(
        self,
        *,
        mixes: dict[UUID, bytes] | None = None,
        albums: dict[UUID, list[bytes]] | None = None,
        fail_album_after: int | None = None,
    ) -> None:
        self._mixes = mixes or {}
        self._albums = albums or {}
        self._fail_album_after = fail_album_after
        self.mix_fetches = 0
        self.album_fetches = 0

    def fetch_mix(self, mix: Mix) -> bytes:
        self.mix_fetches += 1
        return self._mixes[mix.id]

    def fetch_album(self, mix: Mix) -> list[bytes]:
        self.album_fetches += 1
        payloads = self._albums[mix.id]
        if self._fail_album_after is not None:
            raise RuntimeError("origin album fetch failed")
        return payloads


def test_album_timeline_location_maps_across_tracks() -> None:
    album = _album()
    assert album_timeline_location(album, 0.0) == (0, 0.0)
    assert album_timeline_location(album, 30.0) == (0, 30.0)
    assert album_timeline_location(album, 60.0) == (1, 0.0)
    assert album_timeline_location(album, 100.0) == (1, 40.0)
    assert album_timeline_location(album, 999.0) == (1, 90.0)


def test_ensure_complete_mix_from_origin(tmp_path: Path) -> None:
    catalog = CatalogState(data_dir=tmp_path)
    mix = _mix()
    _seed(catalog, mix)
    cache = ReleaseCache(tmp_path, catalog)
    origin = _FakeOrigin(mixes={mix.id: b"audio-mix"})
    notes: list[str] = []

    cache.ensure_complete(
        mix,
        peers=[],
        origin=origin,
        still_assigned=lambda: True,
        note=notes.append,
    )

    assert cache.has(mix.id)
    assert cache.mix_bytes(mix.id) == b"audio-mix"
    assert blob_path(tmp_path, mix.id).is_file()
    assert origin.mix_fetches == 1
    assert any("download from origin" in n for n in notes)


def test_ensure_complete_mix_prefers_peer_over_origin(tmp_path: Path) -> None:
    catalog = CatalogState(data_dir=tmp_path)
    mix = _mix()
    _seed(catalog, mix)
    cache = ReleaseCache(tmp_path, catalog)
    peer = _FakePeer(mixes={mix.id: b"from-peer"})
    origin = _FakeOrigin(mixes={mix.id: b"from-origin"})

    cache.ensure_complete(
        mix,
        peers=[peer],
        origin=origin,
        still_assigned=lambda: True,
    )

    assert cache.mix_bytes(mix.id) == b"from-peer"
    assert origin.mix_fetches == 0


def test_ensure_complete_skips_when_unassigned(tmp_path: Path) -> None:
    catalog = CatalogState(data_dir=tmp_path)
    mix = _mix()
    _seed(catalog, mix)
    cache = ReleaseCache(tmp_path, catalog)
    origin = _FakeOrigin(mixes={mix.id: b"audio"})

    cache.ensure_complete(
        mix,
        peers=[],
        origin=origin,
        still_assigned=lambda: False,
    )

    assert not cache.has(mix.id)
    assert origin.mix_fetches == 0


def test_ensure_complete_album_all_or_nothing(tmp_path: Path) -> None:
    catalog = CatalogState(data_dir=tmp_path)
    album = _album()
    _seed(catalog, album)
    cache = ReleaseCache(tmp_path, catalog)
    payloads = [b"track-a", b"track-b"]
    origin = _FakeOrigin(albums={album.id: payloads})

    cache.ensure_complete(
        album,
        peers=[],
        origin=origin,
        still_assigned=lambda: True,
    )

    assert cache.has(album.id)
    assert cache.album_bytes(album.id) == payloads
    assert album_track_path(tmp_path, album, 0).read_bytes() == b"track-a"
    assert album_track_path(tmp_path, album, 1).read_bytes() == b"track-b"
    # Incomplete single-track leftovers are not treated as present.
    cache.remove(album.id)
    partial = blob_path(tmp_path, album.id)
    partial.mkdir(parents=True)
    (partial / album_track_filename(0, album.tracks[0])).write_bytes(b"only-one")
    assert not cache.has(album.id)


def test_ensure_complete_album_origin_failure_clears_incomplete(tmp_path: Path) -> None:
    catalog = CatalogState(data_dir=tmp_path)
    album = _album()
    _seed(catalog, album)
    cache = ReleaseCache(tmp_path, catalog)
    # Leave a fake incomplete dir as if a prior attempt died mid-write.
    leftover = blob_path(tmp_path, album.id)
    leftover.mkdir(parents=True)
    (leftover / "junk.bin").write_bytes(b"partial")
    origin = _FakeOrigin(albums={album.id: [b"a", b"b"]}, fail_album_after=0)

    with pytest.raises(RuntimeError, match="origin album fetch failed"):
        cache.ensure_complete(
            album,
            peers=[],
            origin=origin,
            still_assigned=lambda: True,
        )

    assert not leftover.exists()
    assert not cache.has(album.id)


def test_ensure_complete_waits_when_origin_none(tmp_path: Path) -> None:
    catalog = CatalogState(data_dir=tmp_path)
    mix = _mix()
    _seed(catalog, mix)
    cache = ReleaseCache(tmp_path, catalog)

    cache.ensure_complete(
        mix,
        peers=[],
        origin=None,
        still_assigned=lambda: True,
    )

    assert not cache.has(mix.id)


def test_refresh_intent_folders_links_mix_and_album(tmp_path: Path) -> None:
    catalog = CatalogState(data_dir=tmp_path)
    mix = _mix(title="Solo")
    album = _album()
    _seed(catalog, mix)
    _seed(catalog, album)
    cache = ReleaseCache(tmp_path, catalog)
    cache.store_mix(mix.id, b"mix-bytes")
    cache.store_album(album, [b"a", b"b"])
    intent_id = uuid4()

    cache.refresh_intent_folders(
        [intent_id],
        lambda _iid: [mix.id, album.id],
    )

    folder = cache.intent_folder(intent_id)
    names = sorted(p.name for p in folder.iterdir())
    assert len(names) == 2
    album_dir = next(p for p in folder.iterdir() if p.is_dir())
    assert sorted(p.name for p in album_dir.iterdir()) == [
        album_track_filename(0, album.tracks[0]),
        album_track_filename(1, album.tracks[1]),
    ]
