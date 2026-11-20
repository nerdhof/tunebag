"""Issue 06: play, rate, tag, resume — exercised only through DeviceAgent."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.events import EventType
from tunebag.player import NullPlayer
from tunebag.skip import SKIP_EFFECTIVE_SECONDS
from tunebag.source import FakeSource


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
        """Simulate the current mix file ending (external player exits)."""
        self._alive = False


def _pair(
    tmp_path: Path,
    *,
    source: FakeSource | None = None,
    player: NullPlayer | None = None,
    clock: Callable[[], datetime] | None = None,
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
        player=NullPlayer(),
        clock=clock,
    )
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    return laptop, phone, src


def _add_mix(
    agent: DeviceAgent,
    source: FakeSource,
    *,
    title: str,
    duration_seconds: int,
    platform_id: str,
    tags: list[str] | None = None,
    stars: Stars | None = None,
    audio: bytes | None = None,
) -> UUID:
    url = f"https://example.com/{platform_id}"
    source.bytes_by_url[url] = audio if audio is not None else f"audio:{platform_id}".encode()
    mix = agent.add_mix(
        title=title,
        url=url,
        duration_seconds=duration_seconds,
        platform=Platform.SOUNDCLOUD,
        platform_id=platform_id,
        artist_name="DJ Example",
    )
    if tags is not None:
        agent.tag_mix(mix.id, tags)
    if stars is not None:
        agent.rate_mix(mix.id, stars)
    return mix.id


def test_play_starts_local_player_against_cached_file(tmp_path: Path) -> None:
    recorder = _RecordingPlayer()
    laptop, _phone, source = _pair(tmp_path, player=recorder)
    mix_id = _add_mix(
        laptop,
        source,
        title="Set A",
        duration_seconds=3600,
        platform_id="a",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    laptop.fill_caches()

    laptop.play(intent.id, mix_id)

    assert len(recorder.plays) == 1
    path, start = recorder.plays[0]
    assert path == tmp_path / "laptop" / "blobs" / str(mix_id)
    assert path.is_file()
    assert start == 0.0
    laptop.stop()
    assert recorder.stops >= 1


def test_mark_played_counts_as_played_without_waiting(tmp_path: Path) -> None:
    laptop, _phone, source = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Set A",
        duration_seconds=3600,
        platform_id="a",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    laptop.fill_caches()
    laptop.play(intent.id, mix_id)

    laptop.mark_played()

    mix = next(m for m in laptop.mixes() if m.id == mix_id)
    assert mix.played is True
    assert laptop.is_playing() is True
    assert laptop.current_mix() == mix_id


def test_mark_played_and_continue_advances_without_skipped(tmp_path: Path) -> None:
    laptop, _phone, source = _pair(tmp_path)
    a = _add_mix(
        laptop,
        source,
        title="Set A",
        duration_seconds=1000,
        platform_id="a",
        stars=Stars.FIVE,
    )
    b = _add_mix(
        laptop,
        source,
        title="Set B",
        duration_seconds=1000,
        platform_id="b",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[(laptop.device_id, 4000)],
    )
    laptop.fill_caches()
    assignment = laptop.assignment(intent.id)
    assert assignment is not None
    assert set(assignment.mix_ids) == {a, b}
    head = assignment.mix_ids[0]
    nxt_id = assignment.mix_ids[1]
    laptop.play(intent.id, head)

    playing = laptop.mark_played_and_continue()

    finished = next(m for m in laptop.mixes() if m.id == head)
    assert finished.played is True
    assert finished.last_heard_at is not None
    assert finished.skipped is False
    assert len(laptop.pending_skips()) == 0
    assert playing.id == nxt_id
    assert laptop.current_mix() == nxt_id
    assert laptop.is_playing() is True


def test_skip_does_not_mark_played(tmp_path: Path) -> None:
    laptop, _phone, source = _pair(tmp_path)
    a = _add_mix(
        laptop,
        source,
        title="Set A",
        duration_seconds=1000,
        platform_id="a",
        stars=Stars.FIVE,
    )
    b = _add_mix(
        laptop,
        source,
        title="Set B",
        duration_seconds=1000,
        platform_id="b",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[(laptop.device_id, 4000)],
    )
    laptop.fill_caches()
    assignment = laptop.assignment(intent.id)
    assert assignment is not None
    head = assignment.mix_ids[0]
    nxt_id = assignment.mix_ids[1]
    laptop.play(intent.id, head)

    laptop.skip()

    abandoned = next(m for m in laptop.mixes() if m.id == head)
    assert abandoned.played is False
    assert abandoned.last_heard_at is None
    assert laptop.current_mix() == nxt_id
    assert head in {p.mix_id for p in laptop.pending_skips()}


def test_mid_play_playhead_does_not_count_as_played(tmp_path: Path) -> None:
    laptop, _phone, source = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Set A",
        duration_seconds=1000,
        platform_id="a",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[(laptop.device_id, 1000)],
    )
    laptop.fill_caches()
    laptop.play(intent.id, mix_id)

    laptop.report_playhead(750)
    assert next(m for m in laptop.mixes() if m.id == mix_id).played is False
    assert next(m for m in laptop.mixes() if m.id == mix_id).last_heard_at is None
    assert laptop.is_playing() is True
    assert laptop.current_mix() == mix_id


def test_stop_before_end_leaves_mix_in_sequence_and_on_disk(
    tmp_path: Path,
) -> None:
    laptop, _phone, source = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Set A",
        duration_seconds=1000,
        platform_id="a",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[(laptop.device_id, 1000)],
    )
    laptop.fill_caches()
    laptop.play(intent.id, mix_id)
    laptop.report_playhead(100)

    laptop.stop()

    assert laptop.is_playing() is False
    assert next(m for m in laptop.mixes() if m.id == mix_id).played is False
    head = laptop.playhead(mix_id)
    assert head is not None
    assert head.position_seconds == 0.0
    assignment = laptop.assignment(intent.id)
    assert assignment is not None
    assert mix_id in assignment.mix_ids
    assert mix_id in {m.id for m in laptop.files()}


def test_closing_browser_does_not_stop_playback(tmp_path: Path) -> None:
    """Agent owns playback; dropping the remote-control session is a no-op."""
    laptop, _phone, source = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Set A",
        duration_seconds=3600,
        platform_id="a",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    laptop.fill_caches()
    laptop.play(intent.id, mix_id)

    # Browser closed — no agent call that stops playback.
    assert laptop.is_playing() is True
    assert laptop.current_mix() == mix_id


def test_played_mix_goes_to_back_of_pool(tmp_path: Path) -> None:
    laptop, _phone, source = _pair(tmp_path)
    first = _add_mix(
        laptop,
        source,
        title="Alpha",
        duration_seconds=3600,
        platform_id="alpha",
        stars=Stars.FIVE,
    )
    second = _add_mix(
        laptop,
        source,
        title="Beta",
        duration_seconds=3600,
        platform_id="beta",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Pool",
        seed=1,
        device_hours=[(laptop.device_id, 7200)],
    )
    before = laptop.sequence(intent.id)
    assert before is not None
    before_ids = [e.mix_id for e in before.entries]
    assert set(before_ids) == {first, second}
    head = before_ids[0]
    other = before_ids[1]

    laptop.fill_caches()
    laptop.play(intent.id, head)
    laptop.mark_played()

    after = laptop.sequence(intent.id)
    assert after is not None
    assert [e.mix_id for e in after.entries] == [other, head]


def test_played_file_stays_until_replacement_is_local(tmp_path: Path) -> None:
    laptop, _phone, source = _pair(tmp_path)
    only = _add_mix(
        laptop,
        source,
        title="Only",
        duration_seconds=3600,
        platform_id="only",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Solo",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    laptop.fill_caches()
    laptop.play(intent.id, only)
    laptop.mark_played()

    assert only in {m.id for m in laptop.files()}


def test_played_file_deleted_once_replacement_is_local(tmp_path: Path) -> None:
    laptop, _phone, source = _pair(tmp_path)
    first = _add_mix(
        laptop,
        source,
        title="Alpha",
        duration_seconds=3600,
        platform_id="alpha",
        stars=Stars.FIVE,
    )
    second = _add_mix(
        laptop,
        source,
        title="Beta",
        duration_seconds=3600,
        platform_id="beta",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Replace",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    assignment = laptop.assignment(intent.id)
    assert assignment is not None
    assert len(assignment.mix_ids) == 1
    head = assignment.mix_ids[0]
    other = first if head == second else second
    laptop.fill_caches()
    assert {m.id for m in laptop.files()} == {head}
    laptop.play(intent.id, head)
    laptop.mark_played()

    # Still current: keep bytes so playback can continue.
    assert head in {m.id for m in laptop.files()}
    assert other in {m.id for m in laptop.files()}
    assert laptop.is_playing() is True
    assert laptop.current_mix() == head

    laptop.stop()

    assert head not in {m.id for m in laptop.files()}
    assert other in {m.id for m in laptop.files()}


def test_one_star_leaves_mix_eligible_and_separate_from_reject(tmp_path: Path) -> None:
    laptop, _phone, source = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Low",
        duration_seconds=3600,
        platform_id="low",
        stars=Stars.ONE,
    )
    intent = laptop.create_intent(
        "Rest",
        seed=1,
        distribution=None,
        device_hours=[(laptop.device_id, 3600)],
    )

    mix = next(m for m in laptop.mixes() if m.id == mix_id)
    assert mix.stars is Stars.ONE
    assert mix.rejected is False
    assignment = laptop.assignment(intent.id)
    assert assignment is not None
    assert mix_id in assignment.mix_ids


def test_later_features_lists_planned_work_without_implementing_it(
    tmp_path: Path,
) -> None:
    laptop, _phone, _source = _pair(tmp_path)

    later = laptop.later_features()

    assert isinstance(later, list)
    assert len(later) >= 3
    assert any("Bandcamp" in item for item in later)
    assert any("OR" in item for item in later)


def test_phone_uses_same_playback_path(tmp_path: Path) -> None:
    laptop, phone, source = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Shared",
        duration_seconds=3600,
        platform_id="shared",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[
            (laptop.device_id, 3600),
            (phone.device_id, 3600),
        ],
    )
    laptop.fill_caches()
    phone.sync()

    phone.play(intent.id, mix_id)
    phone.report_playhead(100)
    phone.mark_played()

    assert next(m for m in phone.mixes() if m.id == mix_id).played is True
    laptop.sync()
    assert next(m for m in laptop.mixes() if m.id == mix_id).played is True


def test_suggest_tags_returns_existing_catalog_tags(tmp_path: Path) -> None:
    laptop, _phone, source = _pair(tmp_path)
    _add_mix(
        laptop,
        source,
        title="Tribal A",
        duration_seconds=3600,
        platform_id="a",
        tags=["tribal", "deep"],
    )
    _add_mix(
        laptop,
        source,
        title="Techno B",
        duration_seconds=3600,
        platform_id="b",
        tags=["techno"],
    )

    # Equal counts → alphabetical among matches.
    assert laptop.suggest_tags("t") == ["techno", "tribal"]
    assert laptop.suggest_tags("deep") == ["deep"]
    assert laptop.suggest_tags("zzz") == []

    _add_mix(
        laptop,
        source,
        title="Tribal C",
        duration_seconds=3600,
        platform_id="c",
        tags=["tribal"],
    )
    # Higher frequency wins over alpha.
    assert laptop.suggest_tags("t") == ["tribal", "techno"]


def test_playhead_syncs_and_peer_resumes_mid_mix(tmp_path: Path) -> None:
    laptop, phone, source = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Shared",
        duration_seconds=3600,
        platform_id="shared",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[
            (laptop.device_id, 3600),
            (phone.device_id, 3600),
        ],
    )
    laptop.fill_caches()
    phone.sync()
    laptop.play(intent.id, mix_id)
    laptop.report_playhead(900)

    phone.sync()

    head = phone.playhead(mix_id)
    assert head is not None
    assert head.position_seconds == 900
    assert mix_id in {m.id for m in phone.files()}
    phone.play(intent.id, mix_id)
    assert phone.is_playing() is True
    assert phone.current_mix() == mix_id
    assert phone.playback_position() == pytest.approx(900, abs=0.05)
    assert phone.playhead(mix_id).position_seconds == 900


def test_latest_playhead_wins_across_devices(tmp_path: Path) -> None:
    laptop, phone, source = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Shared",
        duration_seconds=3600,
        platform_id="shared",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[
            (laptop.device_id, 3600),
            (phone.device_id, 3600),
        ],
    )
    laptop.fill_caches()
    phone.sync()
    laptop.play(intent.id, mix_id)
    laptop.report_playhead(100)
    phone.play(intent.id, mix_id)
    phone.report_playhead(500)

    laptop.sync()
    phone.sync()

    assert laptop.playhead(mix_id).position_seconds == 500
    assert phone.playhead(mix_id).position_seconds == 500


def test_play_on_peer_yields_reachable_device(tmp_path: Path) -> None:
    laptop, phone, source = _pair(tmp_path, player=_RecordingPlayer())
    mix_id = _add_mix(
        laptop,
        source,
        title="Shared",
        duration_seconds=3600,
        platform_id="shared",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[
            (laptop.device_id, 3600),
            (phone.device_id, 3600),
        ],
    )
    laptop.fill_caches()
    phone.sync()
    laptop.play(intent.id, mix_id)
    laptop.report_playhead(120)
    assert laptop.is_playing() is True

    phone.play(intent.id, mix_id)

    assert phone.is_playing() is True
    assert laptop.is_playing() is False
    head = laptop.playhead(mix_id)
    assert head is not None
    assert head.position_seconds == pytest.approx(120, abs=0.05)


def test_play_does_not_yield_disconnected_peer(tmp_path: Path) -> None:
    laptop, phone, source = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Shared",
        duration_seconds=3600,
        platform_id="shared",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[
            (laptop.device_id, 3600),
            (phone.device_id, 3600),
        ],
    )
    laptop.fill_caches()
    phone.sync()
    laptop.play(intent.id, mix_id)
    assert laptop.is_playing() is True

    laptop.disconnect(phone)
    phone.play(intent.id, mix_id)

    assert phone.is_playing() is True
    assert laptop.is_playing() is True


def test_yield_playback_idle_is_noop(tmp_path: Path) -> None:
    laptop, _phone, _source = _pair(tmp_path)
    before = [e for e in laptop.export_events() if e.type == EventType.PLAYHEAD]
    assert laptop.is_playing() is False
    assert laptop.yield_playback() is False
    after = [e for e in laptop.export_events() if e.type == EventType.PLAYHEAD]
    assert after == before


def test_playback_position_advances_with_clock(tmp_path: Path) -> None:
    now = datetime(2024, 1, 1, 12, 0, 0)

    def clock() -> datetime:
        return now

    laptop, _phone, source = _pair(tmp_path, player=_RecordingPlayer(), clock=clock)
    mix_id = _add_mix(
        laptop,
        source,
        title="Set A",
        duration_seconds=3600,
        platform_id="a",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    laptop.fill_caches()
    laptop.play(intent.id, mix_id)
    assert laptop.playback_position() == 0.0

    now = now + timedelta(seconds=45)
    assert laptop.playback_position() == 45.0

    laptop.stop()
    assert laptop.playback_position() == 0.0
    now = now + timedelta(seconds=10)
    assert laptop.playback_position() == 0.0


def test_seek_while_playing_restarts_player_at_offset(tmp_path: Path) -> None:
    recorder = _RecordingPlayer()
    laptop, _phone, source = _pair(tmp_path, player=recorder)
    mix_id = _add_mix(
        laptop,
        source,
        title="Set A",
        duration_seconds=3600,
        platform_id="a",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    laptop.fill_caches()
    laptop.play(intent.id, mix_id)
    assert len(recorder.plays) == 1

    head = laptop.seek(900)
    assert head.position_seconds == 900
    assert laptop.playback_position() == pytest.approx(900, abs=0.05)
    assert laptop.is_playing() is True
    assert len(recorder.plays) == 2
    assert recorder.plays[-1][1] == 900.0


def test_seek_while_stopped_updates_playhead_without_play(tmp_path: Path) -> None:
    recorder = _RecordingPlayer()
    laptop, _phone, source = _pair(tmp_path, player=recorder)
    mix_id = _add_mix(
        laptop,
        source,
        title="Set A",
        duration_seconds=3600,
        platform_id="a",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    laptop.fill_caches()
    laptop.play(intent.id, mix_id)
    laptop.stop()
    plays_after_stop = len(recorder.plays)

    head = laptop.seek(120)
    assert head.position_seconds == 120
    assert laptop.playback_position() == 120
    assert laptop.is_playing() is False
    assert len(recorder.plays) == plays_after_stop
    assert laptop.playhead(mix_id).position_seconds == 120


def test_seek_mid_release_does_not_mark_played(tmp_path: Path) -> None:
    recorder = _RecordingPlayer()
    laptop, _phone, source = _pair(tmp_path, player=recorder)
    mix_id = _add_mix(
        laptop,
        source,
        title="Set A",
        duration_seconds=1000,
        platform_id="a",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[(laptop.device_id, 1000)],
    )
    laptop.fill_caches()
    laptop.play(intent.id, mix_id)

    laptop.seek(750)

    assert next(m for m in laptop.mixes() if m.id == mix_id).played is False
    assert next(m for m in laptop.mixes() if m.id == mix_id).last_heard_at is None
    assert laptop.is_playing() is True
    assert laptop.current_mix() == mix_id


def test_pause_keeps_mix_and_play_resumes(tmp_path: Path) -> None:
    now = datetime(2024, 1, 1, 12, 0, 0)

    def clock() -> datetime:
        return now

    recorder = _RecordingPlayer()
    laptop, _phone, source = _pair(tmp_path, player=recorder, clock=clock)
    mix_id = _add_mix(
        laptop,
        source,
        title="Set A",
        duration_seconds=3600,
        platform_id="a",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    laptop.fill_caches()
    laptop.play(intent.id, mix_id)
    now = now + timedelta(seconds=90)
    laptop.pause()

    assert laptop.is_playing() is False
    assert laptop.current_mix() == mix_id
    assert laptop.playing_intent_id() == intent.id
    assert laptop.playback_position() == 90.0
    assert laptop.playhead(mix_id).position_seconds == 90.0

    resumed = laptop.play(intent.id)
    assert resumed.id == mix_id
    assert laptop.is_playing() is True
    assert recorder.plays[-1][1] == 90.0


def test_skip_advances_to_next_local_mix_without_marking_played(tmp_path: Path) -> None:
    recorder = _RecordingPlayer()
    laptop, _phone, source = _pair(tmp_path, player=recorder)
    first = _add_mix(
        laptop,
        source,
        title="Alpha",
        duration_seconds=3600,
        platform_id="alpha",
        stars=Stars.FIVE,
    )
    second = _add_mix(
        laptop,
        source,
        title="Beta",
        duration_seconds=3600,
        platform_id="beta",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Skip",
        seed=1,
        device_hours=[(laptop.device_id, 7200)],
    )
    laptop.fill_caches()
    assignment = laptop.assignment(intent.id)
    assert assignment is not None
    assert set(assignment.mix_ids) == {first, second}
    head = assignment.mix_ids[0]
    nxt = assignment.mix_ids[1]

    laptop.play(intent.id, head)
    assert laptop.current_mix() == head
    assert laptop.is_playing() is True

    skipped = laptop.skip()
    assert skipped.id == nxt
    assert laptop.current_mix() == nxt
    assert laptop.is_playing() is True
    assert next(m for m in laptop.mixes() if m.id == head).played is False
    assert len(recorder.plays) >= 2


def test_mix_end_auto_continues_to_next_local_without_skip(
    tmp_path: Path,
) -> None:
    recorder = _RecordingPlayer()
    laptop, _phone, source = _pair(tmp_path, player=recorder)
    first = _add_mix(
        laptop,
        source,
        title="Alpha",
        duration_seconds=3600,
        platform_id="alpha",
        stars=Stars.FIVE,
    )
    second = _add_mix(
        laptop,
        source,
        title="Beta",
        duration_seconds=3600,
        platform_id="beta",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Continue",
        seed=1,
        device_hours=[(laptop.device_id, 7200)],
    )
    laptop.fill_caches()
    assignment = laptop.assignment(intent.id)
    assert assignment is not None
    head = assignment.mix_ids[0]
    nxt = assignment.mix_ids[1]
    assert {head, nxt} == {first, second}

    laptop.play(intent.id, head)
    recorder.finish()
    assert laptop.is_playing() is True

    assert laptop.current_mix() == nxt
    finished = next(m for m in laptop.mixes() if m.id == head)
    assert finished.played is True
    assert finished.skipped is False
    assert len(laptop.pending_skips()) == 0
    head_playhead = laptop.playhead(head)
    assert head_playhead is not None
    assert head_playhead.position_seconds == 3600.0
    assert len(recorder.plays) >= 2
    assert recorder.plays[-1][0] == tmp_path / "laptop" / "blobs" / str(nxt)


def test_mix_end_stops_when_no_later_local_release(tmp_path: Path) -> None:
    recorder = _RecordingPlayer()
    laptop, _phone, source = _pair(tmp_path, player=recorder)
    only = _add_mix(
        laptop,
        source,
        title="Solo",
        duration_seconds=1800,
        platform_id="solo",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Solo continue",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    laptop.fill_caches()
    laptop.play(intent.id, only)

    recorder.finish()
    assert laptop.is_playing() is False

    assert laptop.current_mix() == only
    finished = next(m for m in laptop.mixes() if m.id == only)
    assert finished.played is True
    assert finished.skipped is False
    assert len(laptop.pending_skips()) == 0
    head = laptop.playhead(only)
    assert head is not None
    assert head.position_seconds == 1800.0


class _FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 1, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def test_skip_keeps_sequence_until_five_minute_delay(tmp_path: Path) -> None:
    clock = _FakeClock()
    laptop, _phone, source = _pair(tmp_path, clock=clock)
    first = _add_mix(
        laptop,
        source,
        title="Alpha",
        duration_seconds=3600,
        platform_id="alpha",
        stars=Stars.FIVE,
    )
    second = _add_mix(
        laptop,
        source,
        title="Beta",
        duration_seconds=3600,
        platform_id="beta",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Skip delay",
        seed=1,
        device_hours=[(laptop.device_id, 7200)],
    )
    before = laptop.sequence(intent.id)
    assert before is not None
    before_ids = [e.mix_id for e in before.entries]
    assert set(before_ids) == {first, second}
    head = before_ids[0]
    other = before_ids[1]

    laptop.fill_caches()
    laptop.play(intent.id, head)
    laptop.skip()

    mid = laptop.sequence(intent.id)
    assert mid is not None
    assert [e.mix_id for e in mid.entries] == before_ids
    abandoned = next(m for m in laptop.mixes() if m.id == head)
    assert abandoned.played is False
    assert abandoned.skipped is False
    assert len(laptop.pending_skips()) == 1

    clock.advance(SKIP_EFFECTIVE_SECONDS - 1)
    assert laptop.commit_pending_skips() == []
    still = next(m for m in laptop.mixes() if m.id == head)
    assert still.skipped is False

    clock.advance(1)
    committed = laptop.commit_pending_skips()
    assert committed == [head]
    done = next(m for m in laptop.mixes() if m.id == head)
    assert done.skipped is True
    assert done.played is False
    after = laptop.sequence(intent.id)
    assert after is not None
    assert [e.mix_id for e in after.entries] == [other, head]
    assert not any(e.type is EventType.PLAYED for e in laptop.export_events())
    assert any(e.type is EventType.SKIPPED for e in laptop.export_events())


def test_pending_skip_canceled_when_mix_played_again(tmp_path: Path) -> None:
    clock = _FakeClock()
    laptop, _phone, source = _pair(tmp_path, clock=clock)
    first = _add_mix(
        laptop,
        source,
        title="Alpha",
        duration_seconds=3600,
        platform_id="alpha",
        stars=Stars.FIVE,
    )
    second = _add_mix(
        laptop,
        source,
        title="Beta",
        duration_seconds=3600,
        platform_id="beta",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Skip cancel",
        seed=1,
        device_hours=[(laptop.device_id, 7200)],
    )
    before = laptop.sequence(intent.id)
    assert before is not None
    head = [e.mix_id for e in before.entries][0]
    other = [e.mix_id for e in before.entries][1]
    assert {head, other} == {first, second}

    laptop.fill_caches()
    laptop.play(intent.id, head)
    laptop.skip()
    assert len(laptop.pending_skips()) == 1

    laptop.play(intent.id, head)
    assert laptop.pending_skips() == []

    clock.advance(SKIP_EFFECTIVE_SECONDS + 1)
    assert laptop.commit_pending_skips() == []
    mix = next(m for m in laptop.mixes() if m.id == head)
    assert mix.skipped is False
    assert mix.played is False


def test_skipped_file_deleted_once_replacement_is_local(tmp_path: Path) -> None:
    clock = _FakeClock()
    laptop, _phone, source = _pair(tmp_path, clock=clock)
    first = _add_mix(
        laptop,
        source,
        title="Alpha",
        duration_seconds=3600,
        platform_id="alpha",
        stars=Stars.FIVE,
    )
    second = _add_mix(
        laptop,
        source,
        title="Beta",
        duration_seconds=3600,
        platform_id="beta",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Skip file",
        seed=1,
        device_hours=[(laptop.device_id, 7200)],
    )
    before = laptop.sequence(intent.id)
    assert before is not None
    head = [e.mix_id for e in before.entries][0]
    assert {head, [e.mix_id for e in before.entries][1]} == {first, second}

    laptop.fill_caches()
    assert head in {m.id for m in laptop.files()}
    laptop.play(intent.id, head)
    laptop.skip()
    clock.advance(SKIP_EFFECTIVE_SECONDS)
    laptop.commit_pending_skips()

    assert next(m for m in laptop.mixes() if m.id == head).skipped is True
    assert head not in {m.id for m in laptop.files()}
