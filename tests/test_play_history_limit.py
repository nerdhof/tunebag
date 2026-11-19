"""Play history API: cap at 50 newest Last heard; Rejected filter before limit."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from tunebag.agent import PLAY_HISTORY_LIMIT, DeviceAgent
from tunebag.domain import Platform
from tunebag.events import EventType
from tunebag.reject import SOFT_REJECT_SECONDS
from tunebag.source import FakeSource
from tunebag.web import create_app


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 6, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _agent(tmp_path: Path, *, clock: FakeClock | None = None) -> tuple[DeviceAgent, FakeSource, FakeClock]:
    src = FakeSource()
    clk = clock or FakeClock()
    agent = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=tmp_path / "laptop",
        clock=clk,
    )
    return agent, src, clk


def _add_mix(
    agent: DeviceAgent,
    source: FakeSource,
    *,
    title: str,
    platform_id: str,
) -> UUID:
    url = f"https://example.com/{platform_id}"
    source.bytes_by_url[url] = f"audio:{platform_id}".encode()
    mix = agent.add_mix(
        title=title,
        url=url,
        duration_seconds=1000,
        platform=Platform.SOUNDCLOUD,
        platform_id=platform_id,
        artist_name="DJ Example",
    )
    return mix.id


def _hear(agent: DeviceAgent, mix_id: UUID) -> None:
    agent._append_and_apply(EventType.LAST_HEARD, {"mix_id": str(mix_id)})


def test_play_history_api_returns_at_most_50_newest(tmp_path: Path) -> None:
    """GET /api/play-history caps at PLAY_HISTORY_LIMIT, newest Last heard first."""
    agent, source, clock = _agent(tmp_path)
    ids: list[UUID] = []
    for i in range(PLAY_HISTORY_LIMIT + 5):
        mix_id = _add_mix(
            agent,
            source,
            title=f"Set {i}",
            platform_id=f"set-{i}",
        )
        clock.advance(1)
        _hear(agent, mix_id)
        ids.append(mix_id)

    client = TestClient(create_app(agent))
    res = client.get("/api/play-history")
    assert res.status_code == 200
    body = res.json()
    assert body["limit"] == PLAY_HISTORY_LIMIT
    rows = body["mixes"]
    assert len(rows) == PLAY_HISTORY_LIMIT
    # Newest first: last five heard ids are the newest; first returned is last heard.
    assert rows[0]["id"] == str(ids[-1])
    assert rows[-1]["id"] == str(ids[-(PLAY_HISTORY_LIMIT)])
    returned = {row["id"] for row in rows}
    for old_id in ids[:5]:
        assert str(old_id) not in returned


def test_play_history_api_excludes_hard_rejected_by_default(tmp_path: Path) -> None:
    """Hard Rejected are omitted unless include_rejected=true; Soft stay visible."""
    agent, source, clock = _agent(tmp_path)
    soft_id = _add_mix(agent, source, title="Soft", platform_id="soft")
    hard_id = _add_mix(agent, source, title="Hard", platform_id="hard")
    keep_id = _add_mix(agent, source, title="Keep", platform_id="keep")

    clock.advance(1)
    _hear(agent, hard_id)
    clock.advance(1)
    _hear(agent, soft_id)
    clock.advance(1)
    _hear(agent, keep_id)

    agent.reject_mix(hard_id)
    clock.advance(SOFT_REJECT_SECONDS + 1)
    agent.commit_reject_file_deletes()

    agent.reject_mix(soft_id)

    client = TestClient(create_app(agent))
    default = client.get("/api/play-history").json()["mixes"]
    default_ids = [row["id"] for row in default]
    assert str(keep_id) in default_ids
    assert str(soft_id) in default_ids
    assert str(hard_id) not in default_ids
    soft_row = next(row for row in default if row["id"] == str(soft_id))
    assert soft_row["rejected"] is True

    included = client.get("/api/play-history?include_rejected=true").json()["mixes"]
    included_ids = [row["id"] for row in included]
    assert str(hard_id) in included_ids
    assert included_ids[0] == str(keep_id)


def test_play_history_api_applies_reject_filter_before_limit(tmp_path: Path) -> None:
    """Hard Rejected do not consume the 50-row budget when filter is off."""
    agent, source, clock = _agent(tmp_path)
    hard_ids: list[UUID] = []
    for i in range(10):
        mix_id = _add_mix(agent, source, title=f"Hard {i}", platform_id=f"hard-{i}")
        clock.advance(1)
        _hear(agent, mix_id)
        agent.reject_mix(mix_id)
        hard_ids.append(mix_id)
    clock.advance(SOFT_REJECT_SECONDS + 1)
    agent.commit_reject_file_deletes()

    keep_ids: list[UUID] = []
    for i in range(PLAY_HISTORY_LIMIT):
        mix_id = _add_mix(agent, source, title=f"Keep {i}", platform_id=f"keep-{i}")
        clock.advance(1)
        _hear(agent, mix_id)
        keep_ids.append(mix_id)

    client = TestClient(create_app(agent))
    rows = client.get("/api/play-history").json()["mixes"]
    assert len(rows) == PLAY_HISTORY_LIMIT
    returned = {row["id"] for row in rows}
    assert returned == {str(mid) for mid in keep_ids}
    for hid in hard_ids:
        assert str(hid) not in returned


def test_play_history_ui_fetches_capped_endpoint() -> None:
    """Static UI loads Play history from /api/play-history with Rejected toggle."""
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    js = (root / "app.js").read_text()
    assert "/api/play-history" in js
    assert "include_rejected=true" in js
    assert "showRejectedHistory" in js
    history = js[js.index("async function refreshPlayHistory") :]
    history = history[: history.index("\nasync function ")]
    assert "fetch(`/api/play-history${qs}`)" in history or 'fetch("/api/play-history' in history
    assert "/api/mixes" not in history
