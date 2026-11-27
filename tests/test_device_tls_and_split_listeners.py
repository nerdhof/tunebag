"""Issue 01 (peer-cache-file-share): Device TLS cert + split listeners."""

from __future__ import annotations

import socket
import ssl
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.device_tls import tls_cert_fingerprint, write_tls_files
from tunebag.web import create_app, create_peer_app, create_ui_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_listening(host: str, port: int, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"{host}:{port} did not accept connections")


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


def test_peer_https_listener_serves_pairing_with_device_tls(tmp_path: Path) -> None:
    """Live Peer HTTPS listener presents the Device TLS cert (issue 01 wire seam)."""
    host = "127.0.0.1"
    peer_port = _free_port()
    ui_port = _free_port()
    peer_url = f"https://{host}:{peer_port}"
    ui_url = f"http://{host}:{ui_port}"
    agent = DeviceAgent(
        "laptop",
        data_dir=tmp_path / "laptop",
        base_url=peer_url,
        ui_url=ui_url,
    )
    cert_path, key_path = write_tls_files(
        agent.data_dir / "tls",
        cert_pem=agent.tls_cert_pem,
        key_pem=agent.tls_key_pem,
    )

    peer_config = uvicorn.Config(
        create_peer_app(agent),
        host=host,
        port=peer_port,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
        ssl_cert_reqs=int(ssl.CERT_OPTIONAL),
        log_level="warning",
    )
    ui_config = uvicorn.Config(
        create_ui_app(agent),
        host=host,
        port=ui_port,
        log_level="warning",
    )
    peer_server = uvicorn.Server(peer_config)
    ui_server = uvicorn.Server(ui_config)
    peer_thread = threading.Thread(target=peer_server.run, daemon=True)
    ui_thread = threading.Thread(target=ui_server.run, daemon=True)
    peer_thread.start()
    ui_thread.start()
    try:
        _wait_listening(host, peer_port)
        _wait_listening(host, ui_port)

        # UI: cleartext, no client cert.
        with httpx.Client(timeout=5.0) as ui_client:
            ui_health = ui_client.get(f"{ui_url}/api/health")
            assert ui_health.status_code == 200
            assert ui_health.json()["ok"] is True
            assert ui_client.post(
                f"{ui_url}/api/events/pull", json={"cursors": {}}
            ).status_code == 404

        # Peer: HTTPS with the Device TLS cert; client trusts that cert PEM.
        ctx = ssl.create_default_context(cadata=agent.tls_cert_pem)
        ctx.check_hostname = False
        with httpx.Client(verify=ctx, timeout=5.0) as peer_client:
            pairing = peer_client.get(f"{peer_url}/api/pairing")
            assert pairing.status_code == 200
            body = pairing.json()
            assert body["url"] == peer_url
            assert body["tls_cert_fingerprint"] == agent.tls_cert_fingerprint()
            assert tls_cert_fingerprint(body["tls_cert_pem"]) == agent.tls_cert_fingerprint()
            prove = peer_client.post(f"{peer_url}/api/prove", json={"nonce": "wire"})
            assert prove.status_code == 200
            assert "signature" in prove.json()
    finally:
        peer_server.should_exit = True
        ui_server.should_exit = True
        peer_thread.join(timeout=5)
        ui_thread.join(timeout=5)
