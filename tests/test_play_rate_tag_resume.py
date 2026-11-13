"""Issue 06: play, rate, tag, resume — exercised only through DeviceAgent."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from mixy.agent import DeviceAgent
from mixy.domain import Platform, Stars
from mixy.player import NullPlayer
from mixy.source import FakeSource


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


def _pair(
    tmp_path: Path,
    *,
    source: FakeSource | None = None,
    player: NullPlayer | None = None,
) -> tuple[DeviceAgent, DeviceAgent, FakeSource]:
    src = source or FakeSource()
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=tmp_path / "laptop",
        player=player if player is not None else NullPlayer(),
    )
    phone = DeviceAgent(
        "phone",
        priority=10,
        source=src,
        data_dir=tmp_path / "phone",
        player=NullPlayer(),
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
    assert laptop.is_playing() is False


def test_listening_past_75_percent_counts_as_played(tmp_path: Path) -> None:
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

    laptop.report_playhead(749)
    assert next(m for m in laptop.mixes() if m.id == mix_id).played is False

    laptop.report_playhead(750)

    assert next(m for m in laptop.mixes() if m.id == mix_id).played is True


def test_stop_before_75_percent_leaves_mix_in_sequence_and_on_disk(
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
    assert [e.mix_id for e in before.entries] == [first, second]

    laptop.fill_caches()
    laptop.play(intent.id, first)
    laptop.mark_played()

    after = laptop.sequence(intent.id)
    assert after is not None
    assert [e.mix_id for e in after.entries] == [second, first]


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
    laptop.fill_caches()
    assert {m.id for m in laptop.files()} == {first}
    laptop.play(intent.id, first)
    laptop.mark_played()

    assert first not in {m.id for m in laptop.files()}
    assert second in {m.id for m in laptop.files()}


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

    assert laptop.suggest_tags("t") == ["techno", "tribal"]
    assert laptop.suggest_tags("deep") == ["deep"]
    assert laptop.suggest_tags("zzz") == []


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
    assert phone.playback_position() == 900
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
