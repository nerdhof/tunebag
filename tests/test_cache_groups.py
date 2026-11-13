"""Cache UI groups: cached / loading / pending aggregates by intent."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from mixy.agent import DeviceAgent
from mixy.domain import Platform, Stars
from mixy.source import FakeSource


def _agent(tmp_path: Path, source: FakeSource | None = None) -> tuple[DeviceAgent, FakeSource]:
    src = source or FakeSource()
    agent = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=tmp_path / "laptop",
    )
    return agent, src


def _add_mix(
    agent: DeviceAgent,
    source: FakeSource,
    *,
    title: str,
    duration_seconds: int,
    platform_id: str,
    stars: Stars | None = Stars.FIVE,
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
    if stars is not None:
        agent.rate_mix(mix.id, stars)
    return mix.id


def test_cache_groups_partial_fill_cached_vs_pending(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    durations = {
        _add_mix(agent, source, title="A", duration_seconds=3600, platform_id="a"): 3600,
        _add_mix(agent, source, title="B", duration_seconds=1800, platform_id="b"): 1800,
        _add_mix(agent, source, title="C", duration_seconds=900, platform_id="c"): 900,
    }
    intent = agent.create_intent(
        "Night",
        seed=1,
        device_hours=[(agent.device_id, 7200)],
    )
    assignment = agent.assignment(intent.id)
    assert assignment is not None
    assert set(assignment.mix_ids) == set(durations)
    assert len(assignment.mix_ids) == 3

    cached_ids = assignment.mix_ids[:2]
    pending_id = assignment.mix_ids[2]
    for mix_id in cached_ids:
        agent._store_local_file(mix_id, f"audio:{mix_id}".encode())

    groups = agent.cache_groups()
    assert len(groups) == 1
    group = groups[0]
    assert group["name"] == "Night"
    assert group["id"] == intent.id
    assert [m["id"] for m in group["mixes"]] == list(assignment.mix_ids)
    assert [m["status"] for m in group["mixes"]] == ["cached", "cached", "pending"]
    assert group["overview"] == {
        "cached": {
            "count": 2,
            "duration_seconds": sum(durations[i] for i in cached_ids),
        },
        "loading": {"count": 0, "duration_seconds": 0},
        "pending": {"count": 1, "duration_seconds": durations[pending_id]},
    }


def test_cache_groups_marks_active_download_as_loading(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    a = _add_mix(agent, source, title="A", duration_seconds=3600, platform_id="a")
    b = _add_mix(agent, source, title="B", duration_seconds=2589, platform_id="b")
    intent = agent.create_intent(
        "Commute",
        seed=1,
        device_hours=[(agent.device_id, 7200)],
    )
    assignment = agent.assignment(intent.id)
    assert assignment is not None
    assert a in assignment.mix_ids and b in assignment.mix_ids

    agent._store_local_file(a, b"audio:a")
    with agent._download_lock:
        agent._downloading_mix_id = b
        agent._download_bytes = 1_500_000
        agent._download_total_bytes = 4_000_000

    groups = agent.cache_groups()
    group = groups[0]
    by_id = {m["id"]: m for m in group["mixes"]}
    assert by_id[a]["status"] == "cached"
    assert by_id[b]["status"] == "loading"
    assert by_id[b]["downloaded_bytes"] == 1_500_000
    assert by_id[b]["total_bytes"] == 4_000_000
    assert "downloaded_bytes" not in by_id[a]
    assert group["overview"]["cached"] == {"count": 1, "duration_seconds": 3600}
    assert group["overview"]["loading"] == {"count": 1, "duration_seconds": 2589}
    assert group["overview"]["pending"]["count"] == len(assignment.mix_ids) - 2


def test_download_progress_property_and_clear(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    mix_id = _add_mix(agent, source, title="A", duration_seconds=600, platform_id="a")

    def action() -> None:
        progress = agent.download_progress
        assert progress is not None
        assert progress["mix_id"] == mix_id
        assert progress["downloaded_bytes"] == 0
        assert progress["total_bytes"] is None
        agent._on_download_progress(512, 1024)
        mid = agent.download_progress
        assert mid is not None
        assert mid["downloaded_bytes"] == 512
        assert mid["total_bytes"] == 1024

    agent._with_download(mix_id, action)
    assert agent.download_progress is None
    assert agent.downloading_mix_id is None


def test_cache_groups_other_for_unassigned_local_files(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    assigned = _add_mix(agent, source, title="Assigned", duration_seconds=1200, platform_id="x")
    agent.tag_mix(assigned, ["keep"])
    intent = agent.create_intent(
        "Only X",
        tags=["keep"],
        seed=1,
        device_hours=[(agent.device_id, 1200)],
    )
    assignment = agent.assignment(intent.id)
    assert assignment is not None
    assert assignment.mix_ids == [assigned]

    orphan = _add_mix(agent, source, title="Orphan", duration_seconds=600, platform_id="o")
    agent._store_local_file(orphan, b"audio:o")
    agent._store_local_file(assigned, b"audio:x")

    groups = agent.cache_groups()
    assert [g["name"] for g in groups] == ["Only X", "Other"]
    other = groups[1]
    assert other["id"] is None
    assert [m["id"] for m in other["mixes"]] == [orphan]
    assert other["overview"]["cached"] == {"count": 1, "duration_seconds": 600}
