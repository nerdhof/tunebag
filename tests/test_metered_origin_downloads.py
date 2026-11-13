"""Issue 05: metered origin downloads — exercised only through DeviceAgent."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from mixy.agent import DeviceAgent
from mixy.domain import Platform, Stars
from mixy.source import FakeSource


def _pair(
    tmp_path: Path,
    *,
    source: FakeSource | None = None,
) -> tuple[DeviceAgent, DeviceAgent, FakeSource]:
    src = source or FakeSource()
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
    return laptop, phone, src


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


def test_simulated_switch_marks_link_metered(tmp_path: Path) -> None:
    laptop, _phone, _source = _pair(tmp_path)
    assert laptop.is_metered() is False

    laptop.set_metered(True)

    assert laptop.is_metered() is True
    laptop.set_metered(False)
    assert laptop.is_metered() is False


def _three_hour_plan(
    laptop: DeviceAgent, source: FakeSource, *, name: str
) -> tuple[UUID, UUID, UUID, UUID]:
    """Create three 1h mixes and a 3h intent; return (intent_id, a, b, c) in assignment order."""
    ids = [
        _add_mix(
            laptop,
            source,
            title=f"Mix {n}",
            duration_seconds=3600,
            platform_id=f"{name}-{n}",
            stars=Stars.FIVE if n < 3 else Stars.FOUR,
        )
        for n in range(1, 4)
    ]
    intent = laptop.create_intent(
        name,
        seed=1,
        device_hours=[(laptop.device_id, 10800)],
    )
    assignment = laptop.assignment(intent.id)
    assert assignment is not None
    assert len(assignment.mix_ids) == 3
    assert set(assignment.mix_ids) == set(ids)
    a, b, c = assignment.mix_ids
    return intent.id, a, b, c


def test_metered_origin_stays_within_current_and_one_ahead(tmp_path: Path) -> None:
    laptop, _phone, source = _pair(tmp_path)
    _intent_id, first, second, third = _three_hour_plan(laptop, source, name="Metered plan")

    laptop.set_metered(True)
    laptop.set_current_mix(first)
    laptop.fill_caches()

    assert {m.id for m in laptop.files()} == {first, second}
    third_url = laptop.catalog.mixes[third].url
    assert third_url not in source.fetch_calls
    assert source.fetch_calls == [
        laptop.catalog.mixes[first].url,
        laptop.catalog.mixes[second].url,
    ]


def test_metered_includes_resumed_current_mix(tmp_path: Path) -> None:
    laptop, _phone, source = _pair(tmp_path)
    _intent_id, first, second, third = _three_hour_plan(laptop, source, name="Resume plan")

    # Resuming the second mix: allow second + one ahead (third), not first.
    laptop.set_metered(True)
    laptop.set_current_mix(second)
    laptop.fill_caches()

    assert {m.id for m in laptop.files()} == {second, third}
    assert laptop.catalog.mixes[first].url not in source.fetch_calls


def test_existing_files_stay_when_link_becomes_metered(tmp_path: Path) -> None:
    laptop, _phone, source = _pair(tmp_path)
    intent_id, first, second, third = _three_hour_plan(laptop, source, name="Surplus stays")
    laptop.fill_caches()
    assert {m.id for m in laptop.files()} == {first, second, third}

    laptop.set_metered(True)
    laptop.set_current_mix(first)
    source.fetch_calls.clear()
    laptop.fill_caches()

    assert {m.id for m in laptop.files()} == {first, second, third}
    assert source.fetch_calls == []
    assert laptop.assignment(intent_id) is not None


def test_fill_now_tops_one_intent_once_then_cap_returns(tmp_path: Path) -> None:
    laptop, _phone, source = _pair(tmp_path)
    intent_id, first, second, third = _three_hour_plan(laptop, source, name="Fill now plan")
    laptop.set_metered(True)
    laptop.set_current_mix(first)
    laptop.fill_caches()
    assert {m.id for m in laptop.files()} == {first, second}

    # Drop local files so Fill now must origin-fetch the full hours.
    for mix_id in (first, second, third):
        laptop.remove_local_file(mix_id)
    source.fetch_calls.clear()

    laptop.fill_now(intent_id)

    assert {m.id for m in laptop.files()} == {first, second, third}
    assert laptop.is_metered() is True

    # Cap returns: remove surplus (third) and standing fill must not re-fetch it.
    laptop.remove_local_file(third)
    source.fetch_calls.clear()
    laptop.fill_caches()

    assert {m.id for m in laptop.files()} == {first, second}
    assert laptop.catalog.mixes[third].url not in source.fetch_calls


def test_peer_copy_ignores_metered_cap(tmp_path: Path) -> None:
    laptop, phone, source = _pair(tmp_path)
    ids = [
        _add_mix(
            laptop,
            source,
            title=f"Mix {n}",
            duration_seconds=3600,
            platform_id=f"peer-{n}",
            stars=Stars.FIVE if n < 3 else Stars.FOUR,
        )
        for n in range(1, 4)
    ]
    intent = laptop.create_intent(
        "Peer ignore metered",
        seed=1,
        device_hours=[
            (phone.device_id, 10800),
            (laptop.device_id, 10800),
        ],
    )
    phone.sync()
    assignment = laptop.assignment(intent.id)
    assert assignment is not None
    first, _second, _third = assignment.mix_ids
    laptop.fill_caches()
    assert {m.id for m in laptop.files()} == set(ids)

    phone.set_metered(True)
    phone.set_current_mix(first)
    source.fetch_calls.clear()
    phone.fill_caches()

    assert {m.id for m in phone.files()} == set(ids)
    assert source.fetch_calls == []
    assert phone.assignment(intent.id) is not None


def test_catalog_sync_still_happens_on_metered_link(tmp_path: Path) -> None:
    laptop, phone, source = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Tagged later",
        duration_seconds=3600,
        platform_id="tagged",
        stars=Stars.FIVE,
        tags=["techno"],
    )
    laptop.create_intent(
        "Sync on metered",
        seed=1,
        tags=["techno"],
        device_hours=[
            (phone.device_id, 3600),
            (laptop.device_id, 3600),
        ],
    )
    phone.sync()
    laptop.tag_mix(mix_id, ["techno", "peak"])

    phone.set_metered(True)
    phone.set_current_mix(mix_id)
    phone.sync()

    synced = phone.catalog.mixes[mix_id]
    assert synced.tags == ["techno", "peak"]
