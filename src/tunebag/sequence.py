"""Build a seeded intent sequence from tag/artist/platform filter + star distribution.

Probabilities are always used as draw chances (any budget). Empty buckets are
skipped and remaining probabilities are rescaled. The sequence fills until
cumulative duration is at least the largest device budget (may overshoot by
one mix), or the catalog runs out.
"""

from __future__ import annotations

import random
from collections import defaultdict
from uuid import UUID

from tunebag.domain import (
    Intent,
    Mix,
    Platform,
    Sequence,
    SequenceEntry,
    StarBucket,
    Stars,
)


def bucket_for(mix: Mix) -> StarBucket:
    if mix.stars is None:
        return StarBucket.UNRATED
    if mix.stars is Stars.ONE:
        return StarBucket.ONE
    if mix.stars is Stars.TWO:
        return StarBucket.TWO
    if mix.stars is Stars.THREE:
        return StarBucket.THREE
    if mix.stars is Stars.FOUR:
        return StarBucket.FOUR
    return StarBucket.FIVE


def matches_filter(
    mix: Mix,
    tags: list[str],
    artist_ids: list[UUID] | None = None,
    platforms: list[Platform] | None = None,
) -> bool:
    if mix.rejected:
        return False
    if platforms is not None:
        enabled = list(platforms)
        if not enabled or mix.platform not in set(enabled):
            return False
    artists = list(artist_ids or [])
    if artists and mix.artist_id not in set(artists):
        return False
    if tags:
        return not set(tags).isdisjoint(set(mix.tags))
    # Empty tags: untagged-only when no artist filter; otherwise all tags OK.
    if not artists:
        return len(mix.tags) == 0
    return True


def eligible_by_bucket(
    mixes: list[Mix],
    tags: list[str],
    rng: random.Random,
    artist_ids: list[UUID] | None = None,
    platforms: list[Platform] | None = None,
) -> dict[StarBucket, list[Mix]]:
    buckets: dict[StarBucket, list[Mix]] = defaultdict(list)
    for mix in mixes:
        if matches_filter(mix, tags, artist_ids, platforms):
            buckets[bucket_for(mix)].append(mix)
    for bucket in buckets:
        # Fresh first; played or skipped mixes sit at the back.
        # Seed shuffles within each group.
        fresh = [m for m in buckets[bucket] if not m.played and not m.skipped]
        retired = [m for m in buckets[bucket] if m.played or m.skipped]
        rng.shuffle(fresh)
        rng.shuffle(retired)
        buckets[bucket] = fresh + retired
    return buckets


def _draw_bucket(
    rng: random.Random,
    weights: dict[StarBucket, float],
    available: dict[StarBucket, list[Mix]],
) -> StarBucket | None:
    live = {
        bucket: weight
        for bucket, weight in weights.items()
        if weight > 0 and available.get(bucket)
    }
    if not live:
        return None
    total = sum(live.values())
    pick = rng.random() * total
    cumulative = 0.0
    for bucket, weight in live.items():
        cumulative += weight
        if pick <= cumulative:
            return bucket
    return next(iter(live))


def fill_sequence(
    intent: Intent,
    mixes: list[Mix],
    current: Sequence | None,
) -> Sequence:
    """Keep remaining queued order; drop retired; append until max device budget.

    Played, Skipped, and Rejected Releases leave the Sequence. Surviving entries
    keep their relative order. New draws exclude ids already kept and put
    Played/Skipped at the back of their star bucket via ``eligible_by_bucket``.
    """
    mix_by_id = {mix.id: mix for mix in mixes}
    kept: list[SequenceEntry] = []
    if current is not None:
        for entry in current.entries:
            mix = mix_by_id.get(entry.mix_id)
            if mix is None:
                continue
            if mix.played or mix.skipped or mix.rejected:
                continue
            if not matches_filter(
                mix, intent.tags, intent.artist_ids, intent.platforms
            ):
                continue
            kept.append(entry)

    entries = [
        SequenceEntry(mix_id=entry.mix_id, position=index, bucket=entry.bucket)
        for index, entry in enumerate(kept)
    ]
    used_seconds = sum(
        mix_by_id[entry.mix_id].duration_seconds for entry in entries
    )
    budget = intent.max_budget_seconds
    if used_seconds >= budget:
        return Sequence(intent_id=intent.id, entries=entries)

    rng = random.Random(intent.seed)
    available = eligible_by_bucket(
        mixes, intent.tags, rng, intent.artist_ids, intent.platforms
    )
    kept_ids = {entry.mix_id for entry in entries}
    for bucket, bucket_mixes in list(available.items()):
        available[bucket] = [mix for mix in bucket_mixes if mix.id not in kept_ids]
        if not available[bucket]:
            del available[bucket]

    weights = intent.distribution.as_map()
    while used_seconds < budget:
        bucket = _draw_bucket(rng, weights, available)
        if bucket is None:
            break
        mix = available[bucket].pop(0)
        if not available[bucket]:
            del available[bucket]
        entries.append(
            SequenceEntry(mix_id=mix.id, position=len(entries), bucket=bucket)
        )
        used_seconds += mix.duration_seconds

    return Sequence(intent_id=intent.id, entries=entries)


def build_sequence(intent: Intent, mixes: list[Mix]) -> Sequence:
    """Draw mixes until cumulative duration is at least max device budget."""
    return fill_sequence(intent, mixes, current=None)


def assignments_for_intent(
    intent: Intent, sequence: Sequence
) -> dict[UUID, list[UUID]]:
    """Prefix of the shared sequence for each device's hours."""
    mix_ids = [entry.mix_id for entry in sequence.entries]
    # Durations are not on SequenceEntry; callers that need exact packing by
    # seconds should pass a duration map. For assignment by count-of-prefix we
    # use cumulative duration when a duration lookup is provided via intent
    # device budgets as a wall — here we return mix_ids sliced by cumulative
    # duration if the caller also supplies durations. Kept simple: return the
    # full sequence for every device and let assign_by_budget refine.
    return {dh.device_id: mix_ids for dh in intent.device_hours}


def assign_by_budget(
    sequence: Sequence,
    device_id: UUID,
    budget_seconds: int,
    duration_by_mix: dict[UUID, int],
) -> list[UUID]:
    """Take the prefix until cumulative duration is at least this device's hours."""
    chosen: list[UUID] = []
    used = 0
    for entry in sequence.entries:
        chosen.append(entry.mix_id)
        used += duration_by_mix[entry.mix_id]
        if used >= budget_seconds:
            break
    return chosen
