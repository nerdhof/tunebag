"""Unit tests for Playback supervision (fake clock + NullPlayer, no DeviceAgent)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from tunebag.domain import AlbumTrack, Mix, Platform, ReleaseKind, new_id
from tunebag.playback import (
    ContinueTo,
    EmitLastHeard,
    MarkPlayed,
    PlaybackSupervisor,
    ReportPlayhead,
    last_heard_threshold,
)
from tunebag.player import NullPlayer


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 1, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class _RecordingPlayer(NullPlayer):
    def __init__(self) -> None:
        super().__init__()
        self.plays: list[tuple[Path, float]] = []

    def play(self, path: Path, *, start_seconds: float = 0) -> None:
        super().play(path, start_seconds=start_seconds)
        self.plays.append((path, start_seconds))

    def finish(self) -> None:
        self._alive = False


def _mix(*, duration: int = 100, mix_id: UUID | None = None) -> Mix:
    return Mix(
        id=mix_id or new_id(),
        artist_id=new_id(),
        platform=Platform.SOUNDCLOUD,
        platform_id="mix-1",
        title="Set",
        url="https://example.com/mix",
        duration_seconds=duration,
        size_bytes=10,
    )


def _album(*, mix_id: UUID | None = None) -> Mix:
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
        AlbumTrack(
            platform_id="t3",
            title="Three",
            url="https://example.com/t3",
            duration_seconds=30,
            size_bytes=5,
        ),
    )
    return Mix(
        id=mix_id or new_id(),
        artist_id=new_id(),
        platform=Platform.BANDCAMP,
        platform_id="album-1",
        title="Disc",
        url="https://example.com/album",
        duration_seconds=180,
        size_bytes=35,
        kind=ReleaseKind.ALBUM,
        tracks=list(tracks),
    )


def _supervisor(
    tmp_path: Path,
    *,
    clock: FakeClock | None = None,
    player: _RecordingPlayer | None = None,
) -> tuple[PlaybackSupervisor, _RecordingPlayer, FakeClock, dict[UUID, list[Path]]]:
    clk = clock or FakeClock()
    rec = player or _RecordingPlayer()
    files: dict[UUID, list[Path]] = {}

    def locate(mix: Mix, timeline: float) -> tuple[Path, float]:
        paths = files[mix.id]
        if mix.kind is ReleaseKind.ALBUM:
            from tunebag.release_layout import album_timeline_location

            index, offset = album_timeline_location(mix, timeline)
            return paths[index], offset
        return paths[0], float(timeline)

    return PlaybackSupervisor(rec, clk, locate_audio=locate), rec, clk, files


def test_note_position_emits_last_heard_on_rising_edge(tmp_path: Path) -> None:
    mix = _mix(duration=1000)
    # 2% of 1000 = 20; cap is 10 → threshold 10.
    assert last_heard_threshold(1000) == 10.0
    supervisor, _player, _clock, files = _supervisor(tmp_path)
    path = tmp_path / "mix.bin"
    path.write_bytes(b"audio")
    files[mix.id] = [path]
    intent_id = new_id()
    supervisor.start(mix, 0.0, intent_id=intent_id, continue_next_id=None)

    below = supervisor.note_position(mix, 9.0, previous_position=0.0)
    assert [type(i) for i in below] == [ReportPlayhead]
    assert below[0].position_seconds == 9.0  # type: ignore[union-attr]

    cross = supervisor.note_position(mix, 10.0, previous_position=9.0)
    assert [type(i) for i in cross] == [ReportPlayhead, EmitLastHeard]
    assert isinstance(cross[1], EmitLastHeard)
    assert cross[1].mix_id == mix.id

    again = supervisor.note_position(mix, 11.0, previous_position=10.0)
    assert [type(i) for i in again] == [ReportPlayhead]


def test_note_position_marks_played_at_75_percent(tmp_path: Path) -> None:
    mix = _mix(duration=100)
    supervisor, _player, _clock, files = _supervisor(tmp_path)
    path = tmp_path / "mix.bin"
    path.write_bytes(b"audio")
    files[mix.id] = [path]
    supervisor.start(mix, 0.0, intent_id=new_id(), continue_next_id=None)

    under = supervisor.note_position(mix, 74.0, previous_position=0.0)
    assert not any(isinstance(i, MarkPlayed) for i in under)

    over = supervisor.note_position(mix, 75.0, previous_position=74.0)
    assert any(isinstance(i, MarkPlayed) for i in over)
    played = next(i for i in over if isinstance(i, MarkPlayed))
    assert played.mix_id == mix.id


def test_album_track_end_advances_and_reports_timeline(tmp_path: Path) -> None:
    album = _album()
    supervisor, player, _clock, files = _supervisor(tmp_path)
    track_paths = []
    for i in range(3):
        p = tmp_path / f"t{i}.bin"
        p.write_bytes(f"track-{i}".encode())
        track_paths.append(p)
    files[album.id] = track_paths
    supervisor.start(album, 0.0, intent_id=new_id(), continue_next_id=None)
    assert player.plays[-1] == (track_paths[0], 0.0)

    player.finish()
    intents = supervisor.supervise(album, previous_position=0.0)

    assert player.plays[-1] == (track_paths[1], 0.0)
    assert supervisor.album_index == 1
    assert supervisor.playing is True
    # Timeline 60 crosses Last heard threshold min(10, 2% of 180)=3.6.
    assert [type(i) for i in intents] == [ReportPlayhead, EmitLastHeard]
    assert intents[0].position_seconds == 60.0  # type: ignore[union-attr]


def test_album_end_emits_continue_to(tmp_path: Path) -> None:
    album = _album()
    next_id = new_id()
    intent_id = new_id()
    supervisor, player, _clock, files = _supervisor(tmp_path)
    track_paths = []
    for i in range(3):
        p = tmp_path / f"t{i}.bin"
        p.write_bytes(f"track-{i}".encode())
        track_paths.append(p)
    files[album.id] = track_paths
    supervisor.start(
        album, 0.0, intent_id=intent_id, continue_next_id=next_id
    )
    # Finish track 0 → 1, track 1 → 2, track 2 → end.
    for _ in range(2):
        player.finish()
        supervisor.supervise(album, previous_position=0.0)

    player.finish()
    intents = supervisor.supervise(album, previous_position=150.0)

    assert supervisor.playing is False
    assert any(isinstance(i, ReportPlayhead) for i in intents)
    assert any(isinstance(i, MarkPlayed) for i in intents)  # 180 >= 75% of 180
    cont = next(i for i in intents if isinstance(i, ContinueTo))
    assert cont.intent_id == intent_id
    assert cont.mix_id == next_id
    end_report = next(i for i in intents if isinstance(i, ReportPlayhead))
    assert end_report.position_seconds == 180.0


def test_mix_end_uses_fallback_next_when_stash_cleared(tmp_path: Path) -> None:
    mix = _mix(duration=50)
    fallback = new_id()
    intent_id = new_id()
    supervisor, player, _clock, files = _supervisor(tmp_path)
    path = tmp_path / "mix.bin"
    path.write_bytes(b"audio")
    files[mix.id] = [path]
    supervisor.start(mix, 0.0, intent_id=intent_id, continue_next_id=None)

    player.finish()
    intents = supervisor.supervise(
        mix, previous_position=0.0, fallback_next_id=fallback
    )

    cont = next(i for i in intents if isinstance(i, ContinueTo))
    assert cont.mix_id == fallback
    assert cont.intent_id == intent_id


def test_live_position_advances_with_clock(tmp_path: Path) -> None:
    mix = _mix(duration=3600)
    clock = FakeClock()
    supervisor, _player, _clock, files = _supervisor(tmp_path, clock=clock)
    path = tmp_path / "mix.bin"
    path.write_bytes(b"audio")
    files[mix.id] = [path]
    supervisor.start(mix, 100.0, intent_id=new_id(), continue_next_id=None)

    clock.advance(12.5)
    assert supervisor.live_position(mix) == 112.5
