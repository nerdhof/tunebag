"""Issue 03: Album play, Playhead, Played, Reject cleanup — DeviceAgent + FakeSource."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, ReleaseKind, Stars
from tunebag.player import NullPlayer
from tunebag.reject import SOFT_REJECT_SECONDS
from tunebag.source import ArtistListing, FakeSource, Track, Upload


class _RecordingPlayer(NullPlayer):
    def __init__(self) -> None:
        super().__init__()
        self.plays: list[tuple[Path, float]] = []
        self.stops = 0

    def play(self, path: Path, *, start_seconds: float = 0) -> None:
        super().play(path, start_seconds=start_seconds)
        self.plays.append((path, start_seconds))

    def stop(self) -> None:
        super().stop()
        self.stops += 1

    def finish(self) -> None:
        """Simulate the current track file ending (external player exits)."""
        self._alive = False


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 1, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _pair(
    tmp_path: Path,
    *,
    source: FakeSource | None = None,
    player: NullPlayer | None = None,
    phone_player: NullPlayer | None = None,
    clock: FakeClock | None = None,
) -> tuple[DeviceAgent, DeviceAgent, FakeSource]:
    src = source or FakeSource()
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=tmp_path / "laptop",
        player=player if player is not None else NullPlayer(),
        clock=clock,
    )
    phone = DeviceAgent(
        "phone",
        priority=10,
        source=src,
        data_dir=tmp_path / "phone",
        player=phone_player if phone_player is not None else NullPlayer(),
        clock=clock,
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
    laptop.wait_for_fill()
    return album.id, intent.id


def _track_path(agent: DeviceAgent, album_id: UUID, index: int) -> Path:
    cache_dir = agent.data_dir / "blobs" / str(album_id)
    track_files = sorted(p for p in cache_dir.iterdir() if p.is_file())
    return track_files[index]


def test_play_album_starts_first_track_file(tmp_path: Path) -> None:
    recorder = _RecordingPlayer()
    source = _bandcamp_album_source()
    laptop, _phone, _ = _pair(tmp_path, source=source, player=recorder)
    album_id, intent_id = _add_and_assign_album(laptop, source)
    laptop.fill_caches()

    laptop.play(intent_id, album_id)

    assert len(recorder.plays) == 1
    path, start = recorder.plays[0]
    assert path == _track_path(laptop, album_id, 0)
    assert path.is_file()
    assert start == 0.0
    assert laptop.is_playing() is True
    assert laptop.current_mix() == album_id


def test_resume_mid_album_maps_timeline_to_track_offset(tmp_path: Path) -> None:
    """Track durations: 600 + 900 + 300. Timeline 650 → track 2 @ 50s."""
    recorder = _RecordingPlayer()
    source = _bandcamp_album_source()
    laptop, _phone, _ = _pair(tmp_path, source=source, player=recorder)
    album_id, intent_id = _add_and_assign_album(laptop, source)
    laptop.fill_caches()
    laptop.play(intent_id, album_id)
    laptop.report_playhead(650)
    laptop.pause()  # keep playhead; Stop would reset to 0

    laptop.play(intent_id, album_id)

    path, start = recorder.plays[-1]
    assert path == _track_path(laptop, album_id, 1)
    assert start == pytest.approx(50.0, abs=0.05)
    head = laptop.playhead(album_id)
    assert head is not None
    assert head.position_seconds == pytest.approx(650.0, abs=0.05)


def test_playhead_sync_lets_peer_resume_mid_album(tmp_path: Path) -> None:
    """Track durations: 600 + 900 + 300. Timeline 650 → track 2 @ 50s on peer."""
    source = _bandcamp_album_source()
    laptop_player = _RecordingPlayer()
    phone_player = _RecordingPlayer()
    laptop, phone, _ = _pair(
        tmp_path,
        source=source,
        player=laptop_player,
        phone_player=phone_player,
    )
    added = laptop.add_artists(["https://chrishuelsbeck.bandcamp.com/music"])
    album_id = added[0].id
    laptop.rate_mix(album_id, Stars.FIVE)
    intent = laptop.create_intent(
        "Shared album",
        seed=1,
        device_hours=[
            (phone.device_id, 3600),
            (laptop.device_id, 3600),
        ],
    )
    phone.sync()
    laptop.wait_for_fill()
    laptop.fill_caches()
    phone.fill_caches()
    laptop.play(intent.id, album_id)
    laptop.report_playhead(650)
    laptop.pause()  # keep playhead for peer resume; Stop would reset to 0
    phone.sync()

    phone.play(intent.id, album_id)

    path, start = phone_player.plays[-1]
    assert path == _track_path(phone, album_id, 1)
    assert start == pytest.approx(50.0, abs=0.05)
    head = phone.playhead(album_id)
    assert head is not None
    assert head.position_seconds == pytest.approx(650.0, abs=0.05)


def test_seek_across_track_boundary_restarts_correct_file(tmp_path: Path) -> None:
    recorder = _RecordingPlayer()
    source = _bandcamp_album_source()
    laptop, _phone, _ = _pair(tmp_path, source=source, player=recorder)
    album_id, intent_id = _add_and_assign_album(laptop, source)
    laptop.fill_caches()
    laptop.play(intent_id, album_id)

    # 600 + 100 = track 2 @ 100s
    head = laptop.seek(700)

    assert head.position_seconds == 700.0
    assert laptop.is_playing() is True
    path, start = recorder.plays[-1]
    assert path == _track_path(laptop, album_id, 1)
    assert start == 100.0


def test_track_end_advances_to_next_catalog_track(tmp_path: Path) -> None:
    recorder = _RecordingPlayer()
    source = _bandcamp_album_source()
    laptop, _phone, _ = _pair(tmp_path, source=source, player=recorder)
    album_id, intent_id = _add_and_assign_album(laptop, source)
    laptop.fill_caches()
    laptop.play(intent_id, album_id)
    assert recorder.plays[-1][0] == _track_path(laptop, album_id, 0)

    recorder.finish()
    assert laptop.is_playing() is True

    assert len(recorder.plays) == 2
    path, start = recorder.plays[-1]
    assert path == _track_path(laptop, album_id, 1)
    assert start == 0.0
    head = laptop.playhead(album_id)
    assert head is not None
    assert head.position_seconds == 600.0


def test_album_end_auto_continues_to_next_local_release(tmp_path: Path) -> None:
    recorder = _RecordingPlayer()
    source = _bandcamp_album_source()
    mix_url = "https://example.com/set-after-album"
    source.bytes_by_url[mix_url] = b"mix-audio"
    laptop, _phone, _ = _pair(tmp_path, source=source, player=recorder)
    album = laptop.add_artists(["https://chrishuelsbeck.bandcamp.com/music"])[0]
    other = laptop.add_mix(
        title="DJ Set",
        url=mix_url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="set-after-album",
        artist_name="DJ Example",
    )
    laptop.rate_mix(album.id, Stars.FIVE)
    laptop.rate_mix(other.id, Stars.FIVE)
    # Pick a seed where the album is not last so natural end has a next local.
    intent = None
    assignment = None
    for seed in range(1, 64):
        candidate = laptop.create_intent(
            f"Album then mix {seed}",
            seed=seed,
            device_hours=[(laptop.device_id, 7200)],
        )
        assigned = laptop.assignment(candidate.id)
        if (
            assigned is not None
            and set(assigned.mix_ids) == {album.id, other.id}
            and assigned.mix_ids.index(album.id) < assigned.mix_ids.index(other.id)
        ):
            intent = candidate
            assignment = assigned
            break
    assert intent is not None and assignment is not None
    laptop.wait_for_fill()
    laptop.fill_caches()

    laptop.play(intent.id, album.id)
    # Three tracks: finish each until album completes.
    recorder.finish()
    assert laptop.is_playing() is True
    assert laptop.current_mix() == album.id
    recorder.finish()
    assert laptop.is_playing() is True
    assert laptop.current_mix() == album.id
    recorder.finish()

    assert laptop.is_playing() is True
    assert laptop.current_mix() == other.id
    finished = next(m for m in laptop.mixes() if m.id == album.id)
    assert finished.played is True
    assert finished.skipped is False
    assert len(laptop.pending_skips()) == 0
    album_head = laptop.playhead(album.id)
    assert album_head is not None
    assert album_head.position_seconds == float(album.duration_seconds)
    assert recorder.plays[-1][0] == tmp_path / "laptop" / "blobs" / str(other.id)


def test_mid_album_playhead_does_not_mark_played(tmp_path: Path) -> None:
    """Mid-timeline playhead never completes an Album; Played waits for natural end."""
    source = _bandcamp_album_source()
    laptop, _phone, _ = _pair(tmp_path, source=source)
    album_id, intent_id = _add_and_assign_album(laptop, source)
    laptop.fill_caches()
    laptop.play(intent_id, album_id)

    laptop.report_playhead(1350)
    album = next(m for m in laptop.mixes() if m.id == album_id)
    assert album.played is False
    assert album.last_heard_at is None
    assert album.kind is ReleaseKind.ALBUM
    assert laptop.is_playing() is True
    assert laptop.current_mix() == album_id


def test_explicit_mark_played_applies_to_whole_album(tmp_path: Path) -> None:
    source = _bandcamp_album_source()
    laptop, _phone, _ = _pair(tmp_path, source=source)
    album_id, intent_id = _add_and_assign_album(laptop, source)
    laptop.fill_caches()
    laptop.play(intent_id, album_id)

    laptop.mark_played()

    assert next(m for m in laptop.mixes() if m.id == album_id).played is True
    assert laptop.is_playing() is True


def test_tag_skip_reject_apply_to_whole_album_only(tmp_path: Path) -> None:
    recorder = _RecordingPlayer()
    source = _bandcamp_album_source()
    laptop, _phone, _ = _pair(tmp_path, source=source, player=recorder)
    album = laptop.add_artists(["https://chrishuelsbeck.bandcamp.com/music"])[0]
    mix_url = "https://example.com/set-a"
    source.bytes_by_url[mix_url] = b"mix-audio"
    other = laptop.add_mix(
        title="DJ Set",
        url=mix_url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="set-a",
        artist_name="DJ Example",
    )
    laptop.rate_mix(album.id, Stars.FIVE)
    laptop.rate_mix(other.id, Stars.FIVE)
    intent = laptop.create_intent(
        "Albums",
        seed=1,
        device_hours=[(laptop.device_id, 7200)],
    )
    laptop.tag_mix(album.id, ["soundtrack"])
    laptop.wait_for_fill()
    laptop.fill_caches()
    assignment = laptop.assignment(intent.id)
    assert assignment is not None
    assert set(assignment.mix_ids) == {album.id, other.id}
    laptop.play(intent.id, album.id)

    skipped = laptop.skip()
    assert skipped.id == other.id
    assert next(m for m in laptop.mixes() if m.id == album.id).played is False
    assert next(m for m in laptop.mixes() if m.id == album.id).tags == ["soundtrack"]

    laptop.reject_mix(album.id)
    assert laptop.catalog.mixes[album.id].rejected is True
    assert laptop.catalog.mixes[album.id].rejected_at is not None


def test_committed_reject_deletes_album_track_dir_on_every_device(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    source = _bandcamp_album_source()
    laptop, phone, _ = _pair(tmp_path, source=source, clock=clock)
    added = laptop.add_artists(["https://chrishuelsbeck.bandcamp.com/music"])
    album = added[0]
    album_id = album.id
    laptop.rate_mix(album_id, Stars.FIVE)
    laptop.create_intent(
        "Shared album",
        seed=1,
        device_hours=[
            (phone.device_id, 3600),
            (laptop.device_id, 3600),
        ],
    )
    phone.sync()
    laptop.wait_for_fill()
    laptop.fill_caches()
    phone.fill_caches()
    assert album_id in {m.id for m in laptop.files()}
    assert album_id in {m.id for m in phone.files()}
    laptop_dir = tmp_path / "laptop" / "blobs" / str(album_id)
    phone_dir = tmp_path / "phone" / "blobs" / str(album_id)
    assert laptop_dir.is_dir()
    assert phone_dir.is_dir()

    laptop.reject_mix(album_id)
    assert album_id in {m.id for m in laptop.files()}
    clock.advance(SOFT_REJECT_SECONDS)
    laptop.commit_reject_file_deletes()
    phone.sync()
    phone.commit_reject_file_deletes()

    assert laptop.catalog.mixes[album_id].rejected is True
    assert phone.catalog.mixes[album_id].rejected is True
    assert album_id not in {m.id for m in laptop.files()}
    assert album_id not in {m.id for m in phone.files()}
    assert not laptop_dir.exists()
    assert not phone_dir.exists()
