"""Issue 04: fill caches — exercised only through DeviceAgent."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.source import FakeSource


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


def test_laptop_fills_assignment_from_origin(tmp_path: Path) -> None:
    laptop, _phone, source = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Set A",
        duration_seconds=3600,
        platform_id="a",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Fill",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )

    laptop.fill_caches()

    assert [m.id for m in laptop.files()] == [mix_id]
    assert source.fetch_calls == ["https://example.com/a"]
    assignment = laptop.assignment(intent.id)
    assert assignment is not None
    assert assignment.mix_ids == [mix_id]


def test_phone_copies_shared_mix_from_laptop_not_origin(tmp_path: Path) -> None:
    laptop, phone, source = _pair(tmp_path)
    shared = _add_mix(
        laptop,
        source,
        title="Shared",
        duration_seconds=3600,
        platform_id="shared",
        stars=Stars.FIVE,
    )
    _add_mix(
        laptop,
        source,
        title="Laptop only",
        duration_seconds=3600,
        platform_id="laptop-only",
        stars=Stars.FOUR,
    )
    intent = laptop.create_intent(
        "Shared plan",
        seed=1,
        device_hours=[
            (phone.device_id, 3600),
            (laptop.device_id, 7200),
        ],
    )
    phone.sync()
    laptop.sync()

    laptop.fill_caches()
    phone_calls_before = list(source.fetch_calls)
    phone.fill_caches()

    assert shared in {m.id for m in phone.files()}
    phone_assignment = phone.assignment(intent.id)
    assert phone_assignment is not None
    assert phone_assignment.mix_ids == [shared]
    # Phone did not origin-fetch the shared mix.
    assert source.fetch_calls == phone_calls_before


def test_phone_gets_shared_mix_as_soon_as_laptop_has_it(tmp_path: Path) -> None:
    laptop, phone, source = _pair(tmp_path)
    first = _add_mix(
        laptop,
        source,
        title="First",
        duration_seconds=3600,
        platform_id="first",
        stars=Stars.FIVE,
    )
    second = _add_mix(
        laptop,
        source,
        title="Second",
        duration_seconds=3600,
        platform_id="second",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Progressive",
        seed=1,
        device_hours=[
            (phone.device_id, 7200),
            (laptop.device_id, 7200),
        ],
    )
    phone.sync()
    assignment = laptop.assignment(intent.id)
    assert assignment is not None
    assert set(assignment.mix_ids) == {first, second}
    head, tail = assignment.mix_ids[0], assignment.mix_ids[1]
    head_url = laptop.catalog.mixes[head].url

    # Simulate laptop having only the sequence head so far.
    laptop._store_local_file(head, source.bytes_by_url[head_url])
    calls_before = list(source.fetch_calls)
    phone.fill_caches()

    assert {m.id for m in phone.files()} == {head}
    assert source.fetch_calls == calls_before
    # Tail still missing on phone — waited for preferred peer, no origin fetch.
    assert tail not in {m.id for m in phone.files()}


def test_phone_origin_fetches_phone_only_mixes(tmp_path: Path) -> None:
    laptop, phone, source = _pair(tmp_path)
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
    intent = laptop.create_intent(
        "Phone heavy",
        seed=1,
        device_hours=[
            (laptop.device_id, 3600),
            (phone.device_id, 7200),
        ],
    )
    phone.sync()
    laptop.fill_caches()
    phone.fill_caches()

    phone_ids = {m.id for m in phone.files()}
    assert shared in phone_ids
    assert phone_only in phone_ids
    assert "https://example.com/phone-only" in source.fetch_calls
    # Shared mix is the laptop's origin job while reachable.
    assert source.fetch_calls.count("https://example.com/shared") == 1
    phone_assignment = phone.assignment(intent.id)
    assert phone_assignment is not None
    assert set(phone_assignment.mix_ids) == {shared, phone_only}


def test_phone_origin_fetches_when_laptop_unreachable(tmp_path: Path) -> None:
    laptop, phone, source = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Commute",
        duration_seconds=3600,
        platform_id="commute",
        stars=Stars.FIVE,
    )
    laptop.create_intent(
        "Commute plan",
        seed=1,
        device_hours=[
            (phone.device_id, 3600),
            (laptop.device_id, 3600),
        ],
    )
    phone.sync()
    phone.disconnect(laptop)
    source.fetch_calls.clear()

    phone.fill_caches()

    assert [m.id for m in phone.files()] == [mix_id]
    assert source.fetch_calls == ["https://example.com/commute"]


def test_peer_copy_preferred_over_origin(tmp_path: Path) -> None:
    laptop, phone, source = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Already on phone",
        duration_seconds=3600,
        platform_id="peer",
        stars=Stars.FIVE,
    )
    laptop.create_intent(
        "Peer first",
        seed=1,
        device_hours=[
            (phone.device_id, 3600),
            (laptop.device_id, 3600),
        ],
    )
    phone.sync()
    # Phone somehow has the file; laptop should copy instead of origin-fetch.
    phone._store_local_file(mix_id, source.bytes_by_url["https://example.com/peer"])
    source.fetch_calls.clear()

    laptop.fill_caches()

    assert [m.id for m in laptop.files()] == [mix_id]
    assert source.fetch_calls == []


def test_intent_folder_contains_assigned_files(tmp_path: Path) -> None:
    laptop, _phone, source = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Folder Mix",
        duration_seconds=3600,
        platform_id="folder",
        stars=Stars.FIVE,
    )
    intent = laptop.create_intent(
        "Folder plan",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )

    laptop.fill_caches()

    folder = laptop.intent_folder(intent.id)
    files = list(folder.iterdir())
    assert len(files) == 1
    assert files[0].read_bytes() == source.bytes_by_url["https://example.com/folder"]
    assert mix_id in {m.id for m in laptop.files()}


def test_sync_fills_caches_from_peer(tmp_path: Path) -> None:
    laptop, phone, source = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="After sync",
        duration_seconds=3600,
        platform_id="after-sync",
        stars=Stars.FIVE,
    )
    laptop.create_intent(
        "Sync fill",
        seed=1,
        device_hours=[
            (phone.device_id, 3600),
            (laptop.device_id, 3600),
        ],
    )
    laptop.fill_caches()
    source.fetch_calls.clear()

    phone.sync()

    assert [m.id for m in phone.files()] == [mix_id]
    assert source.fetch_calls == []


def test_removed_file_can_be_downloaded_again(tmp_path: Path) -> None:
    laptop, _phone, source = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Again",
        duration_seconds=3600,
        platform_id="again",
        stars=Stars.FIVE,
    )
    laptop.create_intent(
        "Again plan",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    laptop.fill_caches()
    assert source.fetch_calls == ["https://example.com/again"]

    laptop.remove_local_file(mix_id)
    assert laptop.files() == []

    laptop.fill_caches()

    assert [m.id for m in laptop.files()] == [mix_id]
    assert source.fetch_calls == [
        "https://example.com/again",
        "https://example.com/again",
    ]
