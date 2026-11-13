"""Issue 03: share one sequence — exercised only through DeviceAgent."""

from __future__ import annotations

from uuid import UUID

from mixy.agent import DeviceAgent
from mixy.domain import Platform, Stars


def _pair() -> tuple[DeviceAgent, DeviceAgent]:
    laptop = DeviceAgent("laptop", priority=1)
    phone = DeviceAgent("phone", priority=10)
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    return laptop, phone


def _add_mix(
    agent: DeviceAgent,
    *,
    title: str,
    duration_seconds: int,
    platform_id: str,
    tags: list[str] | None = None,
    stars: Stars | None = None,
) -> UUID:
    mix = agent.add_mix(
        title=title,
        url=f"https://example.com/{platform_id}",
        duration_seconds=duration_seconds,
        platform=Platform.SOUNDCLOUD,
        platform_id=platform_id,
        artist_name="DJ Example",
    )
    if tags is not None:
        agent.tag_mix(mix.id, tags)
    if stars is not None:
        agent.rate_mix(mix.id, stars)
    return mix.id


def test_intent_has_name_tags_and_default_star_chances() -> None:
    laptop, _phone = _pair()

    intent = laptop.create_intent("Deep house", tags=["deep", "house"])

    assert intent.name == "Deep house"
    assert intent.tags == ["deep", "house"]
    assert intent.distribution.five == 0.3
    assert intent.distribution.four == 0.2
    assert intent.distribution.three == 0.1
    assert intent.distribution.two == 0.05
    assert intent.distribution.one == 0.05
    assert intent.distribution.unrated == 0.3
    assert intent.id in {i.id for i in laptop.intents()}


def test_several_tags_require_all_empty_tags_match_only_untagged() -> None:
    laptop, _phone = _pair()
    both = _add_mix(
        laptop,
        title="Both tags",
        duration_seconds=3600,
        platform_id="both",
        tags=["deep", "house"],
        stars=Stars.FIVE,
    )
    _add_mix(
        laptop,
        title="Only deep",
        duration_seconds=3600,
        platform_id="deep-only",
        tags=["deep"],
        stars=Stars.FIVE,
    )
    untagged = _add_mix(
        laptop,
        title="Untagged",
        duration_seconds=3600,
        platform_id="untagged",
        stars=Stars.FIVE,
    )

    tagged_intent = laptop.create_intent(
        "Tagged",
        tags=["deep", "house"],
        seed=1,
        device_hours=[(laptop.device_id, 7200)],
    )
    tagged_seq = laptop.sequence(tagged_intent.id)
    assert tagged_seq is not None
    assert [e.mix_id for e in tagged_seq.entries] == [both]

    exploratory = laptop.create_intent(
        "Exploratory",
        tags=[],
        seed=1,
        device_hours=[(laptop.device_id, 7200)],
    )
    explor_seq = laptop.sequence(exploratory.id)
    assert explor_seq is not None
    assert [e.mix_id for e in explor_seq.entries] == [untagged]


def test_rejected_excluded_and_empty_bucket_skipped() -> None:
    laptop, _phone = _pair()
    keeper = _add_mix(
        laptop,
        title="Four star keeper",
        duration_seconds=3600,
        platform_id="four",
        tags=["techno"],
        stars=Stars.FOUR,
    )
    rejected = _add_mix(
        laptop,
        title="Rejected five",
        duration_seconds=3600,
        platform_id="rej",
        tags=["techno"],
        stars=Stars.FIVE,
    )
    laptop.reject_mix(rejected)

    # No five-star candidates left; draw must still fill from other buckets.
    intent = laptop.create_intent(
        "Techno",
        tags=["techno"],
        seed=0,
        device_hours=[(laptop.device_id, 3600)],
    )
    seq = laptop.sequence(intent.id)
    assert seq is not None
    assert [e.mix_id for e in seq.entries] == [keeper]
    assert rejected not in {e.mix_id for e in seq.entries}


def test_shared_sequence_phone_is_prefix_of_laptop_after_sync() -> None:
    laptop, phone = _pair()
    hour_ids = [
        _add_mix(
            laptop,
            title=f"Hour {i}",
            duration_seconds=3600,
            platform_id=f"h{i}",
            tags=["set"],
            stars=Stars.FIVE,
        )
        for i in range(10)
    ]

    intent = laptop.create_intent(
        "Commute",
        tags=["set"],
        seed=42,
        device_hours=[
            (phone.device_id, 2 * 3600),
            (laptop.device_id, 8 * 3600),
        ],
    )
    laptop.sync()
    phone.sync()

    laptop_seq = laptop.sequence(intent.id)
    phone_seq = phone.sequence(intent.id)
    assert laptop_seq is not None and phone_seq is not None
    assert [e.mix_id for e in phone_seq.entries] == [e.mix_id for e in laptop_seq.entries]

    laptop_asg = laptop.assignment(intent.id, laptop.device_id)
    phone_asg = phone.assignment(intent.id, phone.device_id)
    assert laptop_asg is not None and phone_asg is not None
    assert phone_asg.mix_ids == laptop_asg.mix_ids[: len(phone_asg.mix_ids)]
    assert len(phone_asg.mix_ids) == 2
    assert len(laptop_asg.mix_ids) == 8
    assert set(phone_asg.mix_ids).issubset(set(hour_ids))
    assert set(laptop_asg.mix_ids) - set(phone_asg.mix_ids)


def test_short_stretch_may_be_two_five_star_mixes() -> None:
    laptop, _phone = _pair()
    five_a = _add_mix(
        laptop,
        title="Five A",
        duration_seconds=3600,
        platform_id="5a",
        tags=["peak"],
        stars=Stars.FIVE,
    )
    five_b = _add_mix(
        laptop,
        title="Five B",
        duration_seconds=3600,
        platform_id="5b",
        tags=["peak"],
        stars=Stars.FIVE,
    )
    _add_mix(
        laptop,
        title="Three C",
        duration_seconds=3600,
        platform_id="3c",
        tags=["peak"],
        stars=Stars.THREE,
    )

    # Seed chosen so both draws land in the five-star bucket.
    intent = laptop.create_intent(
        "Peak",
        tags=["peak"],
        seed=7,
        device_hours=[(laptop.device_id, 2 * 3600)],
    )
    asg = laptop.assignment(intent.id, laptop.device_id)
    assert asg is not None
    assert asg.mix_ids == [five_a, five_b]


def test_stops_before_overshoot_and_oversize_fills_empty() -> None:
    laptop, _phone = _pair()
    short_a = _add_mix(
        laptop,
        title="Short A",
        duration_seconds=3600,
        platform_id="sa",
        tags=["fit"],
        stars=Stars.FIVE,
    )
    short_b = _add_mix(
        laptop,
        title="Short B",
        duration_seconds=3600,
        platform_id="sb",
        tags=["fit"],
        stars=Stars.FIVE,
    )
    _add_mix(
        laptop,
        title="Would overshoot",
        duration_seconds=3600,
        platform_id="over",
        tags=["fit"],
        stars=Stars.FIVE,
    )

    fit = laptop.create_intent(
        "Fit",
        tags=["fit"],
        seed=1,
        device_hours=[(laptop.device_id, 7200)],
    )
    fit_seq = laptop.sequence(fit.id)
    assert fit_seq is not None
    assert [e.mix_id for e in fit_seq.entries] == [short_a, short_b]

    oversize_only = DeviceAgent("solo")
    big = _add_mix(
        oversize_only,
        title="Too long",
        duration_seconds=10_000,
        platform_id="big",
        tags=["solo"],
        stars=Stars.FIVE,
    )
    intent = oversize_only.create_intent(
        "Solo",
        tags=["solo"],
        seed=1,
        device_hours=[(oversize_only.device_id, 3600)],
    )
    seq = oversize_only.sequence(intent.id)
    assert seq is not None
    assert [e.mix_id for e in seq.entries] == [big]


def test_set_device_hours_rebuilds_shared_sequence() -> None:
    laptop, phone = _pair()
    for i in range(5):
        _add_mix(
            laptop,
            title=f"Mix {i}",
            duration_seconds=3600,
            platform_id=f"m{i}",
            tags=["rebuild"],
            stars=Stars.FOUR,
        )

    intent = laptop.create_intent(
        "Rebuild",
        tags=["rebuild"],
        seed=3,
        device_hours=[(laptop.device_id, 3600)],
    )
    first = laptop.sequence(intent.id)
    assert first is not None
    assert len(first.entries) == 1

    laptop.set_device_hours(intent.id, phone.device_id, 2 * 3600)
    laptop.set_device_hours(intent.id, laptop.device_id, 4 * 3600)
    laptop.sync()
    phone.sync()

    rebuilt = phone.sequence(intent.id)
    assert rebuilt is not None
    assert len(rebuilt.entries) == 4
    phone_asg = phone.assignment(intent.id, phone.device_id)
    assert phone_asg is not None
    assert len(phone_asg.mix_ids) == 2
    assert phone_asg.mix_ids == [e.mix_id for e in rebuilt.entries[:2]]
