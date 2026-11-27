"""Issue 02 (play-history): Un-reject LWW + Catalog reject UX via DeviceAgent / HTTP."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.reject import SOFT_REJECT_SECONDS
from tunebag.source import FakeSource
from tunebag.web import create_app


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
    platform_id: str,
    duration_seconds: int = 3600,
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


def test_unreject_clears_reject_and_mix_reenters_sequence(tmp_path: Path) -> None:
    laptop, _phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Come back",
        platform_id="come-back",
        tags=["techno"],
        stars=Stars.FIVE,
    )

    laptop.reject_mix(mix_id)
    assert laptop.catalog.mixes[mix_id].rejected is True

    laptop.un_reject_mix(mix_id)
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


def test_newer_unreject_beats_older_reject_across_peers(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(laptop, source, title="Race", platform_id="race", stars=Stars.FIVE)
    laptop.sync()
    phone.sync()
    laptop.disconnect(phone)

    clock.advance(1)
    laptop.reject_mix(mix_id)

    clock.advance(30)
    # Phone rejects too (so it can later un-reject after meeting), then both meet;
    # phone's later Un-reject must win over laptop's older Reject.
    phone.reject_mix(mix_id)
    clock.advance(1)
    phone.un_reject_mix(mix_id)

    laptop.connect(phone)
    laptop.sync()
    phone.sync()

    assert laptop.catalog.mixes[mix_id].rejected is False
    assert phone.catalog.mixes[mix_id].rejected is False


def test_newer_reject_beats_older_unreject_across_peers(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(laptop, source, title="Race2", platform_id="race2", stars=Stars.FIVE)
    laptop.sync()
    phone.sync()
    laptop.disconnect(phone)

    clock.advance(1)
    laptop.reject_mix(mix_id)
    clock.advance(1)
    laptop.un_reject_mix(mix_id)

    clock.advance(30)
    phone.reject_mix(mix_id)

    laptop.connect(phone)
    laptop.sync()
    phone.sync()

    assert laptop.catalog.mixes[mix_id].rejected is True
    assert phone.catalog.mixes[mix_id].rejected is True


def test_unreject_does_not_restore_file_bytes(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="No refill",
        platform_id="no-refill",
        stars=Stars.FIVE,
        audio=b"bytes-on-disk",
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

    laptop.reject_mix(mix_id)
    clock.advance(SOFT_REJECT_SECONDS)
    laptop.commit_reject_file_deletes()
    phone.sync()
    phone.commit_reject_file_deletes()
    assert mix_id not in {m.id for m in laptop.files()}
    assert mix_id not in {m.id for m in phone.files()}

    laptop.un_reject_mix(mix_id)
    phone.sync()
    # Un-reject itself does not restore bytes; rebuild + request_fill may
    # re-fetch once the Release is assigned again.
    laptop.wait_for_fill()
    phone.wait_for_fill()

    laptop_assignment = laptop.assignment(
        next(i.id for i in laptop.intents() if i.name == "Plan")
    )
    assert laptop_assignment is not None
    if mix_id in laptop_assignment.mix_ids:
        assert mix_id in {m.id for m in laptop.files()}
    else:
        assert mix_id not in {m.id for m in laptop.files()}


def test_catalog_reject_commits_immediately_and_syncs(tmp_path: Path) -> None:
    """Catalog reject shares reject_mix — Event appends immediately."""
    laptop, phone, source, _clock = _pair(tmp_path)
    mix_id = _add_mix(
        laptop,
        source,
        title="Catalog reject",
        platform_id="catalog-rej",
        stars=Stars.FIVE,
    )
    laptop.create_intent(
        "Plan",
        seed=1,
        device_hours=[(phone.device_id, 3600), (laptop.device_id, 3600)],
    )
    phone.sync()
    laptop.fill_caches()

    laptop.reject_mix(mix_id)
    assert laptop.catalog.mixes[mix_id].rejected is True
    assert laptop.catalog.mixes[mix_id].rejected_at is not None
    phone.sync()
    assert phone.catalog.mixes[mix_id].rejected is True


def test_artists_api_includes_rejected_mix_count(tmp_path: Path) -> None:
    source = FakeSource()
    clock = FakeClock()
    agent = DeviceAgent(
        "laptop",
        source=source,
        data_dir=tmp_path / "laptop",
        clock=clock,
    )
    kept = _add_mix(agent, source, title="Kept", platform_id="kept", stars=Stars.FOUR)
    rejected = _add_mix(
        agent, source, title="Rejected", platform_id="rej", stars=Stars.FIVE
    )
    agent.reject_mix(rejected)
    rejected_artist_id = str(agent.catalog.mixes[rejected].artist_id)
    kept_artist_id = str(agent.catalog.mixes[kept].artist_id)

    client = TestClient(create_app(agent))
    res = client.get("/api/artists")
    assert res.status_code == 200
    by_id = {a["id"]: a for a in res.json()["artists"]}
    assert by_id[rejected_artist_id]["rejected_mixes"] == 1
    assert by_id[rejected_artist_id]["mixes"] == 1
    assert by_id[kept_artist_id]["rejected_mixes"] == 0
    assert by_id[kept_artist_id]["mixes"] == 1


def test_catalog_ui_contract_has_rejected_filter_and_unreject() -> None:
    """Static Catalog surface exposes Rejected filter + Un-reject action hooks."""
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    html = (root / "index.html").read_text()
    js = (root / "app.js").read_text()
    assert 'id="catalog-show-rejected"' in html
    assert 'id="catalog-name-filter"' in html
    assert 'id="catalog-source-filters"' in html
    assert 'id="catalog-star-filters"' in html
    assert 'id="catalog-tag-filters"' in html
    # Catalog filter order: name → tags → sources → stars → rejected
    name_i = html.index('id="catalog-name-filter"')
    tag_i = html.index('id="catalog-tag-filters"')
    source_i = html.index('id="catalog-source-filters"')
    star_i = html.index('id="catalog-star-filters"')
    rejected_i = html.index('id="catalog-show-rejected"')
    assert name_i < tag_i < source_i < star_i < rejected_i
    assert "showRejectedCatalog" in js
    assert "syncRejectedToggle" in js
    assert "catalogFilterPlatforms" in js
    assert "catalogFilterMinStars" in js
    assert "catalogFilterTags" in js
    assert "catalogNameFilter" in js
    assert "matchesNameFilter" in js
    assert "confirmRemove: false" in js
    assert "mixMatchesCatalogFilters" in js
    assert "mountCatalogStarFloor" in js
    assert "mountCatalogFilters" in js
    assert "resetCatalogFilters" in js
    assert "filter-chip" not in html
    assert "mix-rejected" in js
    assert "/api/mixes/${mix.id}/un-reject" in js
    assert "artistGroupStats" in js
    assert "artist-stat-rating" in js
    assert "artist-stat-tagged" in js
    assert "artist-stat-reject" in js
    assert "artist-stat-played" in js
    assert "buildArtistStatEl" in js
    assert "artist-stat-pct" in js
    assert "artist-stat-pct-sign" in js
    assert "artist-stat-avg" in js
    assert "artist-fold-main" in js
    assert 'buildArtistStatEl("artist-stat-tagged", "#", stats.taggedPct)' in js
    assert 'buildArtistStatEl("artist-stat-reject", "✕", stats.rejectedPct)' in js
    assert 'buildArtistStatEl("artist-stat-played", "▶", stats.playedPct)' in js
    assert "artist-stat-rating" in js
    assert '"0.0"' in js
    assert "is-empty" in js
    assert "avgSuffix" in js


def test_intent_list_ui_contract_has_tag_artist_platform_filters() -> None:
    """Intents toolbar filters the list by tags, artists, and platforms."""
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    html = (root / "index.html").read_text()
    js = (root / "app.js").read_text()
    assert 'id="intent-name-filter"' in html
    assert 'id="intent-tag-filters"' in html
    assert 'id="intent-artist-filters"' in html
    assert 'id="intent-source-filters"' in html
    name_i = html.index('id="intent-name-filter"')
    tag_i = html.index('id="intent-tag-filters"')
    artist_i = html.index('id="intent-artist-filters"')
    source_i = html.index('id="intent-source-filters"')
    assert name_i < tag_i < artist_i < source_i
    assert "intentNameFilter" in js
    assert "intentListFilterTags" in js
    assert "intentListFilterArtistIds" in js
    assert "intentListFilterPlatforms" in js
    assert "intentMatchesListFilters" in js
    assert "mountIntentListFilters" in js
    assert "resetIntentListFilters" in js
    assert "No intents match filters" in js
    # Must not shadow helper intentFilterPlatforms()
    assert "function intentFilterPlatforms(" in js
    assert js.count("let intentFilterPlatforms") == 0


def test_name_filter_ui_contract_on_intents_catalog_cache() -> None:
    """Name filter inputs sit in Intents/Catalog/Cache toolbars and wire match helpers."""
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    html = (root / "index.html").read_text()
    js = (root / "app.js").read_text()
    css = (root / "app.css").read_text()
    assert 'id="intent-name-filter"' in html
    assert 'id="catalog-name-filter"' in html
    assert 'id="cache-name-filter"' in html
    assert "name-filter-input" in html
    assert ".name-filter-input" in css
    assert "name-filter-clear" in html
    assert "button.name-filter-clear" in css
    assert "function matchesNameFilter(" in js
    assert "function mountNameFilterInput(" in js
    assert "function syncNameFilterClear(" in js
    assert "catalogNameFilter" in js
    assert "intentNameFilter" in js
    assert "cacheNameFilter" in js
    assert "mountCacheNameFilter" in js
    assert "resetCacheNameFilter" in js
    assert "mountCacheFilters" in js
    assert "resetCacheFilters" in js
    assert "fileMatchesCacheFilters" in js
    assert "cacheFilterStatuses" in js
    assert "cacheFilterPlatforms" in js
    assert "NAME_FILTER_DEBOUNCE_MS" in js
    assert "matchesNameFilter(cacheNameFilter, file.title, file.artist)" in js
    assert "fileMatchesCacheFilters(file)" in js
    assert "No cache rows match this filter" in js
    assert 'id="cache-status-filters"' in html
    assert 'id="cache-source-filters"' in html
    assert ".cache-status-filters" in css
    # Cache name → status → platform → metered in the Filters row
    cache_pane = html[html.index('id="cache"') : html.index('id="peers"')]
    assert cache_pane.index('id="cache-name-filter"') < cache_pane.index(
        'id="cache-status-filters"'
    )
    assert cache_pane.index('id="cache-status-filters"') < cache_pane.index(
        'id="cache-source-filters"'
    )
    assert cache_pane.index('id="cache-source-filters"') < cache_pane.index(
        'id="metered-toggle"'
    )


def test_unreject_api_clears_committed_reject(tmp_path: Path) -> None:
    source = FakeSource()
    clock = FakeClock()
    agent = DeviceAgent(
        "laptop",
        source=source,
        data_dir=tmp_path / "laptop",
        clock=clock,
    )
    mix_id = _add_mix(agent, source, title="API", platform_id="api", stars=Stars.FIVE)
    agent.reject_mix(mix_id)
    client = TestClient(create_app(agent))

    res = client.post(f"/api/mixes/{mix_id}/un-reject")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["mix"]["rejected"] is False
    assert agent.catalog.mixes[mix_id].rejected is False
