"""Stale / unknown device hours must not silently yield fill → 0 cached."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.source import FakeSource
from tunebag.web import create_app


def _pair(tmp_path: Path) -> tuple[DeviceAgent, DeviceAgent, FakeSource]:
    source = FakeSource()
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=source,
        data_dir=tmp_path / "laptop",
    )
    phone = DeviceAgent(
        "phone",
        priority=10,
        source=source,
        data_dir=tmp_path / "phone",
    )
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    return laptop, phone, source


def _add_mix(agent: DeviceAgent, source: FakeSource) -> None:
    url = "https://example.com/stale-hours"
    source.bytes_by_url[url] = b"audio:stale"
    mix = agent.add_mix(
        title="Stale Hours Mix",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="stale-hours",
        artist_name="DJ Example",
    )
    agent.rate_mix(mix.id, Stars.FIVE)


def test_create_intent_rejects_unknown_device_hours(tmp_path: Path) -> None:
    agent = DeviceAgent("laptop", data_dir=tmp_path / "laptop")
    with pytest.raises(ValueError, match="unknown device_id"):
        agent.create_intent(
            "Bad hours",
            seed=1,
            device_hours=[(uuid4(), 3600)],
        )


def test_update_intent_rejects_unknown_device_hours(tmp_path: Path) -> None:
    agent = DeviceAgent("laptop", data_dir=tmp_path / "laptop")
    intent = agent.create_intent(
        "Ok",
        seed=1,
        device_hours=[(agent.device_id, 3600)],
    )
    with pytest.raises(ValueError, match="unknown device_id"):
        agent.update_intent(
            intent.id,
            device_hours=[(uuid4(), 7200)],
        )


def test_set_device_hours_rejects_unknown_device(tmp_path: Path) -> None:
    agent = DeviceAgent("laptop", data_dir=tmp_path / "laptop")
    intent = agent.create_intent(
        "Ok",
        seed=1,
        device_hours=[(agent.device_id, 3600)],
    )
    with pytest.raises(ValueError, match="unknown device_id"):
        agent.set_device_hours(intent.id, uuid4(), 7200)


def test_create_intent_api_rejects_unknown_device_hours(tmp_path: Path) -> None:
    agent = DeviceAgent("laptop", data_dir=tmp_path / "laptop")
    client = TestClient(create_app(agent))
    res = client.post(
        "/api/intents",
        json={
            "name": "Bad hours",
            "device_hours": [
                {"device_id": str(uuid4()), "budget_seconds": 3600},
            ],
        },
    )
    assert res.status_code == 400
    assert "unknown device_id" in res.json()["detail"]


def test_fill_skips_when_hours_only_on_peer(tmp_path: Path) -> None:
    """Local fill finds no assignment when hours are bound only to a peer."""
    laptop, phone, source = _pair(tmp_path)
    _add_mix(laptop, source)
    intent = laptop.create_intent(
        "Phone only",
        seed=1,
        device_hours=[(phone.device_id, 3600)],
    )
    phone.sync()

    cached = laptop.fill_caches()

    assert cached == 0
    assert laptop.assignment(intent.id) is None
    messages = [entry.message for entry in laptop.activity()]
    assert any(
        m.startswith("fill skip: Phone only has hours for") for m in messages
    )
    assert any(m == "fill caches end · 0 cached" for m in messages)
