"""Issue 08: expire one device's hours — exercised only through DeviceAgent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

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


def test_phone_expiry_leaves_laptop_on_intent(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Shared",
        duration_seconds=3600,
        platform_id="shared",
        stars=Stars.FIVE,
    )
    expires_at = clock() + timedelta(hours=1)
    intent = laptop.create_intent(
        "Plan",
        seed=1,
        device_hours=[
            (phone.device_id, 3600, expires_at),
            (laptop.device_id, 7200),
        ],
    )
    phone.sync()
    laptop.fill_caches()
    phone.fill_caches()
    assert mix_id in {m.id for m in phone.files()}
    assert mix_id in {m.id for m in laptop.files()}

    clock.advance(3600)
    phone.sync()  # listener path: sync applies due expiries
    laptop.sync()

    phone_intent = next(i for i in phone.intents() if i.id == intent.id)
    assert phone.device_id not in {dh.device_id for dh in phone_intent.device_hours}
    laptop_hours = next(
        dh for dh in phone_intent.device_hours if dh.device_id == laptop.device_id
    )
    assert laptop_hours.budget_seconds == 7200
    assert phone.assignment(intent.id) is None
    laptop_asg = laptop.assignment(intent.id)
    assert laptop_asg is not None
    assert mix_id in laptop_asg.mix_ids
    assert mix_id in {m.id for m in laptop.files()}


def test_expiry_deletes_exclusive_phone_file_keeps_laptop(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    shared = _add_mix(
        laptop,
        source,
        title="Shared",
        duration_seconds=3600,
        platform_id="shared",
        stars=Stars.FIVE,
    )
    phone_only = _add_mix(
        laptop,
        source,
        title="Phone only",
        duration_seconds=3600,
        platform_id="phone-only",
        stars=Stars.FOUR,
    )
    expires_at = clock() + timedelta(hours=1)
    intent = laptop.create_intent(
        "Phone heavy",
        seed=1,
        device_hours=[
            (laptop.device_id, 3600),
            (phone.device_id, 7200, expires_at),
        ],
    )
    phone.sync()
    laptop.fill_caches()
    phone.fill_caches()
    assert {shared, phone_only} <= {m.id for m in phone.files()}
    assert shared in {m.id for m in laptop.files()}
    assert phone_only not in {m.id for m in laptop.files()}

    clock.advance(3600)
    phone.apply_expired_hours()

    assert phone.assignment(intent.id) is None
    assert phone_only not in {m.id for m in phone.files()}
    # Shared was only needed by the expired phone assignment on phone.
    assert shared not in {m.id for m in phone.files()}
    assert shared in {m.id for m in laptop.files()}


def test_playing_mix_survives_expiry_until_stop(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Now playing",
        duration_seconds=3600,
        platform_id="playing",
        stars=Stars.FIVE,
    )
    expires_at = clock() + timedelta(hours=1)
    intent = laptop.create_intent(
        "Commute",
        seed=1,
        device_hours=[
            (phone.device_id, 3600, expires_at),
            (laptop.device_id, 3600),
        ],
    )
    phone.sync()
    laptop.fill_caches()
    phone.fill_caches()
    phone.play(intent.id, mix_id)
    assert phone.is_playing()
    assert phone.current_mix() == mix_id

    clock.advance(3600)
    phone.apply_expired_hours()

    assert phone.assignment(intent.id) is None
    assert mix_id in {m.id for m in phone.files()}

    phone.stop()
    assert mix_id not in {m.id for m in phone.files()}


def test_mix_wanted_by_other_live_assignment_stays(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Both plans",
        duration_seconds=3600,
        platform_id="both",
        tags=["deep"],
        stars=Stars.FIVE,
    )
    expires_at = clock() + timedelta(hours=1)
    expiring = laptop.create_intent(
        "Expiring",
        tags=["deep"],
        seed=1,
        device_hours=[
            (phone.device_id, 3600, expires_at),
            (laptop.device_id, 3600),
        ],
    )
    keeper = laptop.create_intent(
        "Keeper",
        tags=["deep"],
        seed=1,
        device_hours=[
            (phone.device_id, 3600),
            (laptop.device_id, 3600),
        ],
    )
    phone.sync()
    laptop.fill_caches()
    phone.fill_caches()
    assert mix_id in {m.id for m in phone.files()}
    assert phone.assignment(expiring.id) is not None
    assert phone.assignment(keeper.id) is not None

    clock.advance(3600)
    phone.apply_expired_hours()

    assert phone.assignment(expiring.id) is None
    keeper_asg = phone.assignment(keeper.id)
    assert keeper_asg is not None
    assert mix_id in keeper_asg.mix_ids
    assert mix_id in {m.id for m in phone.files()}


def test_expiry_removes_device_not_shrink_budget(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    _add_mix(
        laptop,
        source,
        title="One",
        duration_seconds=3600,
        platform_id="one",
        stars=Stars.FIVE,
    )
    expires_at = clock() + timedelta(minutes=30)
    intent = laptop.create_intent(
        "Temp phone",
        seed=1,
        device_hours=[
            (phone.device_id, 7200, expires_at),
            (laptop.device_id, 7200),
        ],
    )
    phone.sync()

    clock.advance(30 * 60)
    phone.sync()
    laptop.sync()

    updated = next(i for i in laptop.intents() if i.id == intent.id)
    phone_rows = [dh for dh in updated.device_hours if dh.device_id == phone.device_id]
    assert phone_rows == []
    laptop_row = next(dh for dh in updated.device_hours if dh.device_id == laptop.device_id)
    assert laptop_row.budget_seconds == 7200


def test_aware_expires_at_does_not_crash_sync_or_block_peer_catalog(
    tmp_path: Path,
) -> None:
    """UI ISO-Z expiry must not 500 /api/sync and block peer catalog writes."""
    laptop, phone, _source, _clock = _pair(tmp_path)
    laptop.wait_for_sync()
    phone.wait_for_sync()

    aware_expiry = datetime(2024, 1, 1, 13, 0, 0, tzinfo=UTC)
    intent = laptop.create_intent(
        "Temp phone",
        seed=1,
        device_hours=[
            (phone.device_id, 3600, aware_expiry),
            (laptop.device_id, 7200),
        ],
    )
    phone_hours = next(
        dh for dh in intent.device_hours if dh.device_id == phone.device_id
    )
    assert phone_hours.expires_at is not None
    assert phone_hours.expires_at.tzinfo is None
    assert phone_hours.expires_at == datetime(2024, 1, 1, 13, 0, 0)

    # Pre-fix catalog state: aware expires_at already in memory.
    poisoned = intent.model_copy(
        update={
            "device_hours": [
                dh.model_copy(update={"expires_at": aware_expiry})
                if dh.device_id == phone.device_id
                else dh
                for dh in intent.device_hours
            ]
        }
    )
    laptop.catalog.upsert_intent(poisoned)
    phone.catalog.upsert_intent(poisoned)

    laptop.sync(fill=False)
    phone.sync(fill=False)

    mix = laptop.add_mix(
        title="After aware expiry",
        url="https://example.com/after-aware",
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="after-aware",
        artist_name="DJ Example",
    )
    laptop.wait_for_sync()
    phone.wait_for_sync()
    assert mix.id in {m.id for m in phone.mixes()}

    laptop.delete_intent(intent.id)
    laptop.wait_for_sync()
    phone.wait_for_sync()
    assert intent.id not in {i.id for i in phone.intents()}
