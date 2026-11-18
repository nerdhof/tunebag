"""Issue 04: fill caches — exercised only through DeviceAgent."""

from __future__ import annotations

import threading
from pathlib import Path
from uuid import UUID

import pytest

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
    laptop.wait_for_fill()
    # Drop the auto-fill so we can simulate a partial laptop cache.
    for mix in list(laptop.files()):
        laptop.remove_local_file(mix.id)
    phone.sync(fill=False)
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
    laptop.wait_for_fill()
    for mix in list(laptop.files()):
        laptop.remove_local_file(mix.id)
    phone.sync(fill=False)
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


def test_refresh_mid_fill_skips_stale_assignment_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After Explore refresh mid-fill, do not keep origin-fetching the old assignment.

    Live symptom: refresh re-rolls the sequence; Cache shows the new mixes as
    pending while fill walks the pre-refresh assignment (often multi-hour sets),
    so the UI looks stuck until that stale pass ends and a coalesced fill starts.
    """
    from tunebag.sequence import build_sequence

    fetch_started = threading.Event()
    release_fetch = threading.Event()
    fetch_urls: list[str] = []

    class GatedSource(FakeSource):
        def fetch_bytes(self, source_url: str, *, on_progress=None) -> bytes:
            fetch_urls.append(source_url)
            if len(fetch_urls) == 1:
                fetch_started.set()
                assert release_fetch.wait(timeout=5.0), "first fetch not released"
            return super().fetch_bytes(source_url, on_progress=on_progress)

    source = GatedSource()
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=source,
        data_dir=tmp_path / "laptop",
    )
    for i in range(8):
        _add_mix(
            laptop,
            source,
            title=f"Mix {i}",
            duration_seconds=3600,
            platform_id=f"refresh-mid-{i}",
            tags=["refresh-mid"],
            stars=Stars.FOUR,
        )

    # create_intent starts maintenance fill (blocked on gate until release_fetch).
    intent = laptop.create_intent(
        "Refresh mid fill",
        tags=["refresh-mid"],
        seed=1,
        device_hours=[(laptop.device_id, 3 * 3600)],
    )
    before = laptop.assignment(intent.id)
    assert before is not None
    assert len(before.mix_ids) == 3
    old_ids = list(before.mix_ids)
    old_tail_urls = [laptop.catalog.mixes[mid].url for mid in old_ids[1:]]

    alt_seed = None
    new_ids: list[UUID] = []
    for seed in range(2, 400):
        probe = intent.model_copy(update={"seed": seed})
        rebuilt = [
            entry.mix_id
            for entry in build_sequence(probe, laptop.catalog.mixes_list()).entries
        ]
        # Device budget is 3h; sequence may be longer — assignment is the prefix.
        candidate = rebuilt[:3]
        if len(candidate) == 3 and set(candidate).isdisjoint(old_ids):
            alt_seed = seed
            new_ids = candidate
            break
    assert alt_seed is not None, "could not find disjoint alternate seed for repro"
    monkeypatch.setattr(
        "tunebag.agent.random.randrange", lambda *_a, **_k: alt_seed
    )

    assert laptop.fill_in_progress is True
    assert fetch_started.wait(timeout=2.0), "fill never started old-assignment fetch"

    refreshed = laptop.refresh_intent_sequence(intent.id)
    assert refreshed.seed == alt_seed
    after = laptop.assignment(intent.id)
    assert after is not None
    assert after.mix_ids == new_ids

    groups = laptop.cache_groups()
    group = next(g for g in groups if g["id"] == intent.id)
    assert [m["id"] for m in group["mixes"]] == new_ids
    assert all(m["status"] == "pending" for m in group["mixes"])
    assert laptop.downloading_mix_id == old_ids[0]

    laptop.request_fill()
    release_fetch.set()
    laptop.wait_for_fill(timeout=5.0)

    new_urls = [laptop.catalog.mixes[mid].url for mid in new_ids]
    assert set(new_urls).issubset(set(fetch_urls))
    # Must not keep walking the pre-refresh assignment after the sequence changed.
    assert not set(old_tail_urls).intersection(fetch_urls), (
        f"stale tail still fetched: {sorted(set(old_tail_urls) & set(fetch_urls))}"
    )
    cached_ids = {m.id for m in laptop.files()}
    assert set(new_ids).issubset(cached_ids)
    assert not set(old_ids).intersection(cached_ids)


def test_fill_caches_picks_sooner_intent_before_later_mix(tmp_path: Path) -> None:
    """Cross-intent fill uses sequence urgency, not catalog intent order."""
    laptop, _phone, source = _pair(tmp_path)
    a0 = _add_mix(
        laptop,
        source,
        title="A0",
        duration_seconds=3600,
        platform_id="a0",
        tags=["alpha"],
        stars=Stars.FIVE,
    )
    a1 = _add_mix(
        laptop,
        source,
        title="A1",
        duration_seconds=3600,
        platform_id="a1",
        tags=["alpha"],
        stars=Stars.FIVE,
    )
    b0 = _add_mix(
        laptop,
        source,
        title="B0",
        duration_seconds=3600,
        platform_id="b0",
        tags=["bravo"],
        stars=Stars.FIVE,
    )
    intent_a = laptop.create_intent(
        "Alpha",
        tags=["alpha"],
        seed=1,
        device_hours=[(laptop.device_id, 7200)],
    )
    intent_b = laptop.create_intent(
        "Bravo",
        tags=["bravo"],
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    laptop.wait_for_fill()
    for mix in list(laptop.files()):
        laptop.remove_local_file(mix.id)
    assignment_a = laptop.assignment(intent_a.id)
    assignment_b = laptop.assignment(intent_b.id)
    assert assignment_a is not None and assignment_b is not None
    assert set(assignment_a.mix_ids) == {a0, a1}
    assert list(assignment_b.mix_ids) == [b0]
    head, tail = assignment_a.mix_ids[0], assignment_a.mix_ids[1]
    head_url = laptop.catalog.mixes[head].url
    tail_url = laptop.catalog.mixes[tail].url

    # Deep into Alpha's first mix: Bravo's head (urgency 0) beats Alpha's next
    # mix (urgency ≈ 100). Catalog order would still finish Alpha first.
    laptop._store_local_file(head, source.bytes_by_url[head_url])
    laptop.set_current_mix(head)
    laptop._playback_position = 3500.0
    source.fetch_calls.clear()

    laptop.fill_caches()

    assert source.fetch_calls == [
        "https://example.com/b0",
        tail_url,
    ]
    assert {m.id for m in laptop.files()} == {a0, a1, b0}
