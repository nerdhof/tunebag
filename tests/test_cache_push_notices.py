"""Cache view notices: assignment reshape + download progress push."""

from __future__ import annotations

from pathlib import Path

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.player import NullPlayer
from tunebag.source import FakeSource
from tunebag.ui_notices import UIViewSection


def _agent(tmp_path: Path, *, name: str = "laptop") -> tuple[DeviceAgent, FakeSource]:
    source = FakeSource()
    agent = DeviceAgent(
        name,
        source=source,
        data_dir=tmp_path / name,
        player=NullPlayer(),
    )
    return agent, source


def _sections(agent: DeviceAgent) -> list[UIViewSection]:
    return [n.section for n in agent.drain_view_notices()]


def _add_mix(agent: DeviceAgent, source: FakeSource, *, platform_id: str = "c1"):
    url = f"https://example.com/{platform_id}"
    source.bytes_by_url[url] = f"audio:{platform_id}".encode()
    mix = agent.add_mix(
        title=f"Mix {platform_id}",
        url=url,
        duration_seconds=600,
        platform=Platform.SOUNDCLOUD,
        platform_id=platform_id,
        artist_name="DJ Example",
    )
    agent.rate_mix(mix.id, Stars.FIVE)
    return mix


def test_create_intent_emits_cache_with_intents(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    _add_mix(agent, source)
    agent.drain_view_notices()

    agent.create_intent(
        "Deep",
        seed=1,
        device_hours=[(agent.device_id, 3600)],
    )

    sections = set(_sections(agent))
    assert UIViewSection.INTENTS in sections
    assert UIViewSection.CACHE in sections


def test_assignment_set_marks_cache(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    mix = _add_mix(agent, source)
    intent = agent.create_intent("Deep", seed=1)
    agent.wait_for_fill()
    agent.drain_view_notices()

    agent.set_device_hours(intent.id, agent.device_id, 3600)

    sections = set(_sections(agent))
    assert UIViewSection.INTENTS in sections
    assert UIViewSection.CACHE in sections
    assert mix.id in agent.catalog.mixes


def test_download_wrap_and_progress_mark_cache(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    mix = _add_mix(agent, source)
    agent.drain_view_notices()

    seen: list[UIViewSection] = []

    def action() -> None:
        # Start already marked CACHE+PLAYLOG; drain before progress.
        start_sections = set(_sections(agent))
        assert UIViewSection.CACHE in start_sections
        assert UIViewSection.PLAYLOG in start_sections
        seen.extend(start_sections)
        agent._on_download_progress(mix.id, 512, 1024)
        progress_sections = _sections(agent)
        seen.extend(progress_sections)
        assert UIViewSection.CACHE in progress_sections
        assert UIViewSection.PLAYLOG not in progress_sections

    agent._with_download(mix.id, action)
    end_sections = set(_sections(agent))
    seen.extend(end_sections)

    assert seen.count(UIViewSection.CACHE) >= 3
    # Start/end remount Playlog; throttled progress stays CACHE-only.
    assert UIViewSection.PLAYLOG in end_sections
    assert seen.count(UIViewSection.PLAYLOG) == 2
    assert agent.download_progress is None


def test_companion_cache_refresh_coalesces_latest_wins() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    js = (root / "app.js").read_text()
    html = (root / "index.html").read_text()

    assert "filesRefreshEpoch" in js
    assert "async function refreshFilesNow" in js
    assert "async function refreshFiles" in js
    assert "function patchPlaylogCacheFromFiles" in js
    assert "patchPlaylogCacheFromFiles(data)" in js
    assert "/static/app.js?v=75" in html

    # Activity must not drive Cache; Cache notices do.
    start = js.index("async function refreshActivity")
    rest = js[start:]
    end = rest.find("\nasync function ")
    body = rest[: end if end != -1 else len(rest)]
    assert "refreshFiles" not in body

    # CACHE-only notices must not full-refetch Playlog.
    affected = js[js.index("async function refreshAffectedSurfaces") :]
    affected = affected[: affected.find("\nasync function ")]
    cache_branch = affected[affected.index('if (wanted.has("cache"))') :]
    cache_branch = cache_branch[: cache_branch.find("\n  if (wanted.has(")]
    assert "refreshFiles" in cache_branch
    assert "refreshPlaylog" not in cache_branch
