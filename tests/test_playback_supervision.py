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


def test_note_position_mid_play_is_playhead_only(tmp_path: Path) -> None:
    mix = _mix(duration=1000)
    supervisor, _player, _clock, files = _supervisor(tmp_path)
    path = tmp_path / "mix.bin"
    path.write_bytes(b"audio")
    files[mix.id] = [path]
    supervisor.start(mix, 0.0, intent_id=new_id(), continue_next_id=None)

    intents = supervisor.note_position(mix, 500.0, previous_position=0.0)
    assert [type(i) for i in intents] == [ReportPlayhead]
    assert intents[0].position_seconds == 500.0  # type: ignore[union-attr]
    assert not any(isinstance(i, EmitLastHeard) for i in intents)
    assert not any(isinstance(i, MarkPlayed) for i in intents)


def test_release_end_emits_last_heard_and_played(tmp_path: Path) -> None:
    mix = _mix(duration=100)
    supervisor, player, _clock, files = _supervisor(tmp_path)
    path = tmp_path / "mix.bin"
    path.write_bytes(b"audio")
    files[mix.id] = [path]
    supervisor.start(mix, 0.0, intent_id=new_id(), continue_next_id=None)

    player.finish()
    intents = supervisor.supervise(mix, previous_position=40.0)

    assert supervisor.playing is False
    assert [type(i) for i in intents] == [
        ReportPlayhead,
        EmitLastHeard,
        MarkPlayed,
    ]
    assert intents[0].position_seconds == 100.0  # type: ignore[union-attr]
    assert intents[1].mix_id == mix.id  # type: ignore[union-attr]
    assert intents[2].mix_id == mix.id  # type: ignore[union-attr]


def test_album_track_end_advances_without_completion(tmp_path: Path) -> None:
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
    # Mid-album advance: playhead only (completion waits for last track).
    assert [type(i) for i in intents] == [ReportPlayhead]
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
    assert [type(i) for i in intents] == [
        ReportPlayhead,
        EmitLastHeard,
        ContinueTo,
        MarkPlayed,
    ]
    cont = next(i for i in intents if isinstance(i, ContinueTo))
    assert cont.intent_id == intent_id
    assert cont.mix_id == next_id
    end_report = next(i for i in intents if isinstance(i, ReportPlayhead))
    assert end_report.position_seconds == 180.0


def test_mix_end_emits_continue_before_mark_played(tmp_path: Path) -> None:
    mix = _mix(duration=50)
    next_id = new_id()
    intent_id = new_id()
    supervisor, player, _clock, files = _supervisor(tmp_path)
    path = tmp_path / "mix.bin"
    path.write_bytes(b"audio")
    files[mix.id] = [path]
    supervisor.start(mix, 0.0, intent_id=intent_id, continue_next_id=next_id)

    player.finish()
    intents = supervisor.supervise(mix, previous_position=0.0)

    assert [type(i) for i in intents] == [
        ReportPlayhead,
        EmitLastHeard,
        ContinueTo,
        MarkPlayed,
    ]
    cont = next(i for i in intents if isinstance(i, ContinueTo))
    assert cont.intent_id == intent_id
    assert cont.mix_id == next_id


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


def test_stop_clears_playing_before_player_die_so_supervise_is_noop(
    tmp_path: Path,
) -> None:
    """User Stop must not race into natural-end MarkPlayed while child dies."""
    mix = _mix(duration=100)
    next_id = new_id()
    intent_id = new_id()
    supervisor, player, _clock, files = _supervisor(tmp_path)
    path = tmp_path / "mix.bin"
    path.write_bytes(b"audio")
    files[mix.id] = [path]
    supervisor.start(mix, 0.0, intent_id=intent_id, continue_next_id=next_id)

    # Simulate stop's ordering: playing cleared, then child exits.
    supervisor.playing = False
    player.finish()
    intents = supervisor.supervise(mix, previous_position=10.0)
    assert intents == []
    assert not any(isinstance(i, MarkPlayed) for i in intents)


def test_pause_audio_does_not_natural_end_via_supervise(tmp_path: Path) -> None:
    mix = _mix(duration=100)
    supervisor, player, _clock, files = _supervisor(tmp_path)
    path = tmp_path / "mix.bin"
    path.write_bytes(b"audio")
    files[mix.id] = [path]
    supervisor.start(mix, 0.0, intent_id=new_id(), continue_next_id=new_id())

    supervisor.pause_audio()
    assert supervisor.playing is False
    assert player.is_alive() is False
    intents = supervisor.supervise(mix, previous_position=10.0)
    assert intents == []
