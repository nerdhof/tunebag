"""Issue 01 (peer-cache-file-share): Device TLS cert + split listeners."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.web import create_app, create_peer_app


def test_device_tls_cert_survives_restart(tmp_path: Path) -> None:
    data_dir = tmp_path / "laptop"
    first = DeviceAgent("laptop", data_dir=data_dir)
    assert first.tls_cert_pem
    assert first.tls_key_pem
    assert first.tls_cert_fingerprint()
    cert = first.tls_cert_pem
    key = first.tls_key_pem
    fp = first.tls_cert_fingerprint()

    second = DeviceAgent("laptop", data_dir=data_dir)
    assert second.tls_cert_pem == cert
    assert second.tls_key_pem == key
    assert second.tls_cert_fingerprint() == fp
    # Event-signing keypair stays distinct from Device TLS material.
    assert second.public_key_pem != second.tls_cert_pem
    assert "BEGIN CERTIFICATE" in second.tls_cert_pem
    assert "BEGIN PRIVATE KEY" in second.tls_key_pem


def test_pairing_payload_exposes_tls_cert_for_tofu(tmp_path: Path) -> None:
    agent = DeviceAgent("laptop", data_dir=tmp_path / "laptop")
    payload = agent.pairing_payload()
    assert payload["tls_cert_pem"] == agent.tls_cert_pem
    assert payload["tls_cert_fingerprint"] == agent.tls_cert_fingerprint()


def test_pairing_tofu_pins_peer_tls_fingerprint(tmp_path: Path) -> None:
    laptop = DeviceAgent("laptop", data_dir=tmp_path / "laptop")
    phone = DeviceAgent("phone", data_dir=tmp_path / "phone")
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())

    guest_view = next(p for p in phone.peers() if p.id == laptop.device_id)
    assert guest_view.tls_cert_fingerprint == laptop.tls_cert_fingerprint()
    host_view = next(p for p in laptop.peers() if p.id == phone.device_id)
    assert host_view.tls_cert_fingerprint == phone.tls_cert_fingerprint()


def test_wrong_tls_cert_rejected_after_trust(tmp_path: Path) -> None:
    laptop = DeviceAgent("laptop", data_dir=tmp_path / "laptop")
    phone = DeviceAgent("phone", data_dir=tmp_path / "phone")
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())

    impostor_tls = DeviceAgent("impostor", data_dir=tmp_path / "impostor")
    assert not phone.accepts_peer_tls_cert(
        laptop.device_id, impostor_tls.tls_cert_pem
    )
    assert phone.accepts_peer_tls_cert(laptop.device_id, laptop.tls_cert_pem)
    # Re-trust attempt with a rotated TLS cert for the same Identity fails.
    rotated = dict(laptop.pairing_payload())
    rotated["tls_cert_pem"] = impostor_tls.tls_cert_pem
    rotated["tls_cert_fingerprint"] = impostor_tls.tls_cert_fingerprint()
    try:
        phone._trust_payload(rotated)
        raised = False
    except ValueError as exc:
        raised = True
        assert "re-pair" in str(exc).lower() or "tls" in str(exc).lower()
    assert raised


def test_ui_app_does_not_serve_event_pull(tmp_path: Path) -> None:
    agent = DeviceAgent("laptop", data_dir=tmp_path / "laptop")
    ui = TestClient(create_app(agent))
    peer = TestClient(create_peer_app(agent))

    assert ui.get("/api/health").status_code == 200
    assert ui.get("/").status_code == 200
    # Cleartext UI must not expose Catalog pull.
    assert ui.post("/api/events/pull", json={"cursors": {}}).status_code == 404
    assert ui.post("/api/prove", json={"nonce": "n"}).status_code == 404

    assert peer.post("/api/events/pull", json={"cursors": {}}).status_code == 200
    assert peer.post("/api/prove", json={"nonce": "n"}).status_code == 200
    assert "signature" in peer.post("/api/prove", json={"nonce": "n"}).json()


def test_ui_loads_without_client_cert(tmp_path: Path) -> None:
    """Companion UI listener is cleartext — no client certificate required."""
    agent = DeviceAgent(
        "laptop",
        data_dir=tmp_path / "laptop",
        base_url="https://127.0.0.1:9443",
        ui_url="http://127.0.0.1:8787",
    )
    client = TestClient(create_app(agent))
    home = client.get("/")
    assert home.status_code == 200
    assert "text/html" in home.headers.get("content-type", "")
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True
    # Locators advertise the Peer HTTPS URL, not the UI listener.
    assert agent.pairing_payload()["url"] == "https://127.0.0.1:9443"
