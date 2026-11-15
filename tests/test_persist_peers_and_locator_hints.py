"""Issue 03 (durable-sync): trusted Peers survive restart; sync without re-pair."""

from __future__ import annotations

from pathlib import Path

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform
from tunebag.source import FakeSource


def test_after_restart_paired_peers_sync_catalog_without_re_pair(
    tmp_path: Path,
) -> None:
    src = FakeSource()
    laptop_dir = tmp_path / "laptop"
    phone_dir = tmp_path / "phone"
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=laptop_dir,
    )
    phone = DeviceAgent(
        "phone",
        priority=10,
        source=src,
        data_dir=phone_dir,
    )
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    laptop.wait_for_sync()
    phone.wait_for_sync()

    url = "https://example.com/post-restart"
    src.bytes_by_url[url] = b"audio:post-restart"
    mix = laptop.add_mix(
        title="After pair before restart",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="post-restart-1",
        artist_name="DJ Example",
    )
    laptop.sync(fill=False)
    phone.sync(fill=False)
    assert mix.id in {m.id for m in phone.mixes()}

    # Restart both Devices on their data dirs (drop live meet / reachability).
    laptop2 = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=laptop_dir,
    )
    phone2 = DeviceAgent(
        "phone",
        priority=10,
        source=src,
        data_dir=phone_dir,
    )

    assert {p.id for p in laptop2.peers()} == {phone.device_id}
    assert {p.id for p in phone2.peers()} == {laptop.device_id}

    url2 = "https://example.com/after-restart-sync"
    src.bytes_by_url[url2] = b"audio:after-restart"
    mix2 = laptop2.add_mix(
        title="After restart",
        url=url2,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="after-restart-1",
        artist_name="DJ Example",
    )

    # Meet again without QR / short-code pairing.
    laptop2.connect(phone2)
    laptop2.sync(fill=False)
    phone2.sync(fill=False)

    assert mix.id in {m.id for m in phone2.mixes()}
    assert mix2.id in {m.id for m in phone2.mixes()}
    assert mix2.id in {m.id for m in laptop2.mixes()}
    assert next(m for m in phone2.mixes() if m.id == mix2.id).title == "After restart"
