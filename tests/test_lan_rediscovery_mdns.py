"""Issue 07 (durable-sync): LAN rediscovery via injected LanDiscovery on DeviceAgent."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from tunebag.agent import DeviceAgent
from tunebag.discovery import DISCOVERY_REFRESH_SECONDS, FakeLanDiscovery
from tunebag.domain import Platform
from tunebag.source import FakeSource


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 1, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def _pair_with_discovery(
    tmp_path: Path,
    discovery: FakeLanDiscovery,
    *,
    clock: FakeClock | None = None,
) -> tuple[DeviceAgent, DeviceAgent, FakeSource]:
    src = FakeSource()
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=tmp_path / "laptop",
        base_url="inproc://laptop",
        discovery=discovery,
        clock=clock,
    )
    phone = DeviceAgent(
        "phone",
        priority=10,
        source=src,
        data_dir=tmp_path / "phone",
        base_url="inproc://phone",
        discovery=discovery,
        clock=clock,
    )
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    laptop.wait_for_sync()
    phone.wait_for_sync()
    return laptop, phone, src


def test_trusted_advertisement_refreshes_hint_and_syncs_without_qr(tmp_path: Path) -> None:
    discovery = FakeLanDiscovery()
    laptop, phone, src = _pair_with_discovery(tmp_path, discovery)
    laptop.disconnect(phone)

    url = "https://example.com/rediscovered"
    src.bytes_by_url[url] = b"audio:rediscovered"
    mix = laptop.add_mix(
        title="Rediscovered set",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="rediscovered-1",
        artist_name="DJ Example",
    )

    discovery.publish(laptop, locator="inproc://laptop-new")
    phone.refresh_discovery()
    phone.wait_for_sync()

    assert phone.peer_urls().get(laptop.device_id) == "inproc://laptop-new"
    assert mix.id in {m.id for m in phone.mixes()}


def test_unknown_advertisement_is_pair_candidate_only(tmp_path: Path) -> None:
    discovery = FakeLanDiscovery()
    src = FakeSource()
    phone = DeviceAgent(
        "phone",
        priority=10,
        source=src,
        data_dir=tmp_path / "phone",
        base_url="inproc://phone",
        discovery=discovery,
    )
    stranger = DeviceAgent(
        "stranger",
        priority=1,
        source=src,
        data_dir=tmp_path / "stranger",
        base_url="inproc://stranger",
        discovery=discovery,
    )

    phone.refresh_discovery()

    candidates = phone.pair_candidates()
    assert len(candidates) == 1
    assert candidates[0]["name"] == "stranger"
    assert candidates[0]["short_code"] == stranger.short_code()
    assert candidates[0]["locator"] == "inproc://stranger"
    assert candidates[0]["public_key_pem"] == stranger.public_key_pem
    assert [p.name for p in phone.peers()] == []

    phone.connect(stranger)
    phone.pair(stranger.pairing_payload())
    assert [p.name for p in phone.peers()] == ["stranger"]


def test_agents_advertise_name_short_code_and_locator(tmp_path: Path) -> None:
    discovery = FakeLanDiscovery()
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=FakeSource(),
        data_dir=tmp_path / "laptop",
        base_url="inproc://laptop",
        discovery=discovery,
    )

    ads = [ad for ad in discovery.browse() if ad.locator == "inproc://laptop"]
    assert len(ads) == 1
    assert ads[0].name == "laptop"
    assert ads[0].short_code == laptop.short_code()
    assert ads[0].locator == "inproc://laptop"
    assert not hasattr(ads[0], "public_key_pem")


def test_browse_on_network_change_and_periodic_when_no_live_session(
    tmp_path: Path,
) -> None:
    clock = FakeClock(datetime(2026, 1, 1, 12, 0, 0))
    discovery = FakeLanDiscovery()
    laptop, phone, _src = _pair_with_discovery(tmp_path, discovery, clock=clock)
    laptop.sync(fill=False)
    phone.sync(fill=False)
    calls_after_pair = discovery.browse_calls

    clock.advance(DISCOVERY_REFRESH_SECONDS + 1)
    phone.tick_discovery()
    assert discovery.browse_calls == calls_after_pair  # skipped: live session

    phone.disconnect(laptop)
    calls_before_network = discovery.browse_calls
    phone.on_network_change()
    assert discovery.browse_calls == calls_before_network + 1

    # Drop ads so rediscovery does not restore a live session for the periodic check.
    discovery.clear()
    phone.disconnect(laptop)
    after_clear = discovery.browse_calls
    clock.advance(30)
    phone.tick_discovery()
    assert discovery.browse_calls == after_clear  # interval not elapsed

    clock.advance(DISCOVERY_REFRESH_SECONDS)
    phone.tick_discovery()
    assert discovery.browse_calls == after_clear + 1


def test_pasted_locator_works_when_discovery_unavailable(tmp_path: Path) -> None:
    src = FakeSource()
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=tmp_path / "laptop",
    )
    phone = DeviceAgent(
        "phone",
        priority=10,
        source=src,
        data_dir=tmp_path / "phone",
    )
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    laptop.wait_for_sync()
    phone.wait_for_sync()
    phone.disconnect(laptop)

    phone.remember_peer_url(laptop.device_id, "inproc://unused-hint")
    # Without discovery, in-process meet still works via connect (pasted/manual path).
    laptop.connect(phone)
    url = "https://example.com/pasted-locator"
    src.bytes_by_url[url] = b"audio:pasted"
    mix = laptop.add_mix(
        title="Pasted locator set",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="pasted-1",
        artist_name="DJ Example",
    )
    laptop.sync(fill=False)
    phone.sync(fill=False)

    assert mix.id in {m.id for m in phone.mixes()}
    assert phone.peer_urls().get(laptop.device_id) == "inproc://unused-hint"
