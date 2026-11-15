"""Issue 01 (durable-sync): deterministic Catalog merge via DeviceAgent."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from cryptography.exceptions import InvalidSignature

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.source import FakeSource


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
    laptop.sync()
    phone.sync()
    return laptop, phone, src, clk


def _add_mix(
    agent: DeviceAgent,
    source: FakeSource,
    *,
    title: str,
    platform_id: str,
    duration_seconds: int = 3600,
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
    return mix.id


def _catalog_snapshot(agent: DeviceAgent) -> dict:
    """Comparable Catalog projection (no local-only File / Metered state)."""
    mixes = {
        str(m.id): {
            "title": m.title,
            "tags": list(m.tags),
            "stars": None if m.stars is None else int(m.stars),
            "rejected": m.rejected,
            "played": m.played,
            "artist_id": str(m.artist_id),
        }
        for m in sorted(agent.mixes(), key=lambda m: m.id)
    }
    artists = {
        str(a.id): {"name": a.name, "platform_id": a.platform_id}
        for a in sorted(agent.artists(), key=lambda a: a.id)
    }
    intents = {
        str(i.id): {
            "name": i.name,
            "tags": list(i.tags),
            "seed": i.seed,
            "device_hours": sorted(
                (str(dh.device_id), dh.budget_seconds) for dh in i.device_hours
            ),
        }
        for i in sorted(agent.intents(), key=lambda i: i.id)
    }
    sequences = {
        str(intent_id): [
            (str(e.mix_id), e.position, e.bucket.value) for e in seq.entries
        ]
        for intent_id, seq in sorted(
            agent.catalog.sequences.items(), key=lambda kv: kv[0]
        )
    }
    assignments = {
        f"{intent_id}:{device_id}": {
            "mix_ids": [str(m) for m in assignment.mix_ids],
            "budget_seconds": assignment.budget_seconds,
        }
        for (intent_id, device_id), assignment in sorted(
            agent.catalog.assignments.items(), key=lambda kv: kv[0]
        )
    }
    playheads = {
        str(mix_id): {
            "position_seconds": head.position_seconds,
            "updated_at": head.updated_at.isoformat(),
        }
        for mix_id, head in sorted(agent.catalog.playheads.items(), key=lambda kv: kv[0])
    }
    return {
        "artists": artists,
        "mixes": mixes,
        "intents": intents,
        "sequences": sequences,
        "assignments": assignments,
        "playheads": playheads,
    }


def test_offline_divergent_edits_converge_to_identical_catalog(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(laptop, source, title="Shared", platform_id="shared")
    intent = laptop.create_intent(
        "Plan",
        seed=1,
        tags=["warm"],
        device_hours=[
            (laptop.device_id, 3600),
            (phone.device_id, 3600),
        ],
    )
    laptop.fill_caches()
    laptop.sync()
    phone.sync()
    phone.fill_caches()

    laptop.disconnect(phone)

    clock.advance(1)
    laptop.rate_mix(mix_id, Stars.FIVE)
    laptop.tag_mix(mix_id, ["laptop-tag", "shared"])
    laptop.create_intent(
        "Laptop plan",
        seed=2,
        tags=["laptop"],
        device_hours=[(laptop.device_id, 1800)],
    )
    laptop.set_current_mix(mix_id)
    laptop.report_playhead(100)

    clock.advance(30)
    phone.rate_mix(mix_id, Stars.THREE)
    phone.tag_mix(mix_id, ["phone-tag"])
    phone.delete_intent(intent.id)
    source.bytes_by_url["https://example.com/phone-only"] = b"audio:phone-only"
    phone.add_mix(
        title="Phone only",
        url="https://example.com/phone-only",
        duration_seconds=1800,
        platform=Platform.SOUNDCLOUD,
        platform_id="phone-only",
        artist_name="Phone DJ",
    )
    phone.create_intent(
        "Phone listen",
        seed=9,
        device_hours=[(phone.device_id, 3600)],
    )
    phone.set_current_mix(mix_id)
    phone.report_playhead(250)

    clock.advance(1)
    laptop.reject_mix(mix_id)
    clock.advance(25)
    laptop.commit_pending_rejects()

    laptop.connect(phone)
    laptop.sync()
    phone.sync()

    assert _catalog_snapshot(laptop) == _catalog_snapshot(phone)
    shared = next(m for m in laptop.mixes() if m.id == mix_id)
    assert shared.rejected is True
    assert shared.stars is not None
    assert shared.tags
    # Intent delete vs upsert resolve by last-by-(device_id, event.id); both agree.
    assert {i.id for i in laptop.intents()} == {i.id for i in phone.intents()}
    assert laptop.playhead(mix_id) is not None
    assert laptop.playhead(mix_id).position_seconds == phone.playhead(mix_id).position_seconds


def test_ingest_order_does_not_change_converged_catalog(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(laptop, source, title="Shared", platform_id="shared-order")
    laptop.sync()
    phone.sync()
    laptop.disconnect(phone)

    clock.advance(1)
    laptop.rate_mix(mix_id, Stars.FIVE)
    laptop.tag_mix(mix_id, ["a"])
    clock.advance(1)
    phone.rate_mix(mix_id, Stars.TWO)
    phone.tag_mix(mix_id, ["b"])
    phone.mark_played(mix_id)

    peer_events = [
        e
        for e in laptop.export_events() + phone.export_events()
        if e.device_id in {laptop.device_id, phone.device_id}
    ]

    forward = DeviceAgent(
        "forward",
        priority=50,
        source=FakeSource(),
        data_dir=tmp_path / "forward",
        clock=clock,
    )
    reverse = DeviceAgent(
        "reverse",
        priority=51,
        source=FakeSource(),
        data_dir=tmp_path / "reverse",
        clock=clock,
    )
    for agent in (forward, reverse):
        agent.pair(laptop.pairing_payload())
        agent.pair(phone.pairing_payload())

    forward.ingest_events(peer_events)
    reverse.ingest_events(list(reversed(peer_events)))

    assert _catalog_snapshot(forward) == _catalog_snapshot(reverse)
    mix_f = next(m for m in forward.mixes() if m.id == mix_id)
    mix_r = next(m for m in reverse.mixes() if m.id == mix_id)
    assert mix_f.stars == mix_r.stars
    assert mix_f.tags == mix_r.tags
    assert mix_f.played is True and mix_r.played is True


def test_playhead_within_two_minutes_prefers_higher_position(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(laptop, source, title="Shared", platform_id="ph-near")
    laptop.create_intent(
        "Listen",
        seed=1,
        device_hours=[
            (laptop.device_id, 3600),
            (phone.device_id, 3600),
        ],
    )
    laptop.sync()
    phone.sync()
    laptop.disconnect(phone)

    laptop.set_current_mix(mix_id)
    laptop.report_playhead(100)
    clock.advance(60)
    phone.set_current_mix(mix_id)
    phone.report_playhead(40)

    laptop.connect(phone)
    laptop.sync()
    phone.sync()

    assert laptop.playhead(mix_id).position_seconds == 100
    assert phone.playhead(mix_id).position_seconds == 100


def test_playhead_beyond_two_minutes_prefers_later_author_time(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(laptop, source, title="Shared", platform_id="ph-far")
    laptop.create_intent(
        "Listen",
        seed=1,
        device_hours=[
            (laptop.device_id, 3600),
            (phone.device_id, 3600),
        ],
    )
    laptop.sync()
    phone.sync()
    laptop.disconnect(phone)

    laptop.set_current_mix(mix_id)
    laptop.report_playhead(900)
    clock.advance(180)
    phone.set_current_mix(mix_id)
    phone.report_playhead(50)

    laptop.connect(phone)
    laptop.sync()
    phone.sync()

    assert laptop.playhead(mix_id).position_seconds == 50
    assert phone.playhead(mix_id).position_seconds == 50


def test_artist_delete_is_sticky_against_older_add(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(laptop, source, title="Doomed", platform_id="doomed")
    artist_id = next(m for m in laptop.mixes() if m.id == mix_id).artist_id
    laptop.sync()
    phone.sync()
    laptop.disconnect(phone)

    clock.advance(1)
    laptop.delete_artist(artist_id)
    clock.advance(1)
    phone.rate_mix(mix_id, Stars.FOUR)

    laptop.connect(phone)
    laptop.sync()
    phone.sync()

    assert artist_id not in {a.id for a in laptop.artists()}
    assert artist_id not in {a.id for a in phone.artists()}
    assert mix_id not in {m.id for m in laptop.mixes()}
    assert mix_id not in {m.id for m in phone.mixes()}


def test_tampering_with_created_at_breaks_signature(tmp_path: Path) -> None:
    laptop, phone, source, clock = _pair(tmp_path)
    mix_id = _add_mix(laptop, source, title="Signed", platform_id="signed")
    laptop.sync()
    phone.sync()
    laptop.disconnect(phone)

    clock.advance(5)
    laptop.rate_mix(mix_id, Stars.FIVE)
    rated = next(
        e
        for e in laptop.export_events()
        if e.type.value == "mix_rated" and e.payload.get("mix_id") == str(mix_id)
    )
    tampered = rated.model_copy(update={"created_at": rated.created_at + timedelta(hours=1)})

    with pytest.raises(InvalidSignature):
        phone.ingest_events([tampered])
