"""Issue 01 (play-history): Last heard + Played at natural end — DeviceAgent + API + UI."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.player import NullPlayer
from tunebag.source import FakeSource
from tunebag.web import create_app


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 6, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _pair(
    tmp_path: Path,
    *,
    clock: FakeClock | None = None,
) -> tuple[DeviceAgent, DeviceAgent, FakeSource, FakeClock]:
    src = FakeSource()
    clk = clock or FakeClock()
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=tmp_path / "laptop",
        player=NullPlayer(),
        clock=clk,
    )
    phone = DeviceAgent(
        "phone",
        priority=10,
        source=src,
        data_dir=tmp_path / "phone",
        player=NullPlayer(),
        clock=clk,
    )
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    return laptop, phone, src, clk


def _add_mix(
    agent: DeviceAgent,
    source: FakeSource,
    *,
    title: str,
    duration_seconds: int,
    platform_id: str,
) -> UUID:
    url = f"https://example.com/{platform_id}"
    source.bytes_by_url[url] = f"audio:{platform_id}".encode()
    mix = agent.add_mix(
        title=title,
        url=url,
        duration_seconds=duration_seconds,
        platform=Platform.SOUNDCLOUD,
        platform_id=platform_id,
        artist_name="DJ Example",
    )
    return mix.id


def _play_ready(
    agent: DeviceAgent,
    source: FakeSource,
    *,
    title: str,
    duration_seconds: int,
    platform_id: str,
) -> UUID:
    mix_id = _add_mix(
        agent,
        source,
        title=title,
        duration_seconds=duration_seconds,
        platform_id=platform_id,
    )
    agent.rate_mix(mix_id, Stars.FIVE)
    intent = agent.create_intent(
        "Play",
        seed=1,
        device_hours=[(agent.device_id, duration_seconds)],
    )
    agent.fill_caches()
    agent.play(intent.id, mix_id)
    return mix_id


def _finish_natural_end(agent: DeviceAgent) -> None:
    """Simulate the audio file ending so supervise emits Last heard + Played."""
    agent._cancel_playback_threshold_watch()
    agent._playback._player.stop()
    agent._supervise_playback()


def test_mid_play_does_not_record_last_heard(tmp_path: Path) -> None:
    """Playhead updates mid-Release leave Last heard and Played unset."""
    laptop, _phone, source, _clock = _pair(tmp_path)
    mix_id = _play_ready(
        laptop,
        source,
        title="Set A",
        duration_seconds=1000,
        platform_id="a",
    )

    laptop.report_playhead(500)
    mix = next(m for m in laptop.mixes() if m.id == mix_id)
    assert mix.last_heard_at is None
    assert mix.played is False


def test_natural_end_records_last_heard_and_played(tmp_path: Path) -> None:
    """Natural end of Release sets Last heard and Played together."""
    laptop, _phone, source, clock = _pair(tmp_path)
    mix_id = _play_ready(
        laptop,
        source,
        title="Set A",
        duration_seconds=1000,
        platform_id="end-a",
    )

    clock.advance(1)
    _finish_natural_end(laptop)

    mix = next(m for m in laptop.mixes() if m.id == mix_id)
    assert mix.last_heard_at == clock()
    assert mix.played is True
    head = laptop.playhead(mix_id)
    assert head is not None
    assert head.position_seconds == 1000.0


def test_supervise_watch_commits_on_natural_end(tmp_path: Path) -> None:
    """Agent end watch commits when the player dies while still playing."""
    laptop, _phone, source, clock = _pair(tmp_path)
    mix_id = _play_ready(
        laptop,
        source,
        title="Set A",
        duration_seconds=1000,
        platform_id="live-end",
    )
    laptop._cancel_playback_threshold_watch()
    laptop.report_playhead(100)
    assert next(m for m in laptop.mixes() if m.id == mix_id).last_heard_at is None

    clock.advance(5)
    # Idle GET path must not complete the Release.
    laptop.playback_position()
    assert next(m for m in laptop.mixes() if m.id == mix_id).last_heard_at is None

    laptop._playback._player.stop()
    laptop._playback_threshold_tick()

    mix = next(m for m in laptop.mixes() if m.id == mix_id)
    assert mix.last_heard_at == clock()
    assert mix.played is True
    laptop._cancel_playback_threshold_watch()


def test_mark_played_helper_does_not_invent_last_heard(tmp_path: Path) -> None:
    """Internal mark_played (no continue) sets Played without Last heard."""
    laptop, _phone, source, _clock = _pair(tmp_path)
    mix_id = _play_ready(
        laptop,
        source,
        title="Set B",
        duration_seconds=1000,
        platform_id="b",
    )
    laptop.mark_played(mix_id)
    mix = next(m for m in laptop.mixes() if m.id == mix_id)
    assert mix.played is True
    assert mix.last_heard_at is None


def test_mark_played_and_continue_sets_last_heard(tmp_path: Path) -> None:
    """Companion Mark played records Last heard + Played together."""
    laptop, _phone, source, clock = _pair(tmp_path)
    mix_id = _play_ready(
        laptop,
        source,
        title="Set C",
        duration_seconds=1000,
        platform_id="c",
    )
    clock.advance(1)
    laptop.mark_played_and_continue()
    mix = next(m for m in laptop.mixes() if m.id == mix_id)
    assert mix.played is True
    assert mix.last_heard_at == clock()


def test_http_mark_played_advances_to_next_local(tmp_path: Path) -> None:
    """POST /api/player/mark-played completes current and plays the next local."""
    laptop, _phone, source, _clock = _pair(tmp_path)
    a = _add_mix(
        laptop, source, title="Set A", duration_seconds=1000, platform_id="http-a"
    )
    b = _add_mix(
        laptop, source, title="Set B", duration_seconds=1000, platform_id="http-b"
    )
    laptop.rate_mix(a, Stars.FIVE)
    laptop.rate_mix(b, Stars.FIVE)
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

    client = TestClient(create_app(laptop))
    res = client.post(
        "/api/player/mark-played",
        json={"intent_id": str(intent.id)},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["playing"] is True
    assert body["current_mix_id"] == str(nxt_id)
    finished = next(m for m in laptop.mixes() if m.id == head)
    assert finished.played is True
    assert finished.last_heard_at is not None
    assert laptop.current_mix() == nxt_id


def test_last_heard_survives_peer_sync_and_event_log_rebuild(
    tmp_path: Path,
) -> None:
    """Paired Devices converge; cold-start replay keeps the winning Last heard."""
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Set A",
        duration_seconds=1000,
        platform_id="a",
    )
    laptop.rate_mix(mix_id, Stars.FIVE)
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[
            (laptop.device_id, 1000),
            (phone.device_id, 1000),
        ],
    )
    laptop.fill_caches()
    laptop.wait_for_sync()
    phone.wait_for_sync()
    phone.fill_caches()

    laptop.play(intent.id, mix_id)
    clock.advance(5)
    _finish_natural_end(laptop)
    heard = clock()
    laptop.sync()
    phone.sync()
    assert next(m for m in phone.mixes() if m.id == mix_id).last_heard_at == heard

    # Later natural end from phone wins by signed author time.
    laptop.disconnect(phone)
    phone.disconnect(laptop)
    clock.advance(121)
    phone.play(intent.id, mix_id)
    clock.advance(1)
    later = clock()
    _finish_natural_end(phone)
    assert next(m for m in phone.mixes() if m.id == mix_id).last_heard_at == later

    laptop.connect(phone)
    laptop.sync()
    phone.sync()
    assert next(m for m in laptop.mixes() if m.id == mix_id).last_heard_at == later
    assert next(m for m in phone.mixes() if m.id == mix_id).last_heard_at == later

    rebuilt = DeviceAgent(
        "laptop",
        priority=1,
        source=source,
        data_dir=tmp_path / "laptop",
        player=NullPlayer(),
        clock=clock,
    )
    assert next(m for m in rebuilt.mixes() if m.id == mix_id).last_heard_at == later


def test_mixes_api_exposes_last_heard_without_backfill(tmp_path: Path) -> None:
    """GET /api/mixes includes last_heard_at; Played-only mixes stay null."""
    clock = FakeClock()
    source = FakeSource()
    agent = DeviceAgent(
        "laptop",
        source=source,
        data_dir=tmp_path / "laptop",
        player=NullPlayer(),
        clock=clock,
    )
    heard_id = _add_mix(
        agent, source, title="Heard", duration_seconds=1000, platform_id="heard"
    )
    played_only = _add_mix(
        agent,
        source,
        title="Played only",
        duration_seconds=1000,
        platform_id="played",
    )
    agent.rate_mix(heard_id, Stars.FIVE)
    agent.rate_mix(played_only, Stars.FIVE)
    intent = agent.create_intent(
        "Play",
        seed=1,
        device_hours=[(agent.device_id, 3000)],
    )
    agent.fill_caches()
    agent.play(intent.id, heard_id)
    clock.advance(1)
    heard_at = clock()
    _finish_natural_end(agent)

    agent.play(intent.id, played_only)
    agent.mark_played(played_only)

    client = TestClient(create_app(agent))
    res = client.get("/api/mixes")
    assert res.status_code == 200
    by_id = {row["id"]: row for row in res.json()["mixes"]}
    assert by_id[str(heard_id)]["last_heard_at"] == heard_at.isoformat()
    assert by_id[str(heard_id)]["played"] is True
    assert by_id[str(played_only)]["last_heard_at"] is None
    assert by_id[str(played_only)]["played"] is True


def test_playlog_ui_contract_assignment_table() -> None:
    """Static Playlog section loads assignment-relative rows from /api/playlog."""
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    html = (root / "index.html").read_text()
    js = (root / "app.js").read_text()
    assert 'id="playlog"' in html
    assert 'id="playlog-body"' in html
    assert "refreshPlaylog" in js
    assert "/api/playlog" in js
    assert "Playlog" in html
    assert "<th>Length</th>" in html
    assert "completed (Played)" in html
    assert 'id="player-mark"' in html
    assert "Mark played" in html
