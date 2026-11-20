"""Playlog previous-File cushion: retain briefly after advance, then prune."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.player import NullPlayer
from tunebag.reject import SOFT_REJECT_SECONDS
from tunebag.source import FakeSource


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2024, 6, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _pair(
    tmp_path: Path,
    clock: FakeClock,
) -> tuple[DeviceAgent, FakeSource]:
    src = FakeSource()
    agent = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=tmp_path / "laptop",
        player=NullPlayer(),
        clock=clock,
    )
    return agent, src


def _two_mix_intent(agent: DeviceAgent, source: FakeSource) -> tuple[object, object, object]:
    ids = []
    for title, pid in (("Alpha", "alpha"), ("Beta", "beta")):
        url = f"https://example.com/{pid}"
        source.bytes_by_url[url] = f"audio:{pid}".encode()
        mix = agent.add_mix(
            title=title,
            url=url,
            duration_seconds=3600,
            platform=Platform.SOUNDCLOUD,
            platform_id=pid,
            artist_name="DJ Example",
        )
        agent.rate_mix(mix.id, Stars.FIVE)
        ids.append(mix.id)
    intent = agent.create_intent(
        "Retain",
        seed=1,
        device_hours=[(agent.device_id, 7200)],
    )
    return intent


def test_previous_file_retained_during_cushion_after_skip(tmp_path: Path) -> None:
    """delete_retired must not drop the previous blob while the cushion is active."""
    clock = FakeClock()
    agent, source = _pair(tmp_path, clock)
    intent = _two_mix_intent(agent, source)
    agent.fill_caches()
    assignment = agent.assignment(intent.id)
    assert assignment is not None
    head, tail = assignment.mix_ids[0], assignment.mix_ids[1]
    assert head in {m.id for m in agent.files()}
    agent.play(intent.id, head)
    agent.skip()
    assert agent.current_mix() == tail

    agent._delete_retired_file_if_replaced(head)
    assert head in {m.id for m in agent.files()}
    assert agent._is_playlog_previous_retained(head)

    clock.advance(SOFT_REJECT_SECONDS + 1)
    assert not agent._is_playlog_previous_retained(head)
    agent.commit_pending_skips()
    assert head not in {m.id for m in agent.files()}


def test_playlog_retained_previous_flag_follows_cushion(tmp_path: Path) -> None:
    """Playlog rows expose retained_previous only while the cushion is active."""
    clock = FakeClock()
    agent, source = _pair(tmp_path, clock)
    intent = _two_mix_intent(agent, source)
    agent.fill_caches()
    assignment = agent.assignment(intent.id)
    assert assignment is not None
    head = assignment.mix_ids[0]
    agent.play(intent.id, head)
    agent.skip()

    row = next(r for r in agent.playlog(intent.id)["items"] if r["id"] == head)
    assert row["retained_previous"] is True
    assert row["offset"] == -1

    clock.advance(SOFT_REJECT_SECONDS + 1)
    assert not agent._is_playlog_previous_retained(head)
    # Without Last heard, cushion expiry drops the synthetic past row.
    past_ids = {
        r["id"]
        for r in agent.playlog(intent.id)["items"]
        if int(r["offset"]) < 0
    }
    assert head not in past_ids