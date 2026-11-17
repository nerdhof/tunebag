"""HTTP unpair: POST /api/peers/{device_id}/unpair."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.events import EventType
from tunebag.source import FakeSource
from tunebag.web import create_app


def _pair(tmp_path: Path) -> tuple[DeviceAgent, DeviceAgent]:
    src = FakeSource()
    laptop = DeviceAgent(
        "laptop",
        priority=1,
        source=src,
        data_dir=tmp_path / "laptop",
    )
    phone = DeviceAgent(
        "phone",
        priority=10,
        source=src,
        data_dir=tmp_path / "phone",
    )
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    laptop.wait_for_sync()
    phone.wait_for_sync()
    return laptop, phone


def test_unpair_endpoint_removes_peer_and_writes_event(tmp_path: Path) -> None:
    laptop, phone = _pair(tmp_path)
    client = TestClient(create_app(laptop))

    before = client.get("/api/peers").json()
    assert any(p["id"] == str(phone.device_id) for p in before["peers"])

    res = client.post(f"/api/peers/{phone.device_id}/unpair")
    assert res.status_code == 200
    body = res.json()
    assert all(p["id"] != str(phone.device_id) for p in body["peers"])
    assert any(e.type is EventType.DEVICE_UNPAIRED for e in laptop.export_events())


def test_unpair_endpoint_rejects_self(tmp_path: Path) -> None:
    laptop, _phone = _pair(tmp_path)
    client = TestClient(create_app(laptop))

    res = client.post(f"/api/peers/{laptop.device_id}/unpair")
    assert res.status_code == 400
    assert "cannot unpair this Device" in res.json()["detail"]
