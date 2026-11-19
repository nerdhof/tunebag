"""Unit tests for seeded sequence building."""

from __future__ import annotations

from uuid import uuid4

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
from tunebag.sequence import assign_by_budget, build_sequence, matches_filter


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


def test_matches_filter_empty_tags_untagged_only_without_artists() -> None:
    artist = uuid4()
    untagged = Mix(
        artist_id=artist,
        platform=Platform.SOUNDCLOUD,
        platform_id="u",
        title="U",
        url="https://example.com/u",
        duration_seconds=60,
    )
    tagged = Mix(
        artist_id=artist,
        platform=Platform.SOUNDCLOUD,
        platform_id="t",
        title="T",
        url="https://example.com/t",
        duration_seconds=60,
        tags=["deep"],
    )
    assert matches_filter(untagged, []) is True
    assert matches_filter(tagged, []) is False


def test_matches_filter_empty_tags_with_artist_allows_tagged_and_untagged() -> None:
    artist_a = uuid4()
    artist_b = uuid4()
    tagged_a = Mix(
        artist_id=artist_a,
        platform=Platform.SOUNDCLOUD,
        platform_id="ta",
        title="TA",
        url="https://example.com/ta",
        duration_seconds=60,
        tags=["deep"],
    )
    untagged_a = Mix(
        artist_id=artist_a,
        platform=Platform.SOUNDCLOUD,
        platform_id="ua",
        title="UA",
        url="https://example.com/ua",
        duration_seconds=60,
    )
    other = Mix(
        artist_id=artist_b,
        platform=Platform.SOUNDCLOUD,
        platform_id="ob",
        title="OB",
        url="https://example.com/ob",
        duration_seconds=60,
    )
    assert matches_filter(tagged_a, [], [artist_a]) is True
    assert matches_filter(untagged_a, [], [artist_a]) is True
    assert matches_filter(other, [], [artist_a]) is False


def test_matches_filter_tags_and_artist_intersection() -> None:
    artist_a = uuid4()
    artist_b = uuid4()
    deep_a = Mix(
        artist_id=artist_a,
        platform=Platform.SOUNDCLOUD,
        platform_id="da",
        title="DA",
        url="https://example.com/da",
        duration_seconds=60,
        tags=["deep"],
    )
    house_a = Mix(
        artist_id=artist_a,
        platform=Platform.SOUNDCLOUD,
        platform_id="ha",
        title="HA",
        url="https://example.com/ha",
        duration_seconds=60,
        tags=["house"],
    )
    deep_b = Mix(
        artist_id=artist_b,
        platform=Platform.SOUNDCLOUD,
        platform_id="db",
        title="DB",
        url="https://example.com/db",
        duration_seconds=60,
        tags=["deep"],
    )
    assert matches_filter(deep_a, ["deep"], [artist_a]) is True
    assert matches_filter(house_a, ["deep"], [artist_a]) is False
    assert matches_filter(deep_b, ["deep"], [artist_a]) is False


def test_build_sequence_empty_tags_with_artist_fills_tagged_and_untagged() -> None:
    artist_a = uuid4()
    artist_b = uuid4()
    mixes = [
        Mix(
            artist_id=artist_a,
            platform=Platform.SOUNDCLOUD,
            platform_id="tagged",
            title="Tagged",
            url="https://example.com/tagged",
            duration_seconds=3600,
            tags=["deep"],
            stars=Stars.FIVE,
        ),
        Mix(
            artist_id=artist_a,
            platform=Platform.SOUNDCLOUD,
            platform_id="untagged",
            title="Untagged",
            url="https://example.com/untagged",
            duration_seconds=3600,
            stars=Stars.FIVE,
        ),
        Mix(
            artist_id=artist_b,
            platform=Platform.SOUNDCLOUD,
            platform_id="other",
            title="Other",
            url="https://example.com/other",
            duration_seconds=3600,
            stars=Stars.FIVE,
        ),
    ]
    intent = Intent(
        name="Artist A",
        tags=[],
        artist_ids=[artist_a],
        seed=1,
        device_hours=[DeviceHours(device_id=uuid4(), budget_seconds=7200)],
    )
    ids = {e.mix_id for e in build_sequence(intent, mixes).entries}
    assert ids == {mixes[0].id, mixes[1].id}


def test_matches_filter_platforms_or_membership() -> None:
    artist = uuid4()
    sc = Mix(
        artist_id=artist,
        platform=Platform.SOUNDCLOUD,
        platform_id="sc",
        title="SC",
        url="https://example.com/sc",
        duration_seconds=60,
        tags=["deep"],
    )
    yt = Mix(
        artist_id=artist,
        platform=Platform.YOUTUBE,
        platform_id="yt",
        title="YT",
        url="https://example.com/yt",
        duration_seconds=60,
        tags=["deep"],
    )
    assert matches_filter(sc, ["deep"], platforms=[Platform.SOUNDCLOUD]) is True
    assert matches_filter(yt, ["deep"], platforms=[Platform.SOUNDCLOUD]) is False
    assert matches_filter(yt, ["deep"], platforms=[Platform.SOUNDCLOUD, Platform.YOUTUBE]) is True
    assert matches_filter(sc, ["deep"], platforms=[]) is False


def test_build_sequence_platforms_excludes_other_sources() -> None:
    artist = uuid4()
    mixes = [
        Mix(
            artist_id=artist,
            platform=Platform.SOUNDCLOUD,
            platform_id="sc",
            title="SC",
            url="https://example.com/sc",
            duration_seconds=3600,
            tags=["set"],
            stars=Stars.FIVE,
        ),
        Mix(
            artist_id=artist,
            platform=Platform.BANDCAMP,
            platform_id="bc",
            title="BC",
            url="https://example.com/bc",
            duration_seconds=3600,
            tags=["set"],
            stars=Stars.FIVE,
        ),
    ]
    intent = Intent(
        name="SC only",
        tags=["set"],
        platforms=[Platform.SOUNDCLOUD],
        seed=1,
        device_hours=[DeviceHours(device_id=uuid4(), budget_seconds=7200)],
    )
    ids = {e.mix_id for e in build_sequence(intent, mixes).entries}
    assert ids == {mixes[0].id}

