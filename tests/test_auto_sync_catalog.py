"""Issue 10: auto-sync catalog — exercised only through DeviceAgent."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from mixy.agent import DeviceAgent
from mixy.domain import Platform, Stars
from mixy.source import FakeSource


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
    clock: FakeClock | None = None,
) -> tuple[DeviceAgent, DeviceAgent, FakeSource, FakeClock]:
    src = FakeSource()
    clk = clock or FakeClock()
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=tmp_path / "laptop",
        clock=clk,
    )
    phone = DeviceAgent(
        "phone",
        priority=10,
        source=src,
        data_dir=tmp_path / "phone",
        clock=clk,
    )
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    laptop.wait_for_sync()
    phone.wait_for_sync()
    return laptop, phone, src, clk


def test_catalog_change_visible_on_peer_without_pressing_sync(tmp_path: Path) -> None:
    laptop, phone, _source, _clock = _pair(tmp_path)

    mix = laptop.add_mix(
        title="Auto sync set",
        url="https://example.com/auto-sync",
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="auto-sync-1",
        artist_name="DJ Example",
    )
    laptop.wait_for_sync()
    phone.wait_for_sync()

    assert mix.id in {m.id for m in phone.mixes()}
    assert next(m for m in phone.mixes() if m.id == mix.id).title == "Auto sync set"


def test_becoming_reachable_again_triggers_sync(tmp_path: Path) -> None:
    laptop, phone, _source, _clock = _pair(tmp_path)
    laptop.disconnect(phone)

    mix = laptop.add_mix(
        title="Written while apart",
        url="https://example.com/apart",
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="apart-1",
        artist_name="DJ Example",
    )
    laptop.wait_for_sync()
    phone.wait_for_sync()
    assert mix.id not in {m.id for m in phone.mixes()}

    laptop.connect(phone)
    laptop.wait_for_sync()
    phone.wait_for_sync()

    assert mix.id in {m.id for m in phone.mixes()}


def test_manual_sync_still_forces_immediate_catch_up(tmp_path: Path) -> None:
    laptop, phone, _source, _clock = _pair(tmp_path)
    laptop.disconnect(phone)

    mix = laptop.add_mix(
        title="Manual override",
        url="https://example.com/manual",
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="manual-1",
        artist_name="DJ Example",
    )
    laptop.wait_for_sync()
    phone.wait_for_sync()
    assert mix.id not in {m.id for m in phone.mixes()}

    laptop.connect(phone)
    # Explicit sync (what the Sync button does) without waiting on auto-sync.
    phone.sync(fill=False)
    assert mix.id in {m.id for m in phone.mixes()}


def test_reject_stays_local_during_undo_window_despite_auto_sync(
    tmp_path: Path,
) -> None:
    laptop, phone, source, _clock = _pair(tmp_path)
    url = "https://example.com/maybe-reject"
    source.bytes_by_url[url] = b"audio:maybe"
    mix = laptop.add_mix(
        title="Maybe reject",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="maybe-reject",
        artist_name="DJ Example",
    )
    laptop.rate_mix(mix.id, Stars.FIVE)
    laptop.wait_for_sync()
    phone.wait_for_sync()
    assert mix.id in {m.id for m in phone.mixes()}

    laptop.reject_mix(mix.id)
    laptop.wait_for_sync()
    phone.wait_for_sync()

    assert laptop.catalog.mixes[mix.id].rejected is False
    assert any(p.mix_id == mix.id for p in laptop.pending_rejects())
    assert phone.catalog.mixes[mix.id].rejected is False
