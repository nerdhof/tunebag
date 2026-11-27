"""Issue 02 (peer-cache-file-share): mTLS Event pull hard cut."""

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
from tunebag.device_tls import write_tls_files
from tunebag.domain import Platform
from tunebag.peer_mtls import (
    build_peer_server_ssl_context,
    install_uvicorn_client_cert_scope,
)
from tunebag.web import create_peer_app


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


def _start_peer_listener(agent: DeviceAgent, host: str, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    install_uvicorn_client_cert_scope()
    cert_path, key_path = write_tls_files(
        agent.data_dir / "tls",
        cert_pem=agent.tls_cert_pem,
        key_pem=agent.tls_key_pem,
    )
    trusted = [peer.tls_cert_pem for peer in agent.peers() if peer.tls_cert_pem]
    ssl_ctx = build_peer_server_ssl_context(
        cert_file=cert_path,
        key_file=key_path,
        trusted_client_pems=trusted,
    )
    agent.bind_peer_ssl_context(ssl_ctx)
    config = uvicorn.Config(
        create_peer_app(agent),
        host=host,
        port=port,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
        ssl_context_factory=lambda _cfg, _default: ssl_ctx,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait_listening(host, port)
    return server, thread


def _stop_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=5)


def _client_ssl(
    *,
    trust_pem: str,
    client_cert: Path | None = None,
    client_key: Path | None = None,
) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cadata=trust_pem)
    ctx.check_hostname = False
    if client_cert is not None and client_key is not None:
        ctx.load_cert_chain(str(client_cert), str(client_key))
    return ctx


def test_event_pull_without_client_cert_returns_401(tmp_path: Path) -> None:
    host = "127.0.0.1"
    port = _free_port()
    peer_url = f"https://{host}:{port}"
    laptop = DeviceAgent(
        "laptop",
        data_dir=tmp_path / "laptop",
        base_url=peer_url,
    )
    server, thread = _start_peer_listener(laptop, host, port)
    try:
        ctx = _client_ssl(trust_pem=laptop.tls_cert_pem)
        with httpx.Client(verify=ctx, timeout=5.0) as client:
            response = client.post(f"{peer_url}/api/events/pull", json={"cursors": {}})
        assert response.status_code == 401
    finally:
        _stop_server(server, thread)


def test_event_pull_with_trusted_peer_cert_succeeds(tmp_path: Path) -> None:
    host = "127.0.0.1"
    port = _free_port()
    peer_url = f"https://{host}:{port}"
    laptop = DeviceAgent(
        "laptop",
        data_dir=tmp_path / "laptop",
        base_url=peer_url,
    )
    phone = DeviceAgent("phone", data_dir=tmp_path / "phone")
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())

    server, thread = _start_peer_listener(laptop, host, port)
    try:
        phone_cert, phone_key = write_tls_files(
            tmp_path / "phone-tls",
            cert_pem=phone.tls_cert_pem,
            key_pem=phone.tls_key_pem,
        )
        ctx = _client_ssl(
            trust_pem=laptop.tls_cert_pem,
            client_cert=phone_cert,
            client_key=phone_key,
        )
        with httpx.Client(verify=ctx, timeout=5.0) as client:
            response = client.post(f"{peer_url}/api/events/pull", json={"cursors": {}})
        assert response.status_code == 200
        assert "application/x-ndjson" in response.headers.get("content-type", "")
    finally:
        _stop_server(server, thread)


def test_event_pull_with_unknown_client_cert_is_rejected(tmp_path: Path) -> None:
    """Untrusted client cert fails the TLS handshake (not in Peer CA of pins)."""
    host = "127.0.0.1"
    port = _free_port()
    peer_url = f"https://{host}:{port}"
    laptop = DeviceAgent(
        "laptop",
        data_dir=tmp_path / "laptop",
        base_url=peer_url,
    )
    phone = DeviceAgent("phone", data_dir=tmp_path / "phone")
    stranger = DeviceAgent("stranger", data_dir=tmp_path / "stranger")
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())

    server, thread = _start_peer_listener(laptop, host, port)
    try:
        stranger_cert, stranger_key = write_tls_files(
            tmp_path / "stranger-tls",
            cert_pem=stranger.tls_cert_pem,
            key_pem=stranger.tls_key_pem,
        )
        ctx = _client_ssl(
            trust_pem=laptop.tls_cert_pem,
            client_cert=stranger_cert,
            client_key=stranger_key,
        )
        with httpx.Client(verify=ctx, timeout=5.0) as client:
            try:
                response = client.post(
                    f"{peer_url}/api/events/pull", json={"cursors": {}}
                )
                # If handshake somehow completed, app still hard-cuts.
                assert response.status_code == 401
            except (httpx.TransportError, ssl.SSLError):
                pass
    finally:
        _stop_server(server, thread)


def test_http_sync_uses_mtls_and_ingests_events(tmp_path: Path) -> None:
    host = "127.0.0.1"
    laptop_port = _free_port()
    phone_port = _free_port()
    laptop_url = f"https://{host}:{laptop_port}"
    phone_url = f"https://{host}:{phone_port}"
    laptop = DeviceAgent(
        "laptop",
        data_dir=tmp_path / "laptop",
        base_url=laptop_url,
    )
    phone = DeviceAgent(
        "phone",
        data_dir=tmp_path / "phone",
        base_url=phone_url,
    )
    # Pair in-proc, then meet only over HTTPS Locators (no connect()).
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    laptop.disconnect(phone)

    laptop.remember_peer_url(phone.device_id, phone_url)
    phone.remember_peer_url(laptop.device_id, laptop_url)

    mix = laptop.add_mix(
        title="Over mTLS",
        url="https://example.com/mtls-sync",
        duration_seconds=120,
        platform=Platform.SOUNDCLOUD,
        platform_id="mtls-sync-1",
        artist_name="DJ Wire",
    )

    laptop_server, laptop_thread = _start_peer_listener(laptop, host, laptop_port)
    phone_server, phone_thread = _start_peer_listener(phone, host, phone_port)
    try:
        phone.sync(fill=False)
        assert mix.id in {m.id for m in phone.mixes()}
    finally:
        _stop_server(laptop_server, laptop_thread)
        _stop_server(phone_server, phone_thread)


def test_auto_sync_nudge_hits_peer_listener_over_mtls(tmp_path: Path) -> None:
    host = "127.0.0.1"
    laptop_port = _free_port()
    phone_port = _free_port()
    laptop_url = f"https://{host}:{laptop_port}"
    phone_url = f"https://{host}:{phone_port}"
    laptop = DeviceAgent(
        "laptop",
        data_dir=tmp_path / "laptop",
        base_url=laptop_url,
    )
    phone = DeviceAgent(
        "phone",
        data_dir=tmp_path / "phone",
        base_url=phone_url,
    )
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    laptop.disconnect(phone)
    laptop.remember_peer_url(phone.device_id, phone_url)
    phone.remember_peer_url(laptop.device_id, laptop_url)

    laptop_server, laptop_thread = _start_peer_listener(laptop, host, laptop_port)
    phone_server, phone_thread = _start_peer_listener(phone, host, phone_port)
    try:
        mix = laptop.add_mix(
            title="Nudge sync",
            url="https://example.com/nudge-sync",
            duration_seconds=90,
            platform=Platform.SOUNDCLOUD,
            platform_id="nudge-sync-1",
            artist_name="DJ Nudge",
        )
        # Local write schedules auto-sync + HTTP nudge to phone's Peer listener.
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if mix.id in {m.id for m in phone.mixes()}:
                break
            time.sleep(0.1)
        assert mix.id in {m.id for m in phone.mixes()}
    finally:
        _stop_server(laptop_server, laptop_thread)
        _stop_server(phone_server, phone_thread)


def test_testclient_pull_without_cert_is_401(tmp_path: Path) -> None:
    agent = DeviceAgent("laptop", data_dir=tmp_path / "laptop")
    peer = TestClient(create_peer_app(agent))
    assert peer.post("/api/events/pull", json={"cursors": {}}).status_code == 401
