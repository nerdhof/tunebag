"""Issue 07: reject with 20s undo — exercised only through DeviceAgent."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from mixy.agent import DeviceAgent
from mixy.domain import Platform, Stars
from mixy.reject import UNDO_SECONDS
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
    return laptop, phone, src, clk


def _add_mix(
    agent: DeviceAgent,
    source: FakeSource,
    *,
    title: str,
    duration_seconds: int,
    platform_id: str,
    tags: list[str] | None = None,
    stars: Stars | None = None,
    audio: bytes | None = None,
) -> UUID:
    url = f"https://example.com/{platform_id}"
    source.bytes_by_url[url] = audio if audio is not None else f"audio:{platform_id}".encode()
    mix = agent.add_mix(
        title=title,
        url=url,
        duration_seconds=duration_seconds,
        platform=Platform.SOUNDCLOUD,
        platform_id=platform_id,
        artist_name="DJ Example",
    )
    if tags is not None:
        agent.tag_mix(mix.id, tags)
    if stars is not None:
        agent.rate_mix(mix.id, stars)
    return mix.id


def test_reject_window_is_local_until_commit(tmp_path: Path) -> None:
    laptop, phone, source, _clock = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Maybe reject",
        duration_seconds=3600,
        platform_id="maybe",
        stars=Stars.FIVE,
    )
    laptop.create_intent(
        "Plan",
        seed=1,
        device_hours=[
            (phone.device_id, 3600),
            (laptop.device_id, 3600),
        ],
    )
    phone.sync()
    laptop.fill_caches()
    phone.fill_caches()
    assert mix_id in {m.id for m in laptop.files()}
    assert mix_id in {m.id for m in phone.files()}

    laptop.reject_mix(mix_id)

    assert laptop.catalog.mixes[mix_id].rejected is False
    assert any(p.mix_id == mix_id for p in laptop.pending_rejects())
    phone.sync()
    laptop.sync()
    assert phone.catalog.mixes[mix_id].rejected is False
    assert mix_id in {m.id for m in phone.files()}
    assert mix_id in {m.id for m in laptop.files()}


def test_undo_during_window_keeps_mix_eligible(tmp_path: Path) -> None:
    laptop, _phone, source, _clock = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Undo me",
        duration_seconds=3600,
        platform_id="undo",
        tags=["techno"],
        stars=Stars.FIVE,
    )

    laptop.reject_mix(mix_id)
    assert laptop.undo_reject(mix_id) is True
    assert laptop.pending_rejects() == []
    assert laptop.catalog.mixes[mix_id].rejected is False

    intent = laptop.create_intent(
        "Techno",
        tags=["techno"],
        seed=0,
        device_hours=[(laptop.device_id, 3600)],
    )
    seq = laptop.sequence(intent.id)
    assert seq is not None
    assert mix_id in {e.mix_id for e in seq.entries}


def test_committed_reject_deletes_file_on_every_device(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Gone",
        duration_seconds=3600,
        platform_id="gone",
        stars=Stars.FIVE,
    )
    laptop.create_intent(
        "Plan",
        seed=1,
        device_hours=[
            (phone.device_id, 3600),
            (laptop.device_id, 3600),
        ],
    )
    phone.sync()
    laptop.fill_caches()
    phone.fill_caches()

    laptop.reject_mix(mix_id)
    clock.advance(UNDO_SECONDS)
    committed = laptop.commit_pending_rejects()

    assert committed == [mix_id]
    assert laptop.catalog.mixes[mix_id].rejected is True
    assert mix_id not in {m.id for m in laptop.files()}

    phone.sync()
    assert phone.catalog.mixes[mix_id].rejected is True
    assert mix_id not in {m.id for m in phone.files()}


def test_committed_reject_stays_out_of_sequences(tmp_path: Path) -> None:
    laptop, _phone, source, clock = _pair(tmp_path)
    keeper = _add_mix(
        laptop,
        source,
        title="Four star keeper",
        duration_seconds=3600,
        platform_id="four",
        tags=["techno"],
        stars=Stars.FOUR,
    )
    rejected = _add_mix(
        laptop,
        source,
        title="Rejected five",
        duration_seconds=3600,
        platform_id="rej",
        tags=["techno"],
        stars=Stars.FIVE,
    )

    laptop.reject_mix(rejected)
    clock.advance(UNDO_SECONDS)
    laptop.commit_pending_rejects()

    intent = laptop.create_intent(
        "Techno",
        tags=["techno"],
        seed=0,
        device_hours=[(laptop.device_id, 3600)],
    )
    seq = laptop.sequence(intent.id)
    assert seq is not None
    assert [e.mix_id for e in seq.entries] == [keeper]
    assert rejected not in {e.mix_id for e in seq.entries}
