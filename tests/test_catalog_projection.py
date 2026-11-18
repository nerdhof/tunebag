"""Unit tests for Catalog projection merge (no DeviceAgent / Event log I/O)."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from tunebag.domain import Platform, Stars, new_id
from tunebag.events import Event, EventType
from tunebag.projection import CatalogState, apply, replay


def _event(
    event_type: EventType,
    payload: dict,
    *,
    device_id: UUID,
    created_at: datetime,
    seq: int = 1,
) -> Event:
    return Event(
        type=event_type,
        device_id=device_id,
        created_at=created_at,
        seq=seq,
        payload=payload,
    )


def _seed_mix(
    state: CatalogState,
    *,
    local_device_id: UUID,
    mix_id: UUID | None = None,
    artist_id: UUID | None = None,
) -> tuple[UUID, UUID]:
    artist_id = artist_id or new_id()
    mix_id = mix_id or new_id()
    t0 = datetime(2024, 1, 1, 12, 0, 0)
    apply(
        state,
        _event(
            EventType.ARTIST_ADDED,
            {
                "id": str(artist_id),
                "platform": Platform.SOUNDCLOUD.value,
                "platform_id": "artist-1",
                "name": "DJ Example",
                "url": "https://example.com/artist",
            },
            device_id=local_device_id,
            created_at=t0,
            seq=1,
        ),
        local_device_id=local_device_id,
        now=t0,
    )
    apply(
        state,
        _event(
            EventType.MIX_ADDED,
            {
                "id": str(mix_id),
                "artist_id": str(artist_id),
                "platform": Platform.SOUNDCLOUD.value,
                "platform_id": "mix-1",
                "title": "Shared",
                "url": "https://example.com/mix",
                "duration_seconds": 3600,
            },
            device_id=local_device_id,
            created_at=t0 + timedelta(seconds=1),
            seq=2,
        ),
        local_device_id=local_device_id,
        now=t0,
    )
    return artist_id, mix_id


def test_playhead_within_two_minutes_prefers_higher_position() -> None:
    local = uuid4()
    peer = uuid4()
    state = CatalogState()
    _, mix_id = _seed_mix(state, local_device_id=local)
    t0 = datetime(2024, 1, 1, 12, 0, 0)

    apply(
        state,
        _event(
            EventType.PLAYHEAD,
            {"mix_id": str(mix_id), "position_seconds": 100.0},
            device_id=local,
            created_at=t0,
            seq=3,
        ),
        local_device_id=local,
        now=t0,
    )
    apply(
        state,
        _event(
            EventType.PLAYHEAD,
            {"mix_id": str(mix_id), "position_seconds": 40.0},
            device_id=peer,
            created_at=t0 + timedelta(seconds=60),
            seq=1,
        ),
        local_device_id=local,
        now=t0,
    )

    assert state.playheads[mix_id].position_seconds == 100.0


def test_playhead_beyond_two_minutes_prefers_later_author_time() -> None:
    local = uuid4()
    peer = uuid4()
    state = CatalogState()
    _, mix_id = _seed_mix(state, local_device_id=local)
    t0 = datetime(2024, 1, 1, 12, 0, 0)

    apply(
        state,
        _event(
            EventType.PLAYHEAD,
            {"mix_id": str(mix_id), "position_seconds": 900.0},
            device_id=local,
            created_at=t0,
            seq=3,
        ),
        local_device_id=local,
        now=t0,
    )
    apply(
        state,
        _event(
            EventType.PLAYHEAD,
            {"mix_id": str(mix_id), "position_seconds": 50.0},
            device_id=peer,
            created_at=t0 + timedelta(seconds=180),
            seq=1,
        ),
        local_device_id=local,
        now=t0,
    )

    assert state.playheads[mix_id].position_seconds == 50.0


def test_artist_delete_is_sticky_against_later_mix_add() -> None:
    local = uuid4()
    peer = uuid4()
    state = CatalogState()
    artist_id, mix_id = _seed_mix(state, local_device_id=local)
    t0 = datetime(2024, 1, 1, 12, 0, 0)

    _, effects = apply(
        state,
        _event(
            EventType.ARTIST_DELETED,
            {"id": str(artist_id)},
            device_id=local,
            created_at=t0 + timedelta(seconds=2),
            seq=3,
        ),
        local_device_id=local,
        now=t0,
    )
    assert mix_id in effects.delete_files
    assert artist_id not in state.artists
    assert mix_id not in state.mixes

    apply(
        state,
        _event(
            EventType.MIX_ADDED,
            {
                "id": str(mix_id),
                "artist_id": str(artist_id),
                "platform": Platform.SOUNDCLOUD.value,
                "platform_id": "mix-1",
                "title": "Shared",
                "url": "https://example.com/mix",
                "duration_seconds": 3600,
            },
            device_id=peer,
            created_at=t0 + timedelta(seconds=3),
            seq=1,
        ),
        local_device_id=local,
        now=t0,
    )
    apply(
        state,
        _event(
            EventType.ARTIST_ADDED,
            {
                "id": str(artist_id),
                "platform": Platform.SOUNDCLOUD.value,
                "platform_id": "artist-1",
                "name": "DJ Example",
                "url": "https://example.com/artist",
            },
            device_id=peer,
            created_at=t0 + timedelta(seconds=3),
            seq=2,
        ),
        local_device_id=local,
        now=t0,
    )

    assert artist_id not in state.artists
    assert mix_id not in state.mixes


def test_tags_and_stars_last_writer_wins_by_author_time() -> None:
    local = uuid4()
    peer = uuid4()
    state = CatalogState()
    _, mix_id = _seed_mix(state, local_device_id=local)
    t0 = datetime(2024, 1, 1, 12, 0, 0)

    apply(
        state,
        _event(
            EventType.MIX_RATED,
            {"mix_id": str(mix_id), "stars": int(Stars.FIVE)},
            device_id=local,
            created_at=t0 + timedelta(seconds=1),
            seq=3,
        ),
        local_device_id=local,
        now=t0,
    )
    apply(
        state,
        _event(
            EventType.MIX_TAGGED,
            {"mix_id": str(mix_id), "tags": ["laptop"]},
            device_id=local,
            created_at=t0 + timedelta(seconds=1),
            seq=4,
        ),
        local_device_id=local,
        now=t0,
    )
    apply(
        state,
        _event(
            EventType.MIX_RATED,
            {"mix_id": str(mix_id), "stars": int(Stars.TWO)},
            device_id=peer,
            created_at=t0 + timedelta(seconds=2),
            seq=1,
        ),
        local_device_id=local,
        now=t0,
    )
    apply(
        state,
        _event(
            EventType.MIX_TAGGED,
            {"mix_id": str(mix_id), "tags": ["phone"]},
            device_id=peer,
            created_at=t0 + timedelta(seconds=2),
            seq=2,
        ),
        local_device_id=local,
        now=t0,
    )

    mix = state.mixes[mix_id]
    assert mix.stars == Stars.TWO
    assert mix.tags == ["phone"]


def test_played_is_sticky_and_reject_beats_older_unreject() -> None:
    local = uuid4()
    peer = uuid4()
    state = CatalogState()
    _, mix_id = _seed_mix(state, local_device_id=local)
    t0 = datetime(2024, 1, 1, 12, 0, 0)

    apply(
        state,
        _event(
            EventType.PLAYED,
            {"mix_id": str(mix_id)},
            device_id=peer,
            created_at=t0 + timedelta(seconds=1),
            seq=1,
        ),
        local_device_id=local,
        now=t0,
    )
    _, reject_effects = apply(
        state,
        _event(
            EventType.MIX_REJECTED,
            {"mix_id": str(mix_id)},
            device_id=local,
            created_at=t0 + timedelta(seconds=2),
            seq=3,
        ),
        local_device_id=local,
        now=t0,
    )
    apply(
        state,
        _event(
            EventType.MIX_UNREJECTED,
            {"mix_id": str(mix_id)},
            device_id=peer,
            created_at=t0 + timedelta(seconds=1),
            seq=2,
        ),
        local_device_id=local,
        now=t0,
    )

    mix = state.mixes[mix_id]
    assert mix.played is True
    assert mix.rejected is True
    assert reject_effects.delete_files == [mix_id]


def test_replay_order_does_not_change_converged_catalog() -> None:
    local = uuid4()
    peer = uuid4()
    artist_id = new_id()
    mix_id = new_id()
    t0 = datetime(2024, 1, 1, 12, 0, 0)
    events = [
        _event(
            EventType.ARTIST_ADDED,
            {
                "id": str(artist_id),
                "platform": Platform.SOUNDCLOUD.value,
                "platform_id": "artist-1",
                "name": "DJ Example",
                "url": "https://example.com/artist",
            },
            device_id=local,
            created_at=t0,
            seq=1,
        ),
        _event(
            EventType.MIX_ADDED,
            {
                "id": str(mix_id),
                "artist_id": str(artist_id),
                "platform": Platform.SOUNDCLOUD.value,
                "platform_id": "mix-1",
                "title": "Shared",
                "url": "https://example.com/mix",
                "duration_seconds": 3600,
            },
            device_id=local,
            created_at=t0 + timedelta(seconds=1),
            seq=2,
        ),
        _event(
            EventType.MIX_RATED,
            {"mix_id": str(mix_id), "stars": int(Stars.FIVE)},
            device_id=local,
            created_at=t0 + timedelta(seconds=2),
            seq=3,
        ),
        _event(
            EventType.MIX_TAGGED,
            {"mix_id": str(mix_id), "tags": ["a"]},
            device_id=local,
            created_at=t0 + timedelta(seconds=2),
            seq=4,
        ),
        _event(
            EventType.MIX_RATED,
            {"mix_id": str(mix_id), "stars": int(Stars.TWO)},
            device_id=peer,
            created_at=t0 + timedelta(seconds=3),
            seq=1,
        ),
        _event(
            EventType.MIX_TAGGED,
            {"mix_id": str(mix_id), "tags": ["b"]},
            device_id=peer,
            created_at=t0 + timedelta(seconds=3),
            seq=2,
        ),
        _event(
            EventType.PLAYED,
            {"mix_id": str(mix_id)},
            device_id=peer,
            created_at=t0 + timedelta(seconds=3),
            seq=3,
        ),
    ]

    forward = CatalogState()
    reverse = CatalogState()
    replay(forward, events, local_device_id=local, now=t0)
    replay(reverse, list(reversed(events)), local_device_id=local, now=t0)

    assert forward.mixes[mix_id].stars == reverse.mixes[mix_id].stars == Stars.TWO
    assert forward.mixes[mix_id].tags == reverse.mixes[mix_id].tags == ["b"]
    assert forward.mixes[mix_id].played is True
    assert reverse.mixes[mix_id].played is True


def test_intent_delete_removes_folder_effect() -> None:
    local = uuid4()
    state = CatalogState()
    intent_id = new_id()
    t0 = datetime(2024, 1, 1, 12, 0, 0)
    apply(
        state,
        _event(
            EventType.INTENT_UPSERTED,
            {
                "id": str(intent_id),
                "name": "Plan",
                "tags": [],
                "artist_ids": [],
                "platforms": [Platform.SOUNDCLOUD.value],
                "distribution": {
                    "five": 0.3,
                    "four": 0.2,
                    "three": 0.1,
                    "two": 0.05,
                    "one": 0.05,
                    "unrated": 0.3,
                },
                "device_hours": [],
                "seed": 1,
            },
            device_id=local,
            created_at=t0,
            seq=1,
        ),
        local_device_id=local,
        now=t0,
    )
    _, effects = apply(
        state,
        _event(
            EventType.INTENT_DELETED,
            {"id": str(intent_id)},
            device_id=local,
            created_at=t0 + timedelta(seconds=1),
            seq=2,
        ),
        local_device_id=local,
        now=t0,
    )
    assert intent_id not in state.intents
    assert effects.remove_intent_folders == [intent_id]
