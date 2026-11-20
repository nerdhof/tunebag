"""Drop from sequence: trim + fillup (ADR-0010)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.domain import (
    DeviceHours,
    Intent,
    Mix,
    Platform,
    Sequence,
    SequenceEntry,
    StarBucket,
    Stars,
)
from tunebag.player import NullPlayer
from tunebag.sequence import fill_sequence
from tunebag.sequence_provision import SequenceProvisioner
from tunebag.source import FakeSource
from tunebag.web import create_app


def _mix(
    *,
    title: str,
    duration_seconds: int,
    platform_id: str | None = None,
) -> Mix:
    return Mix(
        artist_id=uuid4(),
        platform=Platform.SOUNDCLOUD,
        platform_id=platform_id or title.lower().replace(" ", "-"),
        title=title,
        url=f"https://example.com/{title}",
        duration_seconds=duration_seconds,
        tags=["set"],
        stars=Stars.FIVE,
    )


def test_fill_sequence_after_trim_omits_dropped_when_budget_met() -> None:
    """Survivors that already meet budget: dropped id stays out (no append)."""
    a = _mix(title="A", duration_seconds=3 * 3600)
    b = _mix(title="B", duration_seconds=3600)
    c = _mix(title="C", duration_seconds=3600)
    d = _mix(title="D", duration_seconds=3600)
    intent = Intent(
        name="Trim full",
        tags=["set"],
        seed=1,
        device_hours=[DeviceHours(device_id=uuid4(), budget_seconds=3 * 3600)],
    )
    trimmed = Sequence(
        intent_id=intent.id,
        entries=[
            SequenceEntry(mix_id=a.id, position=0, bucket=StarBucket.FIVE),
            SequenceEntry(mix_id=c.id, position=1, bucket=StarBucket.FIVE),
        ],
    )
    filled = fill_sequence(intent, [a, b, c, d], trimmed)
    ids = [e.mix_id for e in filled.entries]
    assert ids == [a.id, c.id]
    assert b.id not in ids


def test_fill_sequence_after_trim_keeps_order_and_may_reappend() -> None:
    """Under budget after trim: survivors keep order; append may redraw dropped."""
    mixes = [
        _mix(title=f"M{i}", duration_seconds=3600, platform_id=f"m{i}")
        for i in range(4)
    ]
    a, b, c, d = mixes
    intent = Intent(
        name="Trim under",
        tags=["set"],
        seed=3,
        device_hours=[DeviceHours(device_id=uuid4(), budget_seconds=3 * 3600)],
    )
    trimmed = Sequence(
        intent_id=intent.id,
        entries=[
            SequenceEntry(mix_id=a.id, position=0, bucket=StarBucket.FIVE),
            SequenceEntry(mix_id=c.id, position=1, bucket=StarBucket.FIVE),
        ],
    )
    filled = fill_sequence(intent, mixes, trimmed)
    ids = [e.mix_id for e in filled.entries]
    assert ids[:2] == [a.id, c.id]
    assert len(ids) == 3
    assert ids[2] in {b.id, d.id}


def test_provision_fillup_accepts_trimmed_current() -> None:
    from tunebag.events import EventType
    from tunebag.projection import CatalogState

    device_id = uuid4()
    a = _mix(title="Keep", duration_seconds=3 * 3600)
    b = _mix(title="Drop", duration_seconds=3600)
    c = _mix(title="Also", duration_seconds=3600)
    intent = Intent(
        name="Prov",
        tags=["set"],
        seed=2,
        device_hours=[DeviceHours(device_id=device_id, budget_seconds=3 * 3600)],
    )
    catalog = CatalogState()
    for mix in (a, b, c):
        catalog.add_mix(mix)
    catalog.upsert_intent(intent)
    catalog.set_sequence(
        Sequence(
            intent_id=intent.id,
            entries=[
                SequenceEntry(mix_id=a.id, position=0, bucket=StarBucket.FIVE),
                SequenceEntry(mix_id=b.id, position=1, bucket=StarBucket.FIVE),
                SequenceEntry(mix_id=c.id, position=2, bucket=StarBucket.FIVE),
            ],
        )
    )
    trimmed = Sequence(
        intent_id=intent.id,
        entries=[
            SequenceEntry(mix_id=a.id, position=0, bucket=StarBucket.FIVE),
            SequenceEntry(mix_id=c.id, position=1, bucket=StarBucket.FIVE),
        ],
    )
    drafts = SequenceProvisioner().provision_fillup(
        intent, catalog, current=trimmed
    )
    seq = next(d for d in drafts if d.type is EventType.SEQUENCE_BUILT)
    entry_ids = [UUID(e["mix_id"]) for e in seq.payload["entries"]]
    assert entry_ids == [a.id, c.id]
    assert b.id not in entry_ids


def _agent(tmp_path: Path) -> tuple[DeviceAgent, FakeSource]:
    source = FakeSource()
    agent = DeviceAgent(
        "laptop",
        priority=1,
        source=source,
        data_dir=tmp_path / "laptop",
        player=NullPlayer(),
    )
    return agent, source


def _add_mix(
    agent: DeviceAgent,
    source: FakeSource,
    *,
    title: str,
    platform_id: str,
    duration_seconds: int,
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


def test_drop_from_sequence_removes_when_survivors_meet_budget(
    tmp_path: Path,
) -> None:
    agent, source = _agent(tmp_path)
    a = _add_mix(
        agent, source, title="Long", platform_id="long", duration_seconds=3 * 3600
    )
    b = _add_mix(
        agent, source, title="Drop me", platform_id="drop", duration_seconds=3600
    )
    c = _add_mix(
        agent, source, title="Keep", platform_id="keep", duration_seconds=3600
    )
    intent = agent.create_intent(
        "Drop",
        tags=[],
        seed=1,
        device_hours=[(agent.device_id, 3 * 3600)],
    )
    # Force a known sequence order via fillup from a crafted current.
    crafted = Sequence(
        intent_id=intent.id,
        entries=[
            SequenceEntry(mix_id=a, position=0, bucket=StarBucket.FIVE),
            SequenceEntry(mix_id=b, position=1, bucket=StarBucket.FIVE),
            SequenceEntry(mix_id=c, position=2, bucket=StarBucket.FIVE),
        ],
    )
    with agent._journal.hold():  # noqa: SLF001
        for draft in agent._sequence_provisioner.provision_fillup(  # noqa: SLF001
            agent.catalog.intents[intent.id],
            agent.catalog,
            current=crafted,
        ):
            agent._append_and_apply(draft.type, draft.payload)  # noqa: SLF001

    before = agent.sequence(intent.id)
    assert before is not None
    assert [e.mix_id for e in before.entries] == [a, b, c]

    agent.drop_from_sequence(intent.id, b)
    after = agent.sequence(intent.id)
    assert after is not None
    ids = [e.mix_id for e in after.entries]
    assert b not in ids
    assert ids == [a, c]

    snap = agent.playlog(intent.id)
    upcoming_ids = [row["id"] for row in snap["items"] if row["offset"] > 0]
    assert b not in upcoming_ids


def test_drop_from_sequence_refuses_live_current(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    ids = [
        _add_mix(
            agent,
            source,
            title=f"Set {i}",
            platform_id=f"set-{i}",
            duration_seconds=600,
        )
        for i in range(3)
    ]
    intent = agent.create_intent(
        "Play",
        seed=1,
        device_hours=[(agent.device_id, 1800)],
    )
    agent.fill_caches()
    assignment = agent.assignment(intent.id)
    assert assignment is not None
    current = assignment.mix_ids[0]
    upcoming = assignment.mix_ids[1]
    agent.play(intent.id, current)

    with pytest.raises(ValueError, match="currently playing"):
        agent.drop_from_sequence(intent.id, current)

    # Upcoming still droppable (may re-append at a new position when under budget).
    before_ids = [e.mix_id for e in agent.sequence(intent.id).entries]
    assert upcoming in before_ids
    agent.drop_from_sequence(intent.id, upcoming)
    after = agent.sequence(intent.id)
    assert after is not None
    survivors = [mid for mid in before_ids if mid != upcoming]
    after_ids = [e.mix_id for e in after.entries]
    assert after_ids[: len(survivors)] == survivors


def test_drop_from_sequence_unknown_intent_raises(tmp_path: Path) -> None:
    agent, _source = _agent(tmp_path)
    with pytest.raises(KeyError, match="unknown intent"):
        agent.drop_from_sequence(uuid4(), uuid4())


def test_drop_from_sequence_http(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    a = _add_mix(
        agent, source, title="Long", platform_id="long-h", duration_seconds=3 * 3600
    )
    b = _add_mix(
        agent, source, title="Drop", platform_id="drop-h", duration_seconds=3600
    )
    c = _add_mix(
        agent, source, title="Keep", platform_id="keep-h", duration_seconds=3600
    )
    intent = agent.create_intent(
        "HttpDrop",
        tags=[],
        seed=1,
        device_hours=[(agent.device_id, 3 * 3600)],
    )
    crafted = Sequence(
        intent_id=intent.id,
        entries=[
            SequenceEntry(mix_id=a, position=0, bucket=StarBucket.FIVE),
            SequenceEntry(mix_id=b, position=1, bucket=StarBucket.FIVE),
            SequenceEntry(mix_id=c, position=2, bucket=StarBucket.FIVE),
        ],
    )
    with agent._journal.hold():  # noqa: SLF001
        for draft in agent._sequence_provisioner.provision_fillup(  # noqa: SLF001
            agent.catalog.intents[intent.id],
            agent.catalog,
            current=crafted,
        ):
            agent._append_and_apply(draft.type, draft.payload)  # noqa: SLF001

    client = TestClient(create_app(agent))
    res = client.post(
        f"/api/intents/{intent.id}/sequence/drop",
        json={"mix_id": str(b)},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    entry_ids = [UUID(e["mix_id"]) for e in body["entries"]]
    assert b not in entry_ids
    assert entry_ids == [a, c]

    bad = client.post(
        f"/api/intents/{intent.id}/sequence/drop",
        json={"mix_id": str(uuid4())},
    )
    assert bad.status_code == 400

    missing = client.post(
        f"/api/intents/{uuid4()}/sequence/drop",
        json={"mix_id": str(a)},
    )
    assert missing.status_code == 404
