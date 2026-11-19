"""Shared encode/decode for Intent and Release-add (`mix_added`) Event payloads."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from tunebag.domain import (
    AlbumTrack,
    DeviceHours,
    Intent,
    Mix,
    Platform,
    ReleaseKind,
    StarDistribution,
    default_intent_platforms,
)


def encode_intent(
    intent: Intent,
    *,
    cleared_device_ids: list[UUID] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(intent.id),
        "name": intent.name,
        "tags": list(intent.tags),
        "artist_ids": [str(artist_id) for artist_id in intent.artist_ids],
        "platforms": [platform.value for platform in intent.platforms],
        "distribution": {
            "five": intent.distribution.five,
            "four": intent.distribution.four,
            "three": intent.distribution.three,
            "two": intent.distribution.two,
            "one": intent.distribution.one,
            "unrated": intent.distribution.unrated,
        },
        "device_hours": [
            {
                "device_id": str(dh.device_id),
                "budget_seconds": dh.budget_seconds,
                "expires_at": dh.expires_at.isoformat() if dh.expires_at else None,
            }
            for dh in intent.device_hours
        ],
        "seed": intent.seed,
    }
    if cleared_device_ids:
        payload["cleared_device_ids"] = [str(device_id) for device_id in cleared_device_ids]
    return payload


def decode_intent(payload: dict[str, Any]) -> Intent:
    dist = payload.get("distribution") or {}
    return Intent(
        id=UUID(payload["id"]),
        name=payload["name"],
        tags=list(payload.get("tags") or []),
        artist_ids=[UUID(artist_id) for artist_id in payload.get("artist_ids") or []],
        platforms=_platforms_from_payload(payload),
        distribution=_distribution_from_payload(dist),
        device_hours=[
            DeviceHours(
                device_id=UUID(dh["device_id"]),
                budget_seconds=int(dh["budget_seconds"]),
                expires_at=(
                    _as_naive_utc(datetime.fromisoformat(dh["expires_at"]))
                    if dh.get("expires_at")
                    else None
                ),
            )
            for dh in payload.get("device_hours") or []
        ],
        seed=int(payload["seed"]),
    )


def encode_mix_added(mix: Mix) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(mix.id),
        "artist_id": str(mix.artist_id),
        "platform": mix.platform.value,
        "platform_id": mix.platform_id,
        "title": mix.title,
        "url": mix.url,
        "duration_seconds": mix.duration_seconds,
        "kind": mix.kind.value,
    }
    if mix.size_bytes is not None:
        payload["size_bytes"] = int(mix.size_bytes)
    if mix.cover_url:
        payload["cover_url"] = mix.cover_url
    if mix.tracks:
        payload["tracks"] = [
            {
                "platform_id": t.platform_id,
                "title": t.title,
                "url": t.url,
                "duration_seconds": t.duration_seconds,
                **(
                    {"size_bytes": int(t.size_bytes)}
                    if t.size_bytes is not None
                    else {}
                ),
            }
            for t in mix.tracks
        ]
    return payload


def decode_mix_added(payload: dict[str, Any]) -> Mix:
    raw_size = payload.get("size_bytes")
    size_bytes = None if raw_size is None else int(raw_size)
    kind_raw = payload.get("kind", ReleaseKind.MIX.value)
    raw_cover = payload.get("cover_url")
    cover_url = str(raw_cover) if raw_cover else None
    tracks = [
        AlbumTrack(
            platform_id=str(t["platform_id"]),
            title=str(t["title"]),
            url=str(t["url"]),
            duration_seconds=int(t["duration_seconds"]),
            size_bytes=(None if t.get("size_bytes") is None else int(t["size_bytes"])),
        )
        for t in payload.get("tracks", [])
    ]
    return Mix(
        id=UUID(payload["id"]),
        artist_id=UUID(payload["artist_id"]),
        platform=Platform(payload["platform"]),
        platform_id=payload["platform_id"],
        title=payload["title"],
        url=payload["url"],
        duration_seconds=int(payload["duration_seconds"]),
        size_bytes=size_bytes,
        cover_url=cover_url,
        kind=ReleaseKind(kind_raw),
        tracks=tracks,
    )


def _distribution_from_payload(dist: dict[str, Any]) -> StarDistribution:
    if "unrated" not in dist and "rest" in dist:
        return StarDistribution(
            five=float(dist.get("five", 0.3)),
            four=float(dist.get("four", 0.2)),
            three=float(dist.get("three", 0.1)),
            two=0.0,
            one=0.0,
            unrated=float(dist["rest"]),
        )
    return StarDistribution(
        five=float(dist.get("five", 0.3)),
        four=float(dist.get("four", 0.2)),
        three=float(dist.get("three", 0.1)),
        two=float(dist.get("two", 0.05)),
        one=float(dist.get("one", 0.05)),
        unrated=float(dist.get("unrated", 0.3)),
    )


def _platforms_from_payload(payload: dict[str, Any]) -> list[Platform]:
    raw = payload.get("platforms")
    if raw is None:
        return default_intent_platforms()
    return [Platform(value) for value in raw]


def _as_naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)
