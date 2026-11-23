"""Queue onto sequence: place front/back + fillup (ADR-0012)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.domain import (
    Mix,
    Platform,
    Sequence,
    SequenceEntry,
    StarBucket,
    Stars,
)
from tunebag.player import NullPlayer
from tunebag.sequence import place_in_sequence
from tunebag.source import FakeSource
from tunebag.web import create_app


def _mix(
    *,
    title: str,
    duration_seconds: int,
    platform_id: str | None = None,
    tags: list[str] | None = None,
) -> Mix:
    return Mix(
        artist_id=uuid4(),
        platform=Platform.SOUNDCLOUD,
        platform_id=platform_id or title.lower().replace(" ", "-"),
        title=title,
        url=f"https://example.com/{title}",
        duration_seconds=duration_seconds,
        tags=tags if tags is not None else ["set"],
        stars=Stars.FIVE,
    )


def test_place_in_sequence_front_and_back() -> None:
    a = _mix(title="A", duration_seconds=3600)
    b = _mix(title="B", duration_seconds=3600)
    c = _mix(title="C", duration_seconds=3600)
    current = Sequence(
        intent_id=uuid4(),
        entries=[
            SequenceEntry(mix_id=a.id, position=0, bucket=StarBucket.FIVE),
            SequenceEntry(mix_id=b.id, position=1, bucket=StarBucket.FIVE),
        ],
    )
    front = place_in_sequence(current, c, at="front")
    assert [e.mix_id for e in front.entries] == [c.id, a.id, b.id]
    assert [e.position for e in front.entries] == [0, 1, 2]

    back = place_in_sequence(current, c, at="back")
    assert [e.mix_id for e in back.entries] == [a.id, b.id, c.id]


def test_place_in_sequence_moves_existing() -> None:
    a = _mix(title="A", duration_seconds=3600)
    b = _mix(title="B", duration_seconds=3600)
    c = _mix(title="C", duration_seconds=3600)
    current = Sequence(
        intent_id=uuid4(),
        entries=[
            SequenceEntry(mix_id=a.id, position=0, bucket=StarBucket.FIVE),
            SequenceEntry(mix_id=b.id, position=1, bucket=StarBucket.FIVE),
            SequenceEntry(mix_id=c.id, position=2, bucket=StarBucket.FIVE),
        ],
    )
    to_front = place_in_sequence(current, c, at="front")
    assert [e.mix_id for e in to_front.entries] == [c.id, a.id, b.id]
    to_back = place_in_sequence(current, a, at="back")
    assert [e.mix_id for e in to_back.entries] == [b.id, c.id, a.id]


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
    tags: list[str] | None = None,
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
    if tags:
        agent.tag_mix(mix.id, tags)
    return mix.id


def _force_sequence(
    agent: DeviceAgent, intent_id: UUID, mix_ids: list[UUID]
) -> None:
    crafted = Sequence(
        intent_id=intent_id,
        entries=[
            SequenceEntry(mix_id=mid, position=i, bucket=StarBucket.FIVE)
            for i, mid in enumerate(mix_ids)
        ],
    )
    with agent._journal.hold():  # noqa: SLF001
        for draft in agent._sequence_provisioner.provision_fillup(  # noqa: SLF001
            agent.catalog.intents[intent_id],
            agent.catalog,
            current=crafted,
        ):
            agent._append_and_apply(draft.type, draft.payload)  # noqa: SLF001


def test_queue_on_sequence_front_and_back(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    a = _add_mix(
        agent, source, title="Long", platform_id="long", duration_seconds=3 * 3600
    )
    b = _add_mix(
        agent, source, title="Mid", platform_id="mid", duration_seconds=3600
    )
    c = _add_mix(
        agent, source, title="New", platform_id="new", duration_seconds=3600
    )
    intent = agent.create_intent(
        "Queue",
        tags=[],
        seed=1,
        device_hours=[(agent.device_id, 3 * 3600)],
    )
    _force_sequence(agent, intent.id, [a, b])

    agent.queue_on_sequence(intent.id, c, "front")
    front_ids = [e.mix_id for e in agent.sequence(intent.id).entries]
    assert front_ids[0] == c
    assert a in front_ids and b in front_ids

    agent.queue_on_sequence(intent.id, c, "back")
    back_ids = [e.mix_id for e in agent.sequence(intent.id).entries]
    assert back_ids[-1] == c or (
        # fillup may append more after c when under budget; c still last placed
        c in back_ids and back_ids.index(c) >= len(back_ids) - 2
    )
    # After move to back among the forced survivors, c is after a and b.
    survivors = [mid for mid in back_ids if mid in {a, b, c}]
    assert survivors.index(c) == len(survivors) - 1


def test_queue_on_sequence_moves_when_already_present(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    a = _add_mix(
        agent, source, title="A", platform_id="qa", duration_seconds=3 * 3600
    )
    b = _add_mix(
        agent, source, title="B", platform_id="qb", duration_seconds=3600
    )
    c = _add_mix(
        agent, source, title="C", platform_id="qc", duration_seconds=3600
    )
    intent = agent.create_intent(
        "Move",
        tags=[],
        seed=1,
        device_hours=[(agent.device_id, 3 * 3600)],
    )
    _force_sequence(agent, intent.id, [a, b, c])
    agent.queue_on_sequence(intent.id, c, "front")
    ids = [e.mix_id for e in agent.sequence(intent.id).entries]
    assert ids[0] == c
    assert ids.count(c) == 1


def test_queue_on_sequence_refuses_live_current(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    ids = [
        _add_mix(
            agent,
            source,
            title=f"Set {i}",
            platform_id=f"qset-{i}",
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
    agent.play(intent.id, current)

    with pytest.raises(ValueError, match="currently playing"):
        agent.queue_on_sequence(intent.id, current, "front")


def test_queue_on_sequence_refuses_non_matching(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    tagged = _add_mix(
        agent,
        source,
        title="Tagged",
        platform_id="tagged",
        duration_seconds=3600,
        tags=["house"],
    )
    other = _add_mix(
        agent,
        source,
        title="Other",
        platform_id="other",
        duration_seconds=3600,
        tags=["techno"],
    )
    intent = agent.create_intent(
        "House only",
        tags=["house"],
        seed=1,
        device_hours=[(agent.device_id, 3600)],
    )
    with pytest.raises(ValueError, match="does not match"):
        agent.queue_on_sequence(intent.id, other, "front")
    agent.queue_on_sequence(intent.id, tagged, "front")
    assert agent.sequence(intent.id).entries[0].mix_id == tagged


def test_queue_on_sequence_refuses_rejected(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    mix_id = _add_mix(
        agent, source, title="Nope", platform_id="nope", duration_seconds=3600
    )
    intent = agent.create_intent(
        "Any",
        tags=[],
        seed=1,
        device_hours=[(agent.device_id, 3600)],
    )
    agent.reject_mix(mix_id)
    with pytest.raises(ValueError, match="rejected"):
        agent.queue_on_sequence(intent.id, mix_id, "back")


def test_matching_intents(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    house = _add_mix(
        agent,
        source,
        title="House set",
        platform_id="house-set",
        duration_seconds=3600,
        tags=["house"],
    )
    techno = _add_mix(
        agent,
        source,
        title="Techno set",
        platform_id="techno-set",
        duration_seconds=3600,
        tags=["techno"],
    )
    house_intent = agent.create_intent(
        "House",
        tags=["house"],
        seed=1,
        device_hours=[(agent.device_id, 3600)],
    )
    open_intent = agent.create_intent(
        "Open",
        tags=[],
        seed=2,
        device_hours=[(agent.device_id, 3600)],
    )
    agent.create_intent(
        "Techno",
        tags=["techno"],
        seed=3,
        device_hours=[(agent.device_id, 3600)],
    )

    matched = {i.id for i in agent.matching_intents(house)}
    assert house_intent.id in matched
    assert open_intent.id in matched
    assert len(matched) == 2

    agent.reject_mix(techno)
    assert agent.matching_intents(techno) == []


def test_queue_and_matching_intents_http(tmp_path: Path) -> None:
    agent, source = _agent(tmp_path)
    a = _add_mix(
        agent, source, title="Long", platform_id="long-h", duration_seconds=3 * 3600
    )
    b = _add_mix(
        agent, source, title="Extra", platform_id="extra-h", duration_seconds=3600
    )
    intent = agent.create_intent(
        "HttpQueue",
        tags=[],
        seed=1,
        device_hours=[(agent.device_id, 3 * 3600)],
    )
    _force_sequence(agent, intent.id, [a])

    client = TestClient(create_app(agent))
    match = client.get(f"/api/mixes/{b}/matching-intents")
    assert match.status_code == 200
    names = {row["name"] for row in match.json()["intents"]}
    assert "HttpQueue" in names

    res = client.post(
        f"/api/intents/{intent.id}/sequence/queue",
        json={"mix_id": str(b), "position": "front"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["position"] == "front"
    entry_ids = [UUID(e["mix_id"]) for e in body["entries"]]
    assert entry_ids[0] == b

    bad_pos = client.post(
        f"/api/intents/{intent.id}/sequence/queue",
        json={"mix_id": str(b), "position": "middle"},
    )
    assert bad_pos.status_code == 422

    missing = client.post(
        f"/api/intents/{uuid4()}/sequence/queue",
        json={"mix_id": str(a), "position": "back"},
    )
    assert missing.status_code == 404

    unknown_mix = client.get(f"/api/mixes/{uuid4()}/matching-intents")
    assert unknown_mix.status_code == 404


def test_queue_ui_contract_cover_overlay_and_swipe() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "tunebag" / "static"
    js = (root / "app.js").read_text()
    css = (root / "app.css").read_text()
    html = (root / "index.html").read_text()
    assert "catalog-queue-col" not in html
    assert "catalog-cover-col" in html
    assert "mountCatalogQueueControl" in js
    assert "bindCatalogQueueSwipe" in js
    assert "openCatalogQueueIntentPicker" in js
    assert "queueOnSequence" in js
    assert "fetchMatchingIntents" in js
    assert 'queue: "↪"' in js
    assert "catalog-cover-stack" in js
    assert "catalog-queue-overlay" in js
    assert "Queue at front" in js
    assert "Queue at back" in js
    assert "function mountCatalogQueueControl(" in js
    assert "function armCatalogQueueSwipe(" in js
    assert "function catalogQueueSwipeConfirmHost(" in js
    assert "const touchClient = isHoverNone();" in js
    assert "coverStack.appendChild(overlay);" in js
    assert "if (touchClient) {\n    bindCatalogQueueSwipe(row," in js
    assert "event.pointerType === \"mouse\" && event.button !== 0" in js
    assert 'className = "catalog-tags-cell"' in js
    assert "#catalog-table .catalog-cover-stack" in css
    assert "#catalog-table .catalog-queue-overlay" in css
    assert "catalog-queue-front .catalog-queue-glyph" in css
    assert "transform: scaleY(-1)" in css
    assert "catalog-queue-swipe-confirm" in css
    assert ".catalog-queue-swipe-confirm-front" in css
    assert ".catalog-queue-swipe-confirm-back" in css
    assert "right: 0.35rem" in css
    assert (
        "#catalog-table .mix-row.catalog-queue-preview-front > td"
    ) in css
    assert "#catalog-table .mix-row {\n  touch-action: pan-y;\n}" in css
    assert (
        "#catalog-table .mix-row.catalog-queue-swiping {\n"
        "  user-select: none;\n"
        "  touch-action: none;"
    ) in css
    assert "catalog-queue-col" not in css
    assert "#catalog-table .catalog-cover-stack:hover .catalog-queue-overlay" in css
    overlay_css = css.split("#catalog-table .catalog-queue-overlay {")[1][:400]
    assert "pointer-events: none" in overlay_css
    assert "pointer-events: auto" in css.split(
        "#catalog-table .catalog-cover-stack:hover .catalog-queue-overlay"
    )[1][:200]
