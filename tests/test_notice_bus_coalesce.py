"""Issue 01 (ui-view-notices): Notice bus + coalesce on Catalog/Cache changes."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from tunebag.agent import DeviceAgent
from tunebag.discovery import FakeLanDiscovery
from tunebag.domain import Platform, Stars
from tunebag.player import NullPlayer
from tunebag.source import FakeSource
from tunebag.ui_notices import UIViewNotice, UIViewSection


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 6, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _agent(
    tmp_path: Path,
    *,
    name: str = "laptop",
    clock: FakeClock | None = None,
    discovery: FakeLanDiscovery | None = None,
    base_url: str | None = None,
) -> tuple[DeviceAgent, FakeSource]:
    source = FakeSource()
    kwargs: dict = {
        "priority": 1,
        "source": source,
        "data_dir": tmp_path / name,
        "player": NullPlayer(),
    }
    if clock is not None:
        kwargs["clock"] = clock
    if discovery is not None:
        kwargs["discovery"] = discovery
    if base_url is not None:
        kwargs["base_url"] = base_url
    agent = DeviceAgent(name, **kwargs)
    return agent, source


def _add_mix(
    agent: DeviceAgent,
    source: FakeSource,
    *,
    title: str = "Set A",
    platform_id: str = "a",
    duration_seconds: int = 3600,
) -> object:
    url = f"https://example.com/{platform_id}"
    source.bytes_by_url[url] = f"audio:{platform_id}".encode()
    return agent.add_mix(
        title=title,
        url=url,
        duration_seconds=duration_seconds,
        platform=Platform.SOUNDCLOUD,
        platform_id=platform_id,
        artist_name="DJ Example",
    )


def _sections(agent: DeviceAgent) -> list[UIViewSection]:
    return [n.section for n in agent.drain_view_notices()]


def _catalog_sections(agent: DeviceAgent) -> list[UIViewSection]:
    """Catalog/cache sections only (auto-sync notes also emit activity)."""
    return [s for s in _sections(agent) if s != UIViewSection.ACTIVITY]


def test_tag_mix_emits_coalesced_mixes_and_play_history(tmp_path: Path) -> None:
    """Tagging a Mix notifies mixes + play_history once (not per Event)."""
    agent, source = _agent(tmp_path)
    mix = _add_mix(agent, source)
    agent.drain_view_notices()

    agent.tag_mix(mix.id, ["deep"])

    assert _catalog_sections(agent) == [
        UIViewSection.MIXES,
        UIViewSection.PLAYLOG,
    ]


def test_rate_mix_emits_coalesced_mixes_and_play_history(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    mix = _add_mix(agent, source)
    agent.drain_view_notices()

    agent.rate_mix(mix.id, Stars.FIVE)

    assert _catalog_sections(agent) == [
        UIViewSection.MIXES,
        UIViewSection.PLAYLOG,
    ]


def test_add_mix_emits_single_mixes_notice(tmp_path: Path) -> None:
    """Artist + Mix Events in one add coalesce to one mixes notice."""
    agent, source = _agent(tmp_path)
    agent.drain_view_notices()

    _add_mix(agent, source)

    assert _catalog_sections(agent) == [UIViewSection.MIXES]


def test_reject_commit_emits_mixes_and_play_history(tmp_path: Path) -> None:
    clock = FakeClock()
    agent, source = _agent(tmp_path, clock=clock)
    mix = _add_mix(agent, source)
    agent.drain_view_notices()

    agent.reject_mix(mix.id)

    sections = set(_catalog_sections(agent))
    assert UIViewSection.MIXES in sections
    assert UIViewSection.PLAYLOG in sections


def test_playhead_tick_emits_no_catalog_notice(tmp_path: Path) -> None:
    """Pure PLAYHEAD ticks must not remount Catalog / Playlog."""
    agent, source = _agent(tmp_path)
    mix = _add_mix(agent, source, duration_seconds=1000)
    agent.rate_mix(mix.id, Stars.FIVE)
    intent = agent.create_intent(
        "Play",
        seed=1,
        device_hours=[(agent.device_id, 1000)],
    )
    agent.fill_caches()
    agent.play(intent.id, mix.id)
    agent._cancel_playback_threshold_watch()
    # Seed a playhead below Last heard so the next tick is PLAYHEAD-only.
    agent.report_playhead(5)
    agent.drain_view_notices()

    agent.report_playhead(6)

    assert _catalog_sections(agent) == []


def test_last_heard_rising_edge_still_notifies_mixes_and_history(
    tmp_path: Path,
) -> None:
    """Last heard (with playhead) still coalesces Catalog sections once."""
    agent, source = _agent(tmp_path)
    mix = _add_mix(agent, source, duration_seconds=1000)
    agent.rate_mix(mix.id, Stars.FIVE)
    intent = agent.create_intent(
        "Play",
        seed=1,
        device_hours=[(agent.device_id, 1000)],
    )
    agent.fill_caches()
    agent.play(intent.id, mix.id)
    agent._cancel_playback_threshold_watch()
    agent.wait_for_fill()
    agent.drain_view_notices()

    agent.report_playhead(9)
    agent.report_playhead(10)

    assert _catalog_sections(agent) == [
        UIViewSection.MIXES,
        UIViewSection.PLAYLOG,
    ]
    assert next(m for m in agent.mixes() if m.id == mix.id).last_heard_at is not None


def test_create_intent_emits_single_coalesced_intents_notice(tmp_path: Path) -> None:
    """Upsert + Sequence + Assignments collapse to one intents notice."""
    agent, source = _agent(tmp_path)
    mix = _add_mix(agent, source)
    agent.rate_mix(mix.id, Stars.FIVE)
    agent.drain_view_notices()

    agent.create_intent(
        "Deep",
        seed=1,
        device_hours=[(agent.device_id, 3600)],
    )

    # Fill may mark CACHE (download start); intents must still coalesce to one.
    sections = [s for s in _catalog_sections(agent) if s != UIViewSection.CACHE]
    assert sections == [UIViewSection.PLAYLOG, UIViewSection.INTENTS]


def test_cache_file_add_and_remove_emit_cache(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    mix = _add_mix(agent, source)
    agent.rate_mix(mix.id, Stars.FIVE)
    agent.create_intent(
        "Deep",
        seed=1,
        device_hours=[(agent.device_id, 3600)],
    )
    agent.drain_view_notices()

    agent.fill_caches()
    assert UIViewSection.CACHE in set(_sections(agent))

    agent.drain_view_notices()
    agent.remove_local_file(mix.id)
    assert _catalog_sections(agent) == [UIViewSection.CACHE]


def test_pair_and_unpair_emit_peers(tmp_path: Path) -> None:
    laptop, _ = _agent(tmp_path, name="laptop")
    phone, _ = _agent(tmp_path, name="phone")
    laptop.connect(phone)
    laptop.drain_view_notices()
    phone.drain_view_notices()

    phone.pair(laptop.pairing_payload())
    laptop.wait_for_sync()
    phone.wait_for_sync()

    assert UIViewSection.PEERS in set(_sections(phone))
    assert UIViewSection.PEERS in set(_sections(laptop))

    phone.drain_view_notices()
    peer_id = laptop.device_id
    phone.unpair(peer_id)
    sections = set(_sections(phone))
    assert UIViewSection.PEERS in sections
    assert UIViewSection.INTENTS in sections
    laptop.wait_for_sync()
    phone.wait_for_sync()


def test_pair_candidate_discovery_emits_peers(tmp_path: Path) -> None:
    discovery = FakeLanDiscovery()
    phone, _ = _agent(
        tmp_path,
        name="phone",
        discovery=discovery,
        base_url="inproc://phone",
    )
    _agent(
        tmp_path,
        name="stranger",
        discovery=discovery,
        base_url="inproc://stranger",
    )
    phone.drain_view_notices()

    phone.refresh_discovery()

    assert _catalog_sections(phone) == [UIViewSection.PEERS]
    assert len(phone.pair_candidates()) == 1


def test_two_subscribers_observe_same_coalesced_notices(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    mix = _add_mix(agent, source)
    agent.drain_view_notices()

    seen_a: list[UIViewNotice] = []
    seen_b: list[UIViewNotice] = []
    unsub_a = agent.subscribe_view_notices(seen_a.append)
    unsub_b = agent.subscribe_view_notices(seen_b.append)

    agent.tag_mix(mix.id, ["deep"])

    def catalog_only(notices: list[UIViewNotice]) -> list[UIViewSection]:
        return [n.section for n in notices if n.section != UIViewSection.ACTIVITY]

    assert catalog_only(seen_a) == [
        UIViewSection.MIXES,
        UIViewSection.PLAYLOG,
    ]
    assert catalog_only(seen_b) == [
        UIViewSection.MIXES,
        UIViewSection.PLAYLOG,
    ]
    assert seen_a == seen_b
    unsub_a()
    unsub_b()


def test_pair_during_fill_delivers_peers_notice_before_fill_ends(tmp_path: Path) -> None:
    """Long fill must not hold the view-notice batch across downloads.

    Otherwise PEERS SSE is delayed until fill ends, and Assign hours still
    thinks only the local device is known.
    """
    import threading

    fetch_started = threading.Event()
    release_fetch = threading.Event()
    peers_seen = threading.Event()
    seen_sections: list[UIViewSection] = []

    class SlowSource(FakeSource):
        def fetch_bytes(
            self,
            source_url: str,
            *,
            on_progress: object | None = None,
        ) -> bytes:
            fetch_started.set()
            assert release_fetch.wait(timeout=5.0), "fill was not released"
            return super().fetch_bytes(source_url, on_progress=on_progress)  # type: ignore[arg-type]

    source = SlowSource()
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=source,
        data_dir=tmp_path / "laptop",
        player=NullPlayer(),
    )
    tablet = DeviceAgent(
        "tablet",
        priority=20,
        data_dir=tmp_path / "tablet",
        player=NullPlayer(),
    )
    url = "https://example.com/slow"
    source.bytes_by_url[url] = b"audio-slow"
    mix = laptop.add_mix(
        title="Slow Set",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="slow",
        artist_name="DJ Slow",
    )
    laptop.rate_mix(mix.id, Stars.FIVE)
    laptop.create_intent(
        "Deep",
        seed=1,
        device_hours=[(laptop.device_id, 3600)],
    )
    laptop.drain_view_notices()

    def on_notice(notice: UIViewNotice) -> None:
        seen_sections.append(notice.section)
        if notice.section is UIViewSection.PEERS:
            peers_seen.set()

    unsubscribe = laptop.subscribe_view_notices(on_notice)
    fill_error: list[BaseException] = []

    def run_fill() -> None:
        try:
            laptop.fill_caches()
        except BaseException as exc:  # noqa: BLE001
            fill_error.append(exc)

    filler = threading.Thread(target=run_fill, daemon=True)
    filler.start()
    assert fetch_started.wait(timeout=2.0), "fill never started downloading"

    # Pair while fill is mid-download (batch would still be open under the bug).
    laptop.pair(tablet.pairing_payload())

    assert peers_seen.wait(timeout=1.0), (
        f"PEERS notice blocked until fill ends; saw {seen_sections!r}"
    )
    assert filler.is_alive(), "fill finished before PEERS notice — test did not overlap"

    release_fetch.set()
    filler.join(timeout=5.0)
    unsubscribe()
    assert not fill_error, fill_error[0]
    assert UIViewSection.PEERS in seen_sections
