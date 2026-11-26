"""HTTP create/fill return before background fill finishes; UI can refresh lists."""

from __future__ import annotations

import threading
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform, Stars
from tunebag.source import FakeSource
from tunebag.web import create_app


class GatedSource:
    """Blocks fetch_bytes until ``gate`` is set so the HTTP handler can return first."""

    def __init__(self, inner: FakeSource, gate: threading.Event) -> None:
        self._inner = inner
        self._gate = gate

    def list_uploads(self, artist_url: str):
        return self._inner.list_uploads(artist_url)

    def fetch_bytes(self, source_url: str, *, on_progress=None) -> bytes:
        assert self._gate.wait(timeout=5.0), "fill fetch timed out waiting for gate"
        return self._inner.fetch_bytes(source_url, on_progress=on_progress)


def test_create_intent_api_returns_before_fill_completes(tmp_path: Path) -> None:
    gate = threading.Event()
    inner = FakeSource()
    source = GatedSource(inner, gate)
    agent = DeviceAgent(
        "laptop",
        priority=1,
        source=source,  # type: ignore[arg-type]
        data_dir=tmp_path / "laptop",
    )
    url = "https://example.com/a"
    inner.bytes_by_url[url] = b"audio:a"
    mix = agent.add_mix(
        title="Set A",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="a",
        artist_name="DJ Example",
    )
    agent.rate_mix(mix.id, Stars.FIVE)

    client = TestClient(create_app(agent))
    res = client.post(
        "/api/intents",
        json={
            "name": "Fill",
            "seed": 1,
            "device_hours": [
                {"device_id": str(agent.device_id), "budget_seconds": 3600},
            ],
        },
    )

    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["intent"]["name"] == "Fill"
    assert body["fill_in_progress"] is True
    assert body["files"] == 0

    intents = client.get("/api/intents").json()["intents"]
    assert any(intent["name"] == "Fill" for intent in intents)
    assert client.get("/api/files").json()["files"] == []

    gate.set()
    agent.wait_for_fill(timeout=5.0)

    files = client.get("/api/files").json()["files"]
    assert len(files) == 1
    assert files[0]["id"] == str(mix.id)
    messages = [entry.message for entry in agent.activity()]
    assert any(m.startswith("fill caches end") for m in messages)


def test_fill_api_starts_background_fill(tmp_path: Path) -> None:
    gate = threading.Event()
    inner = FakeSource()
    source = GatedSource(inner, gate)
    agent = DeviceAgent(
        "laptop",
        priority=1,
        source=source,  # type: ignore[arg-type]
        data_dir=tmp_path / "laptop",
    )
    url = "https://example.com/b"
    inner.bytes_by_url[url] = b"audio:b"
    mix = agent.add_mix(
        title="Set B",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="b",
        artist_name="DJ Example",
    )
    agent.rate_mix(mix.id, Stars.FIVE)
    agent.create_intent(
        "Fill",
        seed=1,
        device_hours=[(agent.device_id, 3600)],
    )

    client = TestClient(create_app(agent))
    res = client.post("/api/fill")
    assert res.status_code == 200
    assert res.json()["fill_in_progress"] is True
    assert res.json()["files"] == 0

    gate.set()
    agent.wait_for_fill(timeout=5.0)
    assert [f["id"] for f in client.get("/api/files").json()["files"]] == [str(mix.id)]


def test_request_fill_coalesces_while_in_progress(tmp_path: Path) -> None:
    gate = threading.Event()
    inner = FakeSource()
    source = GatedSource(inner, gate)
    agent = DeviceAgent(
        "laptop",
        priority=1,
        source=source,  # type: ignore[arg-type]
        data_dir=tmp_path / "laptop",
    )
    url = "https://example.com/c"
    inner.bytes_by_url[url] = b"audio:c"
    mix = agent.add_mix(
        title="Set C",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="c",
        artist_name="DJ Example",
    )
    agent.rate_mix(mix.id, Stars.FIVE)
    # create_intent kicks Catalog maintenance request_fill (blocked on gate).
    agent.create_intent(
        "Fill",
        seed=1,
        device_hours=[(agent.device_id, 3600)],
    )

    assert agent.fill_in_progress is True
    assert agent.request_fill() is False
    assert agent.fill_in_progress is True

    gate.set()
    agent.wait_for_fill(timeout=5.0)
    assert [m.id for m in agent.files()] == [mix.id]


def test_refresh_sequence_api_rerolls_seed(tmp_path: Path) -> None:
    agent = DeviceAgent("laptop", priority=1, data_dir=tmp_path / "laptop")
    for i in range(6):
        mix = agent.add_mix(
            title=f"Set {i}",
            url=f"https://example.com/r{i}",
            duration_seconds=3600,
            platform=Platform.SOUNDCLOUD,
            platform_id=f"r{i}",
            artist_name="DJ Example",
        )
        agent.rate_mix(mix.id, Stars.FOUR)
        agent.tag_mix(mix.id, ["roll"])

    intent = agent.create_intent(
        "Roll",
        tags=["roll"],
        seed=7,
        device_hours=[(agent.device_id, 3 * 3600)],
    )
    before = agent.sequence(intent.id)
    assert before is not None
    assert len(before.entries) == 3

    client = TestClient(create_app(agent))
    res = client.post(f"/api/intents/{intent.id}/refresh-sequence")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["intent"]["id"] == str(intent.id)
    assert body["intent"]["seed"] != 7

    after = client.get(f"/api/intents/{intent.id}/sequence").json()
    assert len(after["entries"]) == 3
    assert after["assignments"]
    assert after["assignments"][0]["mix_ids"] == [e["mix_id"] for e in after["entries"]]
    for entry in after["entries"]:
        assert "has_cover" in entry
        assert isinstance(entry["has_cover"], bool)
        assert entry["cache_status"] in ("cached", "loading", "pending", "absent")
        assert "rejected" in entry
        assert "soft_rejected" in entry


def test_refresh_sequence_api_unknown_intent(tmp_path: Path) -> None:
    agent = DeviceAgent("laptop", priority=1, data_dir=tmp_path / "laptop")
    client = TestClient(create_app(agent))
    res = client.post(f"/api/intents/{uuid4()}/refresh-sequence")
    assert res.status_code == 404
