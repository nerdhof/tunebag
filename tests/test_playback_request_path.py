"""Skip/play must not stall on peer HTTP; player hygiene stays local."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.player import NullPlayer
from tunebag.source import FakeSource


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 1, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _pair(tmp_path: Path) -> tuple[DeviceAgent, DeviceAgent, FakeSource, FakeClock]:
    src = FakeSource()
    clk = FakeClock()
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=tmp_path / "laptop",
        clock=clk,
        player=NullPlayer(),
    )
    phone = DeviceAgent(
        "phone",
        priority=10,
        source=src,
        data_dir=tmp_path / "phone",
        clock=clk,
        player=NullPlayer(),
    )
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    laptop.wait_for_sync()
    phone.wait_for_sync()
    return laptop, phone, src, clk


def _two_local_mixes(
    laptop: DeviceAgent,
    phone: DeviceAgent,
    source: FakeSource,
) -> tuple[object, object, object]:
    mixes = []
    for i in range(2):
        url = f"https://example.com/req-{i}"
        source.bytes_by_url[url] = f"audio:{i}".encode()
        mix = laptop.add_mix(
            title=f"Mix {i}",
            url=url,
            duration_seconds=600,
            platform=Platform.SOUNDCLOUD,
            platform_id=f"req-{i}",
            artist_name="DJ Example",
        )
        laptop.rate_mix(mix.id, Stars.FIVE)
        mixes.append(mix)
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[
            (laptop.device_id, 3600),
            (phone.device_id, 3600),
        ],
    )
    laptop.wait_for_sync()
    phone.wait_for_sync()
    laptop.fill_caches()
    phone.fill_caches()
    return mixes[0], mixes[1], intent


def test_play_returns_while_peer_yield_http_is_slow(
    tmp_path: Path, monkeypatch
) -> None:
    laptop, phone, source, _clk = _pair(tmp_path)
    mix_a, _mix_b, intent = _two_local_mixes(laptop, phone, source)
    laptop.remember_peer_url(phone.device_id, "http://203.0.113.1:9")

    started = threading.Event()
    released = threading.Event()

    def slow_yield(url: str, *, label: str) -> None:
        started.set()
        released.wait(timeout=5.0)

    monkeypatch.setattr(laptop, "_http_request_yield", slow_yield)

    t0 = time.monotonic()
    laptop.play(intent.id, mix_a.id)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.5, f"play blocked on peer yield ({elapsed:.2f}s)"
    assert started.wait(timeout=1.0)
    released.set()
    # Drain background yield thread.
    deadline = time.monotonic() + 2.0
    while laptop._yield_in_progress and time.monotonic() < deadline:  # noqa: SLF001
        time.sleep(0.02)


def test_skip_returns_while_peer_nudge_http_is_slow(
    tmp_path: Path, monkeypatch
) -> None:
    laptop, phone, source, _clk = _pair(tmp_path)
    mix_a, mix_b, intent = _two_local_mixes(laptop, phone, source)
    laptop.play(intent.id, mix_a.id)
    laptop.remember_peer_url(phone.device_id, "http://203.0.113.1:9")

    started = threading.Event()
    released = threading.Event()

    def slow_nudge(url: str) -> None:
        started.set()
        released.wait(timeout=5.0)

    monkeypatch.setattr(laptop, "_http_nudge_sync", slow_nudge)

    t0 = time.monotonic()
    next_mix = laptop.skip(intent.id)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.5, f"skip blocked on peer nudge ({elapsed:.2f}s)"
    assert next_mix.id == mix_b.id
    assert started.wait(timeout=1.0)
    released.set()
    deadline = time.monotonic() + 2.0
    while laptop._nudge_in_progress and time.monotonic() < deadline:  # noqa: SLF001
        time.sleep(0.02)


def test_agent_shutdown_stops_player(tmp_path: Path) -> None:
    class TrackingPlayer(NullPlayer):
        def __init__(self) -> None:
            super().__init__()
            self.stops = 0

        def stop(self) -> None:
            super().stop()
            self.stops += 1

    player = TrackingPlayer()
    agent = DeviceAgent(
        "solo",
        priority=1,
        source=FakeSource(),
        data_dir=tmp_path / "solo",
        player=player,
    )
    agent.shutdown()
    assert player.stops >= 1
    assert agent.is_playing() is False
