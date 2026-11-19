"""Player view notices + threshold watch; no Activity→Cache companion coupling."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.player import NullPlayer
from tunebag.source import FakeSource
from tunebag.ui_notices import UIViewSection


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 6, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _agent(
    tmp_path: Path, *, name: str = "laptop", clock: FakeClock | None = None
) -> tuple[DeviceAgent, FakeSource]:
    source = FakeSource()
    agent = DeviceAgent(
        name,
        source=source,
        data_dir=tmp_path / name,
        player=NullPlayer(),
        clock=clock or FakeClock(),
    )
    return agent, source


def _sections(agent: DeviceAgent) -> list[UIViewSection]:
    return [n.section for n in agent.drain_view_notices()]


def _play_ready(agent: DeviceAgent, source: FakeSource) -> object:
    url = "https://example.com/player-push"
    source.bytes_by_url[url] = b"audio:push"
    mix = agent.add_mix(
        title="Push mix",
        url=url,
        duration_seconds=1000,
        platform=Platform.SOUNDCLOUD,
        platform_id="push-1",
        artist_name="DJ Example",
    )
    agent.rate_mix(mix.id, Stars.FIVE)
    intent = agent.create_intent(
        "Play",
        seed=1,
        device_hours=[(agent.device_id, 1000)],
    )
    agent.fill_caches()
    agent.drain_view_notices()
    agent.play(intent.id, mix.id)
    return mix


def test_play_and_pause_emit_player_notice(tmp_path: Path) -> None:
    clock = FakeClock()
    agent, source = _agent(tmp_path, clock=clock)
    mix = _play_ready(agent, source)
    sections = _sections(agent)
    assert UIViewSection.PLAYER in sections

    agent.drain_view_notices()
    agent.pause()
    assert UIViewSection.PLAYER in _sections(agent)
    agent._cancel_playback_threshold_watch()
    assert mix.id in agent.catalog.mixes


def test_threshold_watch_tick_commits_last_heard_without_playback_position(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    agent, source = _agent(tmp_path, clock=clock)
    mix = _play_ready(agent, source)
    agent._cancel_playback_threshold_watch()
    agent.report_playhead(1)
    assert agent.catalog.mixes[mix.id].last_heard_at is None

    clock.advance(10)
    # Idle GET path must not commit thresholds.
    agent.playback_position()
    assert agent.catalog.mixes[mix.id].last_heard_at is None

    agent._playback_threshold_tick()
    assert agent.catalog.mixes[mix.id].last_heard_at == clock()
    agent._cancel_playback_threshold_watch()


def test_companion_drops_player_poll_and_activity_files_coupling() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    js = (root / "app.js").read_text()
    html = (root / "index.html").read_text()

    assert '"player"' in js
    assert "PLAYER_POLL_MS" not in js
    assert "setPlayerLocalClock" in js
    assert "fillInProgressFromEntries" not in js
    assert "requestFilesRefresh" not in js
    assert "/static/app.js?v=71" in html

    # refreshActivity must not pull Cache.
    start = js.index("async function refreshActivity")
    rest = js[start:]
    end = rest.find("\nasync function ")
    body = rest[: end if end != -1 else len(rest)]
    assert "refreshFiles" not in body
    assert "/api/files" not in body
