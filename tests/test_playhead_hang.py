"""Playhead ticks must not hang the companion via Catalog refresh / auto-sync."""

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
        self._now = start or datetime(2024, 1, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _pair(
    tmp_path: Path,
) -> tuple[DeviceAgent, DeviceAgent, FakeSource]:
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
    return laptop, phone, src


def _add_and_play(
    laptop: DeviceAgent,
    phone: DeviceAgent,
    source: FakeSource,
    *,
    duration_seconds: int = 3600,
) -> object:
    url = "https://example.com/hang-mix"
    source.bytes_by_url[url] = b"audio:hang"
    mix = laptop.add_mix(
        title="Hang mix",
        url=url,
        duration_seconds=duration_seconds,
        platform=Platform.SOUNDCLOUD,
        platform_id="hang-1",
        artist_name="DJ Example",
    )
    laptop.rate_mix(mix.id, Stars.FIVE)
    intent = laptop.create_intent(
        "Play",
        seed=1,
        device_hours=[
            (laptop.device_id, duration_seconds),
            (phone.device_id, duration_seconds),
        ],
    )
    laptop.wait_for_sync()
    phone.wait_for_sync()
    laptop.fill_caches()
    phone.fill_caches()
    laptop.play(intent.id, mix.id)
    return mix


def test_playhead_tick_does_not_auto_sync_or_mark_catalog(tmp_path: Path) -> None:
    laptop, phone, source = _pair(tmp_path)
    mix = _add_and_play(laptop, phone, source)
    # Below Last heard so this is PLAYHEAD-only.
    laptop.report_playhead(5)
    laptop.wait_for_sync()
    phone.wait_for_sync()
    laptop.drain_view_notices()
    phone.drain_view_notices()

    laptop.report_playhead(8)
    # Give any mistaken auto-sync a moment to run.
    laptop.wait_for_sync(timeout=1.0)
    phone.wait_for_sync(timeout=1.0)

    sections = {n.section for n in laptop.drain_view_notices()}
    assert UIViewSection.MIXES not in sections
    assert UIViewSection.PLAY_HISTORY not in sections
    assert UIViewSection.ACTIVITY not in sections
    # Peer must not see the mid-tick playhead until a transport boundary.
    assert phone.playhead(mix.id) is None or phone.playhead(mix.id).position_seconds != 8


def test_pause_flushes_playhead_to_peer_via_auto_sync(tmp_path: Path) -> None:
    laptop, phone, source = _pair(tmp_path)
    mix = _add_and_play(laptop, phone, source)
    laptop.report_playhead(8)
    laptop.wait_for_sync(timeout=1.0)
    phone.wait_for_sync(timeout=1.0)
    assert phone.playhead(mix.id) is None or phone.playhead(mix.id).position_seconds != 8

    laptop.pause()
    laptop.wait_for_sync()
    phone.wait_for_sync()

    head = phone.playhead(mix.id)
    assert head is not None
    assert head.position_seconds == 8


def test_seek_flushes_playhead_to_peer_via_auto_sync(tmp_path: Path) -> None:
    laptop, phone, source = _pair(tmp_path)
    mix = _add_and_play(laptop, phone, source)
    laptop.seek(900)
    laptop.wait_for_sync()
    phone.wait_for_sync()

    head = phone.playhead(mix.id)
    assert head is not None
    assert head.position_seconds == 900


def test_stop_with_position_flushes_playhead_to_peer(tmp_path: Path) -> None:
    laptop, phone, source = _pair(tmp_path)
    mix = _add_and_play(laptop, phone, source)
    laptop.stop(position_seconds=120)
    laptop.wait_for_sync()
    phone.wait_for_sync()

    head = phone.playhead(mix.id)
    assert head is not None
    assert head.position_seconds == 120


def test_companion_playhead_heartbeat_is_five_minutes() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    js = (root / "app.js").read_text()
    html = (root / "index.html").read_text()
    assert "PLAYHEAD_COMMIT_MS = 5 * 60 * 1000" in js
    assert "PLAYER_POLL_MS" not in js
    assert "setPlayerLocalClock" in js
    assert "position_seconds: Math.max(0, lastKnownPositionSeconds)" in js
    assert "/static/app.js?v=70" in html
