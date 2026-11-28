"""Issue 03 (peer-cache-file-share): File HEAD/GET + HTTP PeerBytes."""

from __future__ import annotations

import socket
import ssl
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from fastapi import Request
from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.device_tls import write_tls_files
from tunebag.domain import (
    AlbumTrack,
    Artist,
    Mix,
    Platform,
    ReleaseKind,
    new_id,
)
from tunebag.http_peer_bytes import HttpPeerBytes
from tunebag.peer_mtls import (
    TEST_CLIENT_CERT_HEADER,
    build_peer_server_ssl_context,
    install_uvicorn_client_cert_scope,
)
from tunebag.projection import CatalogState
from tunebag.release_cache import ReleaseCache
from tunebag.web import create_peer_app, create_ui_app


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


def _start_peer_listener(
    agent: DeviceAgent, host: str, port: int
) -> tuple[uvicorn.Server, threading.Thread]:
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


def _pair_phone_to_laptop(
    tmp_path: Path,
) -> tuple[DeviceAgent, DeviceAgent]:
    laptop = DeviceAgent("laptop", data_dir=tmp_path / "laptop")
    phone = DeviceAgent("phone", data_dir=tmp_path / "phone")
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    return laptop, phone


def test_file_head_get_mix_over_mtls(tmp_path: Path) -> None:
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

    mix = laptop.add_mix(
        title="Shared set",
        url="https://example.com/shared-set",
        duration_seconds=120,
        platform=Platform.SOUNDCLOUD,
        platform_id="shared-set-1",
        artist_name="DJ Wire",
    )
    laptop._store_local_file(mix.id, b"mix-audio-bytes")

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
            head = client.head(f"{peer_url}/api/files/{mix.id}")
            assert head.status_code == 200
            get = client.get(f"{peer_url}/api/files/{mix.id}")
            assert get.status_code == 200
            assert get.content == b"mix-audio-bytes"

            no_cert = _client_ssl(trust_pem=laptop.tls_cert_pem)
            with httpx.Client(verify=no_cert, timeout=5.0) as bare:
                denied = bare.head(f"{peer_url}/api/files/{mix.id}")
            assert denied.status_code == 401
    finally:
        _stop_server(server, thread)


def test_http_peer_bytes_mix_over_live_mtls(tmp_path: Path) -> None:
    """HttpPeerBytes.file_bytes over real Peer HTTPS mTLS (not TestClient shim)."""
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

    mix = laptop.add_mix(
        title="HTTP PeerBytes mix",
        url="https://example.com/http-peer-bytes",
        duration_seconds=90,
        platform=Platform.SOUNDCLOUD,
        platform_id="http-peer-bytes-1",
        artist_name="DJ Probe",
    )
    laptop._store_local_file(mix.id, b"peer-mix-bytes")

    phone_cert, phone_key = write_tls_files(
        tmp_path / "phone-tls",
        cert_pem=phone.tls_cert_pem,
        key_pem=phone.tls_key_pem,
    )
    server, thread = _start_peer_listener(laptop, host, port)
    try:

        def client_factory() -> httpx.Client:
            ctx = _client_ssl(
                trust_pem=laptop.tls_cert_pem,
                client_cert=phone_cert,
                client_key=phone_key,
            )
            return httpx.Client(verify=ctx, timeout=5.0, base_url=peer_url)

        http_peer = HttpPeerBytes(name="laptop", client_factory=client_factory)
        assert http_peer.file_bytes(mix.id) == b"peer-mix-bytes"
        assert http_peer.file_bytes(new_id()) is None
    finally:
        _stop_server(server, thread)


def test_complete_album_head_and_track_gets(tmp_path: Path) -> None:
    laptop, phone = _pair_phone_to_laptop(tmp_path)
    album = _seed_album_on_agent(laptop)
    payloads = [b"track-a", b"track-b"]
    laptop._cache.store_album(album, payloads)

    peer = TestClient(create_peer_app(laptop))
    headers = {TEST_CLIENT_CERT_HEADER: phone.tls_cert_pem}

    head = peer.head(f"/api/files/{album.id}", headers=headers)
    assert head.status_code == 200
    assert head.headers.get("x-tunebag-tracks") == "2"

    for index, expected in enumerate(payloads):
        got = peer.get(f"/api/files/{album.id}/tracks/{index}", headers=headers)
        assert got.status_code == 200
        assert got.content == expected

    # Mix GET must not serve Album as a single blob.
    mix_get = peer.get(f"/api/files/{album.id}", headers=headers)
    assert mix_get.status_code == 404


def test_partial_album_is_miss_for_probe_and_http_peer_bytes(tmp_path: Path) -> None:
    laptop, phone = _pair_phone_to_laptop(tmp_path)
    album = _seed_album_on_agent(laptop)
    # Strand a single track — incomplete Album must not advertise or copy.
    cache_dir = laptop._cache.blob_path(album.id)
    cache_dir.mkdir(parents=True)
    (
        cache_dir / f"01-{album.tracks[0].title}-{album.tracks[0].platform_id}.bin"
    ).write_bytes(b"only-one")
    assert not laptop._has_local_file(album.id)

    peer = TestClient(create_peer_app(laptop))
    headers = {TEST_CLIENT_CERT_HEADER: phone.tls_cert_pem}
    assert peer.head(f"/api/files/{album.id}", headers=headers).status_code == 404
    assert (
        peer.get(f"/api/files/{album.id}/tracks/0", headers=headers).status_code == 404
    )

    counts = {"head": 0, "get": 0}

    def client_factory() -> TestClient:
        return TestClient(_counting_peer_app(laptop, counts), headers=headers)

    http_peer = HttpPeerBytes(name="laptop", client_factory=client_factory)
    assert http_peer.album_track_bytes(album.id) is None
    assert counts["head"] >= 1
    assert counts["get"] == 0

    dest_catalog = CatalogState(data_dir=tmp_path / "dest")
    dest_catalog.mixes[album.id] = album
    dest_catalog.artists[album.artist_id] = laptop.catalog.artists[album.artist_id]
    dest = ReleaseCache(tmp_path / "dest", dest_catalog)
    dest.ensure_complete(
        album,
        peers=[http_peer],
        origin=None,
        still_assigned=lambda: True,
    )
    assert not dest.has(album.id)


def test_http_peer_bytes_copies_complete_album_via_ensure_complete(
    tmp_path: Path,
) -> None:
    laptop, phone = _pair_phone_to_laptop(tmp_path)
    album = _seed_album_on_agent(laptop)
    payloads = [b"track-a", b"track-b"]
    laptop._cache.store_album(album, payloads)

    headers = {TEST_CLIENT_CERT_HEADER: phone.tls_cert_pem}

    def client_factory() -> TestClient:
        return TestClient(create_peer_app(laptop), headers=headers)

    http_peer = HttpPeerBytes(name="laptop", client_factory=client_factory)
    assert http_peer.album_track_bytes(album.id) == payloads

    dest_catalog = CatalogState(data_dir=tmp_path / "dest")
    dest_catalog.mixes[album.id] = album
    dest_catalog.artists[album.artist_id] = laptop.catalog.artists[album.artist_id]
    dest = ReleaseCache(tmp_path / "dest", dest_catalog)
    dest.ensure_complete(
        album,
        peers=[http_peer],
        origin=None,
        still_assigned=lambda: True,
    )
    assert dest.album_bytes(album.id) == payloads


def test_http_peer_bytes_mix_probes_before_get(tmp_path: Path) -> None:
    laptop, phone = _pair_phone_to_laptop(tmp_path)
    mix = laptop.add_mix(
        title="Probe mix",
        url="https://example.com/probe-mix",
        duration_seconds=60,
        platform=Platform.SOUNDCLOUD,
        platform_id="probe-mix-1",
        artist_name="DJ Probe",
    )
    # Missing File: HEAD miss must not trigger GET.
    counts = {"head": 0, "get": 0}
    headers = {TEST_CLIENT_CERT_HEADER: phone.tls_cert_pem}

    def client_factory() -> TestClient:
        return TestClient(_counting_peer_app(laptop, counts), headers=headers)

    http_peer = HttpPeerBytes(name="laptop", client_factory=client_factory)
    assert http_peer.file_bytes(mix.id) is None
    assert counts["head"] >= 1
    assert counts["get"] == 0

    laptop._store_local_file(mix.id, b"now-present")
    counts["head"] = 0
    counts["get"] = 0
    assert http_peer.file_bytes(mix.id) == b"now-present"
    assert counts["head"] >= 1
    assert counts["get"] >= 1


def test_ui_listener_does_not_serve_file_bytes(tmp_path: Path) -> None:
    laptop = DeviceAgent("laptop", data_dir=tmp_path / "laptop")
    mix_id = new_id()
    ui = TestClient(create_ui_app(laptop))
    assert ui.head(f"/api/files/{mix_id}").status_code == 404
    assert ui.get(f"/api/files/{mix_id}").status_code == 404
    assert ui.get(f"/api/files/{mix_id}/tracks/0").status_code == 404


def _seed_album_on_agent(agent: DeviceAgent) -> Mix:
    artist_id = new_id()
    album_id = new_id()
    artist = Artist(
        id=artist_id,
        platform=Platform.BANDCAMP,
        platform_id="artist:album-peer",
        name="Album Artist",
        url="https://example.com/artist",
    )
    album = Mix(
        id=album_id,
        artist_id=artist_id,
        platform=Platform.BANDCAMP,
        platform_id="album-peer-1",
        title="Peer Disc",
        url="https://example.com/album",
        duration_seconds=150,
        size_bytes=30,
        kind=ReleaseKind.ALBUM,
        tracks=[
            AlbumTrack(
                platform_id="t1",
                title="One",
                url="https://example.com/t1",
                duration_seconds=60,
                size_bytes=10,
            ),
            AlbumTrack(
                platform_id="t2",
                title="Two",
                url="https://example.com/t2",
                duration_seconds=90,
                size_bytes=20,
            ),
        ],
    )
    agent.catalog.artists[artist_id] = artist
    agent.catalog.mixes[album_id] = album
    return album


def _counting_peer_app(agent: DeviceAgent, counts: dict[str, int]):
    app = create_peer_app(agent)

    @app.middleware("http")
    async def _count(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if path.startswith("/api/files/"):
            if request.method == "HEAD":
                counts["head"] += 1
            elif request.method == "GET":
                counts["get"] += 1
        return await call_next(request)

    return app
