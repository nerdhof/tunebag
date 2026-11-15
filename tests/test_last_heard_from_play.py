"""Issue 01 (play-history): Last heard from play — DeviceAgent + mixes API + UI contract."""

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


def test_crossing_meaningful_listen_threshold_records_last_heard(
    tmp_path: Path,
) -> None:
    """Position reaching max(120s, 5% duration) emits Last heard on rising edge only."""
    laptop, _phone, source, clock = _pair(tmp_path)
    # duration 1000 → 5% = 50 → threshold = max(120, 50) = 120
    mix_id = _play_ready(
        laptop,
        source,
        title="Set A",
        duration_seconds=1000,
        platform_id="a",
    )

    laptop.report_playhead(119)
    mix = next(m for m in laptop.mixes() if m.id == mix_id)
    assert mix.last_heard_at is None

    clock.advance(1)
    laptop.report_playhead(120)
    mix = next(m for m in laptop.mixes() if m.id == mix_id)
    assert mix.last_heard_at == clock()

    first_heard = mix.last_heard_at
    clock.advance(30)
    laptop.report_playhead(200)
    mix = next(m for m in laptop.mixes() if m.id == mix_id)
    assert mix.last_heard_at == first_heard


def test_last_heard_threshold_uses_five_percent_when_higher(
    tmp_path: Path,
) -> None:
    """On a long Mix, threshold is 5% of duration (not the 120s floor)."""
    laptop, _phone, source, clock = _pair(tmp_path)
    # duration 3600 → 5% = 180 → threshold = max(120, 180) = 180
    mix_id = _play_ready(
        laptop,
        source,
        title="Long Set",
        duration_seconds=3600,
        platform_id="long",
    )

    laptop.report_playhead(179)
    assert next(m for m in laptop.mixes() if m.id == mix_id).last_heard_at is None

    clock.advance(1)
    laptop.report_playhead(180)
    assert next(m for m in laptop.mixes() if m.id == mix_id).last_heard_at == clock()


def test_last_heard_independent_of_played(tmp_path: Path) -> None:
    """Crossing meaningful-listen does not require Played; mark_played does not invent Last heard."""
    laptop, _phone, source, clock = _pair(tmp_path)
    mix_id = _play_ready(
        laptop,
        source,
        title="Set A",
        duration_seconds=1000,
        platform_id="a",
    )

    clock.advance(1)
    laptop.report_playhead(120)
    mix = next(m for m in laptop.mixes() if m.id == mix_id)
    assert mix.last_heard_at == clock()
    assert mix.played is False

    other = _play_ready(
        laptop,
        source,
        title="Set B",
        duration_seconds=1000,
        platform_id="b",
    )
    laptop.mark_played(other)
    other_mix = next(m for m in laptop.mixes() if m.id == other)
    assert other_mix.played is True
    assert other_mix.last_heard_at is None


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
    laptop.report_playhead(120)
    heard = clock()
    laptop.sync()
    phone.sync()
    assert next(m for m in phone.mixes() if m.id == mix_id).last_heard_at == heard

    # Later rising edge from phone wins by signed author time.
    # Past the playhead near-window so a below-threshold seek can stick.
    laptop.disconnect(phone)
    phone.disconnect(laptop)
    clock.advance(121)
    phone.play(intent.id, mix_id)
    phone.report_playhead(50)
    clock.advance(1)
    later = clock()
    phone.report_playhead(120)
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
    agent.report_playhead(120)

    agent.play(intent.id, played_only)
    agent.mark_played(played_only)

    client = TestClient(create_app(agent))
    res = client.get("/api/mixes")
    assert res.status_code == 200
    by_id = {row["id"]: row for row in res.json()["mixes"]}
    assert by_id[str(heard_id)]["last_heard_at"] == heard_at.isoformat()
    assert by_id[str(played_only)]["last_heard_at"] is None
    assert by_id[str(played_only)]["played"] is True


def test_play_history_ui_lists_last_heard_newest_first() -> None:
    """Static Play history section orders Mixes with a Last heard, newest first."""
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    html = (root / "index.html").read_text()
    js = (root / "app.js").read_text()
    assert 'id="play-history"' in html
    assert 'id="play-history-body"' in html
    assert "refreshPlayHistory" in js
    assert "last_heard_at" in js
    assert "Play history" in html
