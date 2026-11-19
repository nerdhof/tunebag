"""Round-trip tests for Intent and mix_added Event payload codec."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from tunebag.domain import (
    AlbumTrack,
    DeviceHours,
    Intent,
    Mix,
    Platform,
    ReleaseKind,
    StarDistribution,
)
from tunebag.event_payloads import (
    decode_intent,
    decode_mix_added,
    encode_intent,
    encode_mix_added,
)


def test_intent_roundtrip_includes_device_hours_and_cleared_ids() -> None:
    device_a = uuid4()
    device_b = uuid4()
    expires = datetime(2026, 6, 1, 12, 0, 0)
    intent = Intent(
        name="Weekend",
        tags=["deep", "house"],
        artist_ids=[uuid4()],
        platforms=[Platform.SOUNDCLOUD, Platform.BANDCAMP],
        distribution=StarDistribution(
            five=0.4, four=0.2, three=0.1, two=0.05, one=0.05, unrated=0.2
        ),
        device_hours=[
            DeviceHours(device_id=device_a, budget_seconds=7200, expires_at=expires),
            DeviceHours(device_id=device_b, budget_seconds=3600),
        ],
        seed=42,
    )
    cleared = [device_b]
    payload = encode_intent(intent, cleared_device_ids=cleared)

    assert payload["cleared_device_ids"] == [str(device_b)]
    restored = decode_intent(payload)
    assert restored.id == intent.id
    assert restored.name == intent.name
    assert restored.tags == intent.tags
    assert restored.artist_ids == intent.artist_ids
    assert restored.platforms == intent.platforms
    assert restored.distribution == intent.distribution
    assert restored.seed == intent.seed
    assert len(restored.device_hours) == 2
    by_id = {dh.device_id: dh for dh in restored.device_hours}
    assert by_id[device_a].budget_seconds == 7200
    assert by_id[device_a].expires_at == expires
    assert by_id[device_b].budget_seconds == 3600
    assert by_id[device_b].expires_at is None


def test_intent_decode_defaults_missing_artist_ids_and_platforms() -> None:
    intent = Intent(
        name="Legacy",
        tags=["deep"],
        artist_ids=[uuid4()],
        platforms=[Platform.BANDCAMP],
        seed=7,
        device_hours=[],
    )
    payload = encode_intent(intent)
    del payload["artist_ids"]
    del payload["platforms"]
    restored = decode_intent(payload)
    assert restored.artist_ids == []
    assert restored.platforms == [
        Platform.SOUNDCLOUD,
        Platform.HEARTHIS,
        Platform.BANDCAMP,
        Platform.YOUTUBE,
    ]


def test_mix_added_roundtrip_for_mix_release() -> None:
    mix = Mix(
        artist_id=uuid4(),
        platform=Platform.SOUNDCLOUD,
        platform_id="m1",
        title="Night set",
        url="https://example.com/m1",
        duration_seconds=5400,
        size_bytes=12_000_000,
        cover_url="https://cdn.example/cover.jpg",
        kind=ReleaseKind.MIX,
    )
    payload = encode_mix_added(mix)
    assert payload["cover_url"] == "https://cdn.example/cover.jpg"
    restored = decode_mix_added(payload)
    assert restored.id == mix.id
    assert restored.artist_id == mix.artist_id
    assert restored.platform == mix.platform
    assert restored.platform_id == mix.platform_id
    assert restored.title == mix.title
    assert restored.url == mix.url
    assert restored.duration_seconds == mix.duration_seconds
    assert restored.size_bytes == mix.size_bytes
    assert restored.cover_url == mix.cover_url
    assert restored.kind is ReleaseKind.MIX
    assert restored.tracks == []


def test_mix_added_decode_omits_missing_cover_url() -> None:
    mix = Mix(
        artist_id=uuid4(),
        platform=Platform.SOUNDCLOUD,
        platform_id="m2",
        title="No cover",
        url="https://example.com/m2",
        duration_seconds=3600,
        kind=ReleaseKind.MIX,
    )
    payload = encode_mix_added(mix)
    assert "cover_url" not in payload
    restored = decode_mix_added(payload)
    assert restored.cover_url is None


def test_mix_added_roundtrip_for_album_tracks() -> None:
    mix = Mix(
        artist_id=uuid4(),
        platform=Platform.BANDCAMP,
        platform_id="album-1",
        title="LP",
        url="https://artist.bandcamp.com/album/lp",
        duration_seconds=600,
        size_bytes=None,
        kind=ReleaseKind.ALBUM,
        tracks=[
            AlbumTrack(
                platform_id="t1",
                title="One",
                url="https://artist.bandcamp.com/track/one",
                duration_seconds=200,
                size_bytes=1_000_000,
            ),
            AlbumTrack(
                platform_id="t2",
                title="Two",
                url="https://artist.bandcamp.com/track/two",
                duration_seconds=400,
            ),
        ],
    )
    restored = decode_mix_added(encode_mix_added(mix))
    assert restored.kind is ReleaseKind.ALBUM
    assert restored.tracks == mix.tracks
    assert restored.size_bytes is None


def test_device_agent_does_not_import_projection_intent_decode() -> None:
    import inspect

    import tunebag.agent as agent_mod
    from tunebag.event_payloads import encode_intent, encode_mix_added

    source = inspect.getsource(agent_mod)
    assert "_intent_from_payload" not in source
    assert "decode_intent" not in source
    assert agent_mod.encode_intent is encode_intent
    assert agent_mod.encode_mix_added is encode_mix_added
