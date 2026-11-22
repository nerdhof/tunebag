"""Playlog API: global Last-heard past, assignment upcoming, HTTP."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from tunebag.agent import PLAYLOG_PAST_LIMIT, PLAYLOG_UPCOMING_LIMIT, DeviceAgent
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


def _seed_completed(agent: DeviceAgent, mix_id: UUID, when: datetime) -> None:
    """Mark a Release completed for Playlog past (Played + Last heard)."""
    mix = agent.catalog.mixes[mix_id]
    agent.catalog.add_mix(
        mix.model_copy(update={"last_heard_at": when, "played": True})
    )


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


def test_playlog_keeps_live_current_after_mark_played_leaves_assignment(
    tmp_path: Path,
) -> None:
    """mark_played may drop the Release from assignment; Playlog keeps it at 0."""
    agent, source, _clk = _agent(tmp_path)
    # Short budget so only two of four assigned; played head can leave the window.
    ids: list[UUID] = []
    for i in range(4):
        ids.append(
            _add_mix(
                agent,
                source,
                title=f"Pool {i}",
                platform_id=f"pool-{i}",
                duration_seconds=1000,
            )
        )
    intent = agent.create_intent(
        "Live current",
        seed=1,
        device_hours=[(agent.device_id, 2000)],
    )
    intent_id = intent.id
    agent.fill_caches()
    assignment = agent.assignment(intent_id)
    assert assignment is not None
    assert len(assignment.mix_ids) == 2
    head = assignment.mix_ids[0]
    agent.play(intent_id, head)
    assert agent.is_playing()
    # mark_played rebuilds sequences; skip prune races in this unit test.
    agent._prune_unassigned_files = lambda: None  # type: ignore[method-assign]
    agent.mark_played(head)

    assignment_after = agent.assignment(intent_id)
    assert assignment_after is not None
    assert head not in assignment_after.mix_ids
    assert agent.current_mix() == head
    assert agent.is_playing()

    snap = agent.playlog(intent_id)
    by_id = {row["id"]: row for row in snap["items"]}
    assert by_id[head]["offset"] == 0
    assert snap["anchor_mix_id"] == head
    assert snap["playing"] is True
    assert head not in {
        row["id"] for row in snap["items"] if int(row["offset"]) < 0
    }


def test_playlog_past_local_file_is_playable(tmp_path: Path) -> None:
    """Cached Last-heard past rows expose playable so ◀ can revise them."""
    clock = FakeClock()
    agent, source, _clk = _agent(tmp_path, clock=clock)
    intent_id, queue_ids = _intent_with_mixes(agent, source, 2)
    agent.fill_caches()
    heard = _add_mix(
        agent, source, title="Heard past", platform_id="heard-past", duration_seconds=100
    )
    # Keep File without putting it on the playing Intent assignment.
    agent._store_local_file(heard, b"audio:heard-past")
    _seed_completed(agent, heard, clock())
    agent.play(intent_id, queue_ids[0])

    row = next(r for r in agent.playlog(intent_id)["items"] if r["id"] == heard)
    assert row["offset"] == -1
    assert row["playable"] is True
    agent.play(intent_id, heard)
    assert agent.current_mix() == heard


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

    _seed_completed(agent, other, clock())
    clock.advance(60)
    _seed_completed(agent, tail, clock())
    clock.advance(60)
    # Newest overall, but becomes current → excluded from past.
    _seed_completed(agent, head, clock())

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
        _seed_completed(agent, mix.id, clock())
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


def test_playlog_upcoming_limit_caps_assignment_window(tmp_path: Path) -> None:
    """Upcoming stops at ``upcoming_limit``; truncated flag when more remain."""
    agent, source, _clk = _agent(tmp_path)
    count = PLAYLOG_UPCOMING_LIMIT + 5
    intent_id, _ids = _intent_with_mixes(
        agent, source, count, duration_seconds=60
    )
    agent.fill_caches()
    assignment = agent.assignment(intent_id)
    assert assignment is not None
    ordered = list(assignment.mix_ids)
    assert len(ordered) >= count
    agent.play(intent_id, ordered[0])

    snap = agent.playlog(
        intent_id, upcoming_limit=PLAYLOG_UPCOMING_LIMIT
    )
    assert snap["upcoming_limit"] == PLAYLOG_UPCOMING_LIMIT
    assert snap["upcoming_truncated"] is True
    upcoming = [row for row in snap["items"] if int(row["offset"]) > 0]
    assert len(upcoming) == PLAYLOG_UPCOMING_LIMIT
    by_offset = {int(row["offset"]): row["id"] for row in upcoming}
    assert by_offset[1] == ordered[1]
    assert by_offset[PLAYLOG_UPCOMING_LIMIT] == ordered[PLAYLOG_UPCOMING_LIMIT]
    shown = {row["id"] for row in snap["items"]}
    assert ordered[PLAYLOG_UPCOMING_LIMIT + 1] not in shown

    # Limit covers the full remaining queue → not truncated.
    fit = agent.playlog(intent_id, upcoming_limit=len(ordered) - 1)
    assert fit["upcoming_truncated"] is False
    assert max(int(row["offset"]) for row in fit["items"]) == len(ordered) - 1


def test_playlog_row_cache_status_and_playable_fields(tmp_path: Path) -> None:
    """Rows expose cache_status, playable, and soft_rejected for UI."""
    clock = FakeClock()
    agent, source, _clk = _agent(tmp_path, clock=clock)
    intent_id, _ids = _intent_with_mixes(agent, source, 3)
    agent.fill_caches()
    assignment = agent.assignment(intent_id)
    assert assignment is not None
    ordered = list(assignment.mix_ids)
    _seed_completed(agent, ordered[0], clock())
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
    assert body["upcoming_limit"] == PLAYLOG_UPCOMING_LIMIT
    assert body["upcoming_truncated"] is False
    assert body["playing"] is True
    assert len(body["items"]) == 2
    fields = body["items"][0]
    for key in (
        "offset",
        "id",
        "artist",
        "artist_url",
        "title",
        "url",
        "platform",
        "cache_status",
        "has_cover",
        "playable",
        "soft_rejected",
        "rejected",
        "last_heard_at",
    ):
        assert key in fields
    assert fields["platform"]
    assert fields["url"]

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
    assert "upcoming_truncated" in playlog
    assert "playlog-truncated" in playlog
