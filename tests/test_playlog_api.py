"""Playlog API: global Last-heard past, assignment upcoming, HTTP."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from tunebag.agent import PLAYLOG_PAST_LIMIT, DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.player import NullPlayer
from tunebag.source import FakeSource
from tunebag.web import create_app


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 6, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _agent(
    tmp_path: Path, *, clock: FakeClock | None = None
) -> tuple[DeviceAgent, FakeSource, FakeClock]:
    src = FakeSource()
    clk = clock or FakeClock()
    agent = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=tmp_path / "laptop",
        player=NullPlayer(),
        clock=clk,
    )
    return agent, src, clk


def _add_mix(
    agent: DeviceAgent,
    source: FakeSource,
    *,
    title: str,
    platform_id: str,
    duration_seconds: int = 1000,
) -> UUID:
    url = f"https://example.com/{platform_id}"
    source.bytes_by_url[url] = f"audio:{platform_id}".encode()
    mix = agent.add_mix(
        title=title,
        url=url,
        duration_seconds=duration_seconds,
        platform=Platform.SOUNDCLOUD,
        platform_id=platform_id,
        artist_name="DJ Example",
    )
    agent.rate_mix(mix.id, Stars.FIVE)
    return mix.id


def _intent_with_mixes(
    agent: DeviceAgent,
    source: FakeSource,
    count: int,
    *,
    duration_seconds: int = 600,
) -> tuple[UUID, list[UUID]]:
    ids: list[UUID] = []
    for i in range(count):
        ids.append(
            _add_mix(
                agent,
                source,
                title=f"Set {i}",
                platform_id=f"set-{i}",
                duration_seconds=duration_seconds,
            )
        )
    total_seconds = count * duration_seconds
    intent = agent.create_intent(
        "Playlog",
        seed=1,
        device_hours=[(agent.device_id, total_seconds)],
    )
    return intent.id, ids


def _seed_last_heard(agent: DeviceAgent, mix_id: UUID, when: datetime) -> None:
    mix = agent.catalog.mixes[mix_id]
    agent.catalog.add_mix(mix.model_copy(update={"last_heard_at": when}))


def test_playlog_offsets_anchor_on_current_mix(tmp_path: Path) -> None:
    """Current/upcoming follow assignment; past needs Last heard."""
    agent, source, _clk = _agent(tmp_path)
    intent_id, _ids = _intent_with_mixes(agent, source, 3)
    agent.fill_caches()
    assignment = agent.assignment(intent_id)
    assert assignment is not None
    ordered = list(assignment.mix_ids)
    anchor = ordered[1]
    agent.play(intent_id, anchor)

    snap = agent.playlog(intent_id)
    offsets = {row["id"]: row["offset"] for row in snap["items"]}
    assert offsets[ordered[1]] == 0
    assert offsets[ordered[2]] == 1
    # No Last heard yet → predecessor is not global past.
    assert ordered[0] not in offsets
    assert snap["anchor_mix_id"] == anchor
    assert snap["current_mix_id"] == anchor
    assert snap["playing"] is True


def test_playlog_past_is_global_last_heard_across_intents(tmp_path: Path) -> None:
    """Past (−N) is Catalog Last heard newest-first, not Intent-local."""
    clock = FakeClock()
    agent, source, _clk = _agent(tmp_path, clock=clock)
    other = _add_mix(agent, source, title="Other intent set", platform_id="other")
    agent.create_intent(
        "Other",
        seed=2,
        device_hours=[(agent.device_id, 1000)],
    )
    intent_id, _ids = _intent_with_mixes(agent, source, 2)
    agent.fill_caches()
    assignment = agent.assignment(intent_id)
    assert assignment is not None
    head, tail = assignment.mix_ids[0], assignment.mix_ids[1]

    _seed_last_heard(agent, other, clock())
    clock.advance(60)
    _seed_last_heard(agent, tail, clock())
    clock.advance(60)
    # Newest overall, but becomes current → excluded from past.
    _seed_last_heard(agent, head, clock())

    agent.play(intent_id, head)
    snap = agent.playlog(intent_id)
    by_offset = {int(row["offset"]): row["id"] for row in snap["items"]}
    assert by_offset[0] == head
    # Tail is also upcoming (+1), so excluded from past; only ``other`` remains.
    assert by_offset[1] == tail
    assert by_offset[-1] == other
    assert -2 not in by_offset


def test_playlog_cushion_previous_appears_without_last_heard(tmp_path: Path) -> None:
    """Immediate previous stays at −1 during the File cushion even without Last heard."""
    agent, source, _clk = _agent(tmp_path)
    intent_id, _ids = _intent_with_mixes(agent, source, 2, duration_seconds=3600)
    agent.fill_caches()
    assignment = agent.assignment(intent_id)
    assert assignment is not None
    head, second = assignment.mix_ids[0], assignment.mix_ids[1]
    agent.play(intent_id, head)
    agent.skip()
    assert agent.current_mix() == second

    snap = agent.playlog(intent_id)
    by_offset = {int(row["offset"]): row["id"] for row in snap["items"]}
    assert by_offset[0] == second
    assert by_offset[-1] == head


def test_playlog_past_limit_caps_last_heard_window(tmp_path: Path) -> None:
    """Only ``past_limit`` Last-heard past rows appear (outside the queue)."""
    clock = FakeClock()
    agent, source, _clk = _agent(tmp_path, clock=clock)
    # Queue first so later Last-heard-only mixes are not assigned into upcoming.
    intent_id, queue_ids = _intent_with_mixes(agent, source, 2)
    agent.fill_caches()
    assignment = agent.assignment(intent_id)
    assert assignment is not None
    assert set(assignment.mix_ids) == set(queue_ids)

    heard_ids: list[UUID] = []
    for i in range(PLAYLOG_PAST_LIMIT + 3):
        url = f"https://example.com/heard-{i}"
        source.bytes_by_url[url] = f"audio:heard-{i}".encode()
        mix = agent.add_mix(
            title=f"Heard {i}",
            url=url,
            duration_seconds=100,
            platform=Platform.SOUNDCLOUD,
            platform_id=f"heard-{i}",
            artist_name="DJ Example",
        )
        clock.advance(10)
        _seed_last_heard(agent, mix.id, clock())
        heard_ids.append(mix.id)

    clock.advance(1)
    anchor = assignment.mix_ids[0]
    agent.play(intent_id, anchor)

    snap = agent.playlog(intent_id, past_limit=PLAYLOG_PAST_LIMIT)
    past_rows = [row for row in snap["items"] if int(row["offset"]) < 0]
    assert len(past_rows) == PLAYLOG_PAST_LIMIT
    # Sorted −N…−1: newest Last heard is offset −1; oldest in window is −N.
    by_offset = {int(row["offset"]): row["id"] for row in past_rows}
    assert by_offset[-1] == heard_ids[-1]
    assert by_offset[-PLAYLOG_PAST_LIMIT] == heard_ids[-PLAYLOG_PAST_LIMIT]
    assert heard_ids[0] not in {row["id"] for row in past_rows}
    assert queue_ids[1] not in {row["id"] for row in past_rows}


def test_playlog_row_cache_status_and_playable_fields(tmp_path: Path) -> None:
    """Rows expose cache_status, playable, and soft_rejected for UI."""
    clock = FakeClock()
    agent, source, _clk = _agent(tmp_path, clock=clock)
    intent_id, _ids = _intent_with_mixes(agent, source, 3)
    agent.fill_caches()
    assignment = agent.assignment(intent_id)
    assert assignment is not None
    ordered = list(assignment.mix_ids)
    _seed_last_heard(agent, ordered[0], clock())
    agent.play(intent_id, ordered[1])
    agent.remove_local_file(ordered[0])

    snap = agent.playlog(intent_id)
    by_id = {row["id"]: row for row in snap["items"]}
    current = by_id[ordered[1]]
    assert current["cache_status"] == "cached"
    assert current["playable"] is True
    assert current["soft_rejected"] is False
    upcoming = by_id[ordered[2]]
    assert upcoming["cache_status"] == "cached"
    past = by_id[ordered[0]]
    assert past["offset"] == -1
    assert past["cache_status"] == "absent"
    assert past["playable"] is False
    for row in snap["items"]:
        assert "cache_status" in row
        assert "playable" in row
        assert "soft_rejected" in row
        assert "last_heard_at" in row


def test_playlog_api_http_matches_agent_snapshot(tmp_path: Path) -> None:
    """GET /api/playlog returns the agent playlog JSON shape."""
    agent, source, _clk = _agent(tmp_path)
    intent_id, _ids = _intent_with_mixes(agent, source, 2)
    agent.fill_caches()
    assignment = agent.assignment(intent_id)
    assert assignment is not None
    head = assignment.mix_ids[0]
    agent.play(intent_id, head)

    client = TestClient(create_app(agent))
    res = client.get(f"/api/playlog?intent_id={intent_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["intent_id"] == str(intent_id)
    assert body["past_limit"] == PLAYLOG_PAST_LIMIT
    assert body["playing"] is True
    assert len(body["items"]) == 2
    fields = body["items"][0]
    for key in (
        "offset",
        "id",
        "artist",
        "title",
        "cache_status",
        "has_cover",
        "playable",
        "soft_rejected",
        "rejected",
        "last_heard_at",
    ):
        assert key in fields

    res_default = client.get("/api/playlog")
    assert res_default.status_code == 200
    assert res_default.json()["intent_id"] == str(intent_id)


def test_playlog_ui_fetches_playlog_endpoint() -> None:
    """Static UI loads Playlog from /api/playlog (no History rejected toggle)."""
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    js = (root / "app.js").read_text()
    html = (root / "index.html").read_text()
    assert 'id="playlog"' in html
    assert "/api/playlog" in js
    assert "refreshPlaylog" in js
    assert "showRejectedHistory" not in js
    assert "include_rejected=true" not in js
    playlog = js[js.index("async function refreshPlaylog") :]
    playlog = playlog[: playlog.index("\nasync function ", 1)]
    assert "fetch(`/api/playlog${qs}`)" in playlog or 'fetch("/api/playlog' in playlog
