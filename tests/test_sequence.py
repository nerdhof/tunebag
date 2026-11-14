"""Unit tests for seeded sequence building."""

from __future__ import annotations

from uuid import uuid4

from mixy.domain import (
    DeviceHours,
    Intent,
    Mix,
    Platform,
    Sequence,
    SequenceEntry,
    StarBucket,
    Stars,
)
from mixy.sequence import assign_by_budget, build_sequence


def _five_star_mixes(n: int) -> list[Mix]:
    artist_id = uuid4()
    return [
        Mix(
            artist_id=artist_id,
            platform=Platform.SOUNDCLOUD,
            platform_id=f"m{i}",
            title=f"Mix {i:02d}",
            url=f"https://example.com/{i}",
            duration_seconds=3600,
            tags=["set"],
            stars=Stars.FIVE,
        )
        for i in range(n)
    ]


def test_same_seed_reproduces_within_bucket_order() -> None:
    mixes = _five_star_mixes(8)
    device_id = uuid4()
    intent = Intent(
        name="Commute",
        tags=["set"],
        seed=99,
        device_hours=[DeviceHours(device_id=device_id, budget_seconds=4 * 3600)],
    )
    first = [e.mix_id for e in build_sequence(intent, mixes).entries]
    second = [e.mix_id for e in build_sequence(intent, mixes).entries]
    assert first == second
    assert len(first) == 4


def test_different_seeds_change_within_bucket_order() -> None:
    mixes = _five_star_mixes(8)
    device_id = uuid4()
    hours = [DeviceHours(device_id=device_id, budget_seconds=4 * 3600)]
    a = Intent(name="A", tags=["set"], seed=1, device_hours=hours)
    b = Intent(name="B", tags=["set"], seed=2, device_hours=hours)
    order_a = [e.mix_id for e in build_sequence(a, mixes).entries]
    order_b = [e.mix_id for e in build_sequence(b, mixes).entries]
    assert len(order_a) == len(order_b) == 4
    assert order_a != order_b


def test_assign_by_budget_includes_mix_that_crosses_hours() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    sequence = Sequence(
        intent_id=uuid4(),
        entries=[
            SequenceEntry(mix_id=a, position=0, bucket=StarBucket.FIVE),
            SequenceEntry(mix_id=b, position=1, bucket=StarBucket.FIVE),
            SequenceEntry(mix_id=c, position=2, bucket=StarBucket.FIVE),
        ],
    )
    durations = {a: 3600, b: 5400, c: 3600}
    # 2h budget: 1h + 1.5h → both (2.5h), not stop at 1h.
    assert assign_by_budget(sequence, uuid4(), 2 * 3600, durations) == [a, b]


def test_build_sequence_fills_at_least_budget_with_overshoot() -> None:
    artist_id = uuid4()
    mixes = [
        Mix(
            artist_id=artist_id,
            platform=Platform.SOUNDCLOUD,
            platform_id="long",
            title="Long",
            url="https://example.com/long",
            duration_seconds=5 * 3600 + 20 * 60,
            tags=["set"],
            stars=Stars.FIVE,
        ),
        Mix(
            artist_id=artist_id,
            platform=Platform.SOUNDCLOUD,
            platform_id="next",
            title="Next",
            url="https://example.com/next",
            duration_seconds=3 * 3600,
            tags=["set"],
            stars=Stars.FIVE,
        ),
    ]
    intent = Intent(
        name="Weekend",
        tags=["set"],
        seed=1,
        device_hours=[DeviceHours(device_id=uuid4(), budget_seconds=8 * 3600)],
    )
    entries = build_sequence(intent, mixes).entries
    assert {e.mix_id for e in entries} == {m.id for m in mixes}
    total = sum(
        next(m.duration_seconds for m in mixes if m.id == e.mix_id) for e in entries
    )
    assert total == 8 * 3600 + 20 * 60
