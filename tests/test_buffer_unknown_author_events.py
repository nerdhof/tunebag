"""Issue 05 (durable-sync): buffer unknown-author events via DeviceAgent."""

from __future__ import annotations

from pathlib import Path

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform
from tunebag.source import FakeSource


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


def test_ingest_does_not_apply_unknown_author_events_until_paired(tmp_path: Path) -> None:
    src = FakeSource()
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=tmp_path / "laptop",
    )
    tablet = DeviceAgent(
        "tablet",
        priority=20,
        source=src,
        data_dir=tmp_path / "tablet",
    )
    mix = _add_mix(tablet, src, title="Tablet set", platform_id="tablet-set-1")

    laptop.ingest_events(tablet.export_events())

    assert mix.id not in {m.id for m in laptop.mixes()}
    assert [p.name for p in laptop.peers()] == []

    laptop.pair(tablet.pairing_payload())

    assert mix.id in {m.id for m in laptop.mixes()}
    assert next(m for m in laptop.mixes() if m.id == mix.id).title == "Tablet set"
    assert [p.name for p in laptop.peers()] == ["tablet"]


def test_pairing_via_synced_device_paired_unlocks_buffered_events(tmp_path: Path) -> None:
    """Dependent events arrive before author pairing visibility; DEVICE_PAIRED unlocks Catalog."""
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
    tablet = DeviceAgent(
        "tablet",
        priority=20,
        source=src,
        data_dir=tmp_path / "tablet",
    )

    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    laptop.sync(fill=False)
    phone.sync(fill=False)
    # Disconnect so phone↔tablet work cannot auto-sync into laptop.
    laptop.disconnect(phone)

    phone.connect(tablet)
    tablet.pair(phone.pairing_payload())
    mix = _add_mix(tablet, src, title="Relay set", platform_id="relay-set-1")
    phone.sync(fill=False)
    tablet.sync(fill=False)

    # Laptop sees Tablet-authored rows before any DEVICE_PAIRED for Tablet.
    tablet_authored = [e for e in phone.export_events() if e.device_id == tablet.device_id]
    assert tablet_authored
    laptop.ingest_events(tablet_authored)
    assert mix.id not in {m.id for m in laptop.mixes()}
    assert "tablet" not in {p.name for p in laptop.peers()}

    # Phone-authored DEVICE_PAIRED(Tablet) makes the author known → buffer flushes.
    pair_events = [
        e
        for e in phone.export_events()
        if e.device_id == phone.device_id
        and e.payload.get("id") == str(tablet.device_id)
    ]
    assert pair_events
    laptop.ingest_events(pair_events)

    assert mix.id in {m.id for m in laptop.mixes()}
    assert next(m for m in laptop.mixes() if m.id == mix.id).title == "Relay set"
    assert "tablet" in {p.name for p in laptop.peers()}
