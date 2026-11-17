"""Issue 06 (durable-sync): DEVICE_UNPAIRED via DeviceAgent."""

from __future__ import annotations

from pathlib import Path

from tunebag.agent import (
    EXPLORE_DEFAULT_BUDGET_SECONDS,
    EXPLORE_INTENT_ID,
    DeviceAgent,
)
from tunebag.domain import Platform
from tunebag.events import EventType
from tunebag.source import FakeSource


def _pair(tmp_path: Path) -> tuple[DeviceAgent, DeviceAgent, FakeSource]:
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
    return laptop, phone, src


def _add_mix(
    agent: DeviceAgent,
    source: FakeSource,
    *,
    title: str,
    platform_id: str,
) -> object:
    url = f"https://example.com/{platform_id}"
    source.bytes_by_url[url] = f"audio:{platform_id}".encode()
    return agent.add_mix(
        title=title,
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id=platform_id,
        artist_name="DJ Example",
    )


def test_unpair_clears_device_hours_keeps_intent_and_history(
    tmp_path: Path,
) -> None:
    """Unpair drops hours/assignments for that Peer; Explore and past mixes stay."""
    laptop = DeviceAgent("laptop", priority=1, data_dir=tmp_path / "laptop")
    phone = DeviceAgent("phone", priority=10, data_dir=tmp_path / "phone")
    assert laptop.seed_default_intents_if_empty()
    assert phone.seed_default_intents_if_empty()
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    laptop.sync(fill=False)
    phone.sync(fill=False)

    explore = laptop.catalog.intents[EXPLORE_INTENT_ID]
    assert {dh.device_id for dh in explore.device_hours} == {
        laptop.device_id,
        phone.device_id,
    }
    assert laptop.assignment(EXPLORE_INTENT_ID, phone.device_id) is not None

    laptop.unpair(phone.device_id)

    explore = laptop.catalog.intents[EXPLORE_INTENT_ID]
    assert explore.name == "Explore"
    assert {dh.device_id for dh in explore.device_hours} == {laptop.device_id}
    assert explore.device_hours[0].budget_seconds == EXPLORE_DEFAULT_BUDGET_SECONDS
    assert laptop.assignment(EXPLORE_INTENT_ID, phone.device_id) is None
    assert laptop.assignment(EXPLORE_INTENT_ID, laptop.device_id) is not None

    restarted = DeviceAgent("laptop", priority=1, data_dir=tmp_path / "laptop")
    explore = restarted.catalog.intents[EXPLORE_INTENT_ID]
    assert {dh.device_id for dh in explore.device_hours} == {laptop.device_id}
    assert restarted.assignment(EXPLORE_INTENT_ID, phone.device_id) is None


def test_unpair_ignores_future_events_keeps_history_and_requires_re_pair(
    tmp_path: Path,
) -> None:
    laptop, phone, src = _pair(tmp_path)
    before = _add_mix(phone, src, title="Before unpair", platform_id="before-1")
    laptop.sync(fill=False)
    phone.sync(fill=False)
    assert before.id in {m.id for m in laptop.mixes()}

    laptop.remember_peer_url(phone.device_id, "http://phone.example:8765")
    laptop.unpair(phone.device_id)

    assert phone.device_id not in {p.id for p in laptop.peers()}
    assert phone.device_id not in laptop.peer_urls()
    assert before.id in {m.id for m in laptop.mixes()}
    assert any(e.type is EventType.DEVICE_UNPAIRED for e in laptop.export_events())

    after = _add_mix(phone, src, title="After unpair", platform_id="after-1")
    laptop.connect(phone)
    laptop.sync(fill=False)
    phone.sync(fill=False)
    assert after.id not in {m.id for m in laptop.mixes()}
    assert before.id in {m.id for m in laptop.mixes()}
    assert phone.device_id not in {p.id for p in laptop.peers()}

    # Re-pair requires the QR / short-code path (pairing payload), not mere sync.
    laptop.pair(phone.pairing_payload())
    laptop.sync(fill=False)
    phone.sync(fill=False)

    assert phone.device_id in {p.id for p in laptop.peers()}
    assert after.id in {m.id for m in laptop.mixes()}
    assert next(m for m in laptop.mixes() if m.id == after.id).title == "After unpair"


def test_unpair_drops_buffered_events_for_peer(tmp_path: Path) -> None:
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
    mix = _add_mix(phone, src, title="Buffered then unpaired", platform_id="buf-1")
    laptop.ingest_events(phone.export_events())
    assert mix.id not in {m.id for m in laptop.mixes()}

    # Unpair while the author's events are still buffered (never paired locally).
    laptop.unpair(phone.device_id)
    laptop.pair(phone.pairing_payload())
    assert mix.id not in {m.id for m in laptop.mixes()}

    laptop.ingest_events(phone.export_events())
    assert mix.id in {m.id for m in laptop.mixes()}

    laptop.unpair(phone.device_id)
    later = _add_mix(phone, src, title="Should stay ignored", platform_id="buf-2")
    laptop.ingest_events(phone.export_events())
    assert later.id not in {m.id for m in laptop.mixes()}

    laptop.pair(phone.pairing_payload())
    laptop.ingest_events(phone.export_events())
    assert later.id in {m.id for m in laptop.mixes()}


def test_unpair_replicates_so_third_peer_stops_trusting(tmp_path: Path) -> None:
    laptop, phone, src = _pair(tmp_path)
    tablet = DeviceAgent(
        "tablet",
        priority=20,
        source=src,
        data_dir=tmp_path / "tablet",
    )
    laptop.connect(tablet)
    tablet.pair(laptop.pairing_payload())
    laptop.sync(fill=False)
    tablet.sync(fill=False)
    phone.sync(fill=False)
    tablet.sync(fill=False)
    assert phone.device_id in {p.id for p in tablet.peers()}

    before = _add_mix(phone, src, title="Shared before", platform_id="shared-before")
    laptop.sync(fill=False)
    phone.sync(fill=False)
    tablet.sync(fill=False)
    assert before.id in {m.id for m in tablet.mixes()}

    laptop.unpair(phone.device_id)
    laptop.sync(fill=False)
    tablet.sync(fill=False)

    assert phone.device_id not in {p.id for p in tablet.peers()}
    assert before.id in {m.id for m in tablet.mixes()}

    after = _add_mix(phone, src, title="Shared after", platform_id="shared-after")
    tablet.ingest_events(
        [e for e in phone.export_events() if e.device_id == phone.device_id]
    )
    assert after.id not in {m.id for m in tablet.mixes()}
