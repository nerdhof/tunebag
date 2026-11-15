"""Issue 02 (ui-view-notices): Notices on Peer Event-log ingest."""

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
    laptop.wait_for_sync()
    phone.wait_for_sync()
    return laptop, phone, src, clk


def _sections(agent: DeviceAgent) -> list[UIViewSection]:
    return [n.section for n in agent.drain_view_notices()]


def test_peer_mix_ingest_emits_coalesced_mixes(tmp_path: Path) -> None:
    """One sync pass ingesting Artist+Mix emits a single mixes notice on the receiver."""
    laptop, phone, source, _clock = _pair(tmp_path)
    laptop.disconnect(phone)
    laptop.wait_for_sync()
    phone.wait_for_sync()
    laptop.drain_view_notices()
    phone.drain_view_notices()

    url = "https://example.com/peer-mix"
    source.bytes_by_url[url] = b"audio:peer-mix"
    mix = laptop.add_mix(
        title="Peer set",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="peer-mix-1",
        artist_name="DJ Peer",
    )
    assert mix.id not in {m.id for m in phone.mixes()}

    laptop.connect(phone)
    laptop.wait_for_sync()
    phone.wait_for_sync()

    assert mix.id in {m.id for m in phone.mixes()}
    assert _sections(phone) == [UIViewSection.MIXES]


def test_peer_rate_ingest_emits_mixes_and_play_history(tmp_path: Path) -> None:
    laptop, phone, source, _clock = _pair(tmp_path)
    url = "https://example.com/rate-mix"
    source.bytes_by_url[url] = b"audio:rate-mix"
    mix = laptop.add_mix(
        title="Rate set",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="rate-mix-1",
        artist_name="DJ Peer",
    )
    laptop.wait_for_sync()
    phone.wait_for_sync()
    assert mix.id in {m.id for m in phone.mixes()}

    laptop.disconnect(phone)
    laptop.wait_for_sync()
    phone.wait_for_sync()
    laptop.drain_view_notices()
    phone.drain_view_notices()

    laptop.rate_mix(mix.id, Stars.FIVE)
    laptop.connect(phone)
    laptop.wait_for_sync()
    phone.wait_for_sync()

    assert _sections(phone) == [UIViewSection.MIXES, UIViewSection.PLAY_HISTORY]


def test_peer_tag_ingest_emits_mixes_and_play_history(tmp_path: Path) -> None:
    laptop, phone, source, _clock = _pair(tmp_path)
    url = "https://example.com/tag-mix"
    source.bytes_by_url[url] = b"audio:tag-mix"
    mix = laptop.add_mix(
        title="Tag set",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="tag-mix-1",
        artist_name="DJ Peer",
    )
    laptop.wait_for_sync()
    phone.wait_for_sync()
    assert mix.id in {m.id for m in phone.mixes()}

    laptop.disconnect(phone)
    laptop.wait_for_sync()
    phone.wait_for_sync()
    laptop.drain_view_notices()
    phone.drain_view_notices()

    laptop.tag_mix(mix.id, ["deep"])
    laptop.connect(phone)
    laptop.wait_for_sync()
    phone.wait_for_sync()

    assert _sections(phone) == [UIViewSection.MIXES, UIViewSection.PLAY_HISTORY]


def test_peer_intent_ingest_emits_single_coalesced_intents(tmp_path: Path) -> None:
    """Intent upsert + Sequence + Assignments from a Peer coalesce to one intents notice."""
    laptop, phone, source, _clock = _pair(tmp_path)
    url = "https://example.com/intent-mix"
    source.bytes_by_url[url] = b"audio:intent-mix"
    mix = laptop.add_mix(
        title="Intent set",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="intent-mix-1",
        artist_name="DJ Peer",
    )
    laptop.rate_mix(mix.id, Stars.FIVE)
    laptop.wait_for_sync()
    phone.wait_for_sync()

    laptop.disconnect(phone)
    laptop.wait_for_sync()
    phone.wait_for_sync()
    laptop.drain_view_notices()
    phone.drain_view_notices()

    intent = laptop.create_intent(
        "Deep",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    laptop.connect(phone)
    laptop.wait_for_sync()
    phone.wait_for_sync()

    assert intent.id in {i.id for i in phone.intents()}
    assert _sections(phone) == [UIViewSection.INTENTS]


def test_ingested_device_paired_and_unpaired_emit_peers(tmp_path: Path) -> None:
    """Peer-set Catalog Events from sync emit peers on the receiving Device."""
    laptop, phone, source, _clock = _pair(tmp_path)
    laptop.disconnect(phone)
    laptop.wait_for_sync()
    phone.wait_for_sync()

    tablet = DeviceAgent(
        "tablet",
        priority=5,
        source=source,
        data_dir=tmp_path / "tablet",
        player=NullPlayer(),
    )
    laptop.connect(tablet)
    tablet.pair(laptop.pairing_payload())
    laptop.wait_for_sync()
    tablet.wait_for_sync()

    phone.drain_view_notices()
    laptop.connect(phone)
    laptop.wait_for_sync()
    phone.wait_for_sync()

    assert tablet.device_id in {p.id for p in phone.peers()}
    assert UIViewSection.PEERS in set(_sections(phone))

    laptop.disconnect(phone)
    laptop.wait_for_sync()
    phone.wait_for_sync()
    laptop.unpair(tablet.device_id)
    phone.drain_view_notices()

    laptop.connect(phone)
    laptop.wait_for_sync()
    phone.wait_for_sync()

    assert tablet.device_id not in {p.id for p in phone.peers()}
    assert UIViewSection.PEERS in set(_sections(phone))


def test_full_log_catch_up_coalesces_per_section(tmp_path: Path) -> None:
    """Many Events in one sync pass emit at most one notice per affected section."""
    laptop, phone, source, _clock = _pair(tmp_path)
    laptop.disconnect(phone)
    laptop.wait_for_sync()
    phone.wait_for_sync()
    laptop.drain_view_notices()
    phone.drain_view_notices()

    for i in range(3):
        url = f"https://example.com/catch-up-{i}"
        source.bytes_by_url[url] = f"audio:catch-up-{i}".encode()
        mix = laptop.add_mix(
            title=f"Catch-up {i}",
            url=url,
            duration_seconds=3600,
            platform=Platform.SOUNDCLOUD,
            platform_id=f"catch-up-{i}",
            artist_name="DJ Peer",
        )
        laptop.rate_mix(mix.id, Stars.FIVE)
        laptop.tag_mix(mix.id, ["deep"])

    laptop.create_intent(
        "Catch-up intent",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )

    laptop.connect(phone)
    laptop.wait_for_sync()
    phone.wait_for_sync()

    sections = _sections(phone)
    assert sections == [
        UIViewSection.MIXES,
        UIViewSection.PLAY_HISTORY,
        UIViewSection.INTENTS,
    ]
    assert len(phone.mixes()) >= 3
    assert any(i.name == "Catch-up intent" for i in phone.intents())
