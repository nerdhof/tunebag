"""mTLS Peer meet: client-cert extraction, pin check, and httpx clients."""

from __future__ import annotations

import ssl
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from fastapi import HTTPException, Request

from tunebag.device_tls import tls_cert_fingerprint

# TestClient has no TLS; tests may present a PEM via this header.
TEST_CLIENT_CERT_HEADER = "x-tunebag-client-cert"

_UVICORN_PATCHED = False


def peer_cert_pem_from_transport(transport: Any) -> str | None:
    """DER→PEM for the TLS peer cert, even when OpenSSL did not validate it."""
    if transport is None:
        return None
    get_extra = getattr(transport, "get_extra_info", None)
    if not callable(get_extra):
        return None
    ssl_object = get_extra("ssl_object")
    if ssl_object is None:
        return None
    getpeercert = getattr(ssl_object, "getpeercert", None)
    if not callable(getpeercert):
        return None
    der = getpeercert(binary_form=True)
    if not der:
        return None
    cert = x509.load_der_x509_certificate(der)
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def client_cert_pem_from_scope(scope: Mapping[str, Any]) -> str | None:
    """Read client cert PEM from ASGI TLS extension (uvicorn patch or tests)."""
    extensions = scope.get("extensions") or {}
    tls = extensions.get("tls") or {}
    chain = tls.get("client_cert_chain") or ()
    for item in chain:
        if isinstance(item, str) and "BEGIN CERTIFICATE" in item:
            return item
        if isinstance(item, (bytes, bytearray)):
            text = bytes(item).decode()
            if "BEGIN CERTIFICATE" in text:
                return text
    return None


def client_cert_pem_from_request(request: Request) -> str | None:
    """Client cert from TLS scope, else TestClient header (ASGI-only)."""
    pem = client_cert_pem_from_scope(request.scope)
    if pem:
        return pem
    # Live HTTPS must not accept a spoofable header — only plain ASGI TestClient.
    if request.scope.get("scheme") == "https":
        return None
    header = request.headers.get(TEST_CLIENT_CERT_HEADER)
    return header if header and "BEGIN CERTIFICATE" in header else None


def require_trusted_peer_cert(request: Request, agent: Any) -> str:
    """Return pinned fingerprint when the client cert matches a trusted Peer.

    Raises HTTP 401 when the cert is missing or not pinned.
    """
    pem = client_cert_pem_from_request(request)
    if not pem:
        raise HTTPException(status_code=401, detail="client certificate required")
    try:
        fingerprint = tls_cert_fingerprint(pem)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid client certificate") from exc
    for peer in agent.peers():
        if peer.tls_cert_fingerprint and peer.tls_cert_fingerprint == fingerprint:
            return fingerprint
    raise HTTPException(status_code=401, detail="untrusted client certificate")


def install_uvicorn_client_cert_scope() -> None:
    """Expose client cert PEM on ``scope['extensions']['tls']`` for Peer auth."""
    global _UVICORN_PATCHED
    if _UVICORN_PATCHED:
        return
    _patch_httptools()
    _patch_h11()
    _UVICORN_PATCHED = True


def _set_tls_extension(scope: dict[str, Any], transport: Any) -> None:
    pem = peer_cert_pem_from_transport(transport)
    extensions = scope.setdefault("extensions", {})
    extensions["tls"] = {
        "spec_version": "0.3",
        "client_cert_chain": [pem] if pem else [],
    }


def _patch_httptools() -> None:
    try:
        from uvicorn.protocols.http.httptools_impl import HttpToolsProtocol
    except ImportError:  # pragma: no cover
        return
    if getattr(HttpToolsProtocol, "_tunebag_mtls_patched", False):
        return
    original = HttpToolsProtocol.on_headers_complete

    def on_headers_complete(self: Any) -> None:
        original(self)
        if self.scope is not None:
            _set_tls_extension(self.scope, self.transport)

    HttpToolsProtocol.on_headers_complete = on_headers_complete  # type: ignore[method-assign]
    HttpToolsProtocol._tunebag_mtls_patched = True


def _patch_h11() -> None:
    try:
        from uvicorn.protocols.http.h11_impl import H11Protocol
    except ImportError:  # pragma: no cover
        return
    if getattr(H11Protocol, "_tunebag_mtls_patched", False):
        return
    # h11 builds scope inside data_received; wrap connection cycle start via
    # the existing handle_events path by patching after scope assignment in
    # the same place httptools uses — patch ``handle_events`` is fragile, so
    # wrap ``H11Protocol.handle_events`` lightly.
    original_handle = H11Protocol.handle_events

    def handle_events(self: Any) -> None:
        original_handle(self)
        scope = getattr(self, "scope", None)
        if isinstance(scope, dict) and scope.get("type") == "http":
            tls = (scope.get("extensions") or {}).get("tls")
            if tls is None:
                _set_tls_extension(scope, self.transport)

    H11Protocol.handle_events = handle_events  # type: ignore[method-assign]
    H11Protocol._tunebag_mtls_patched = True


def ssl_context_for_peer_pin(trust_pem: str) -> ssl.SSLContext:
    """Client SSLContext that trusts exactly one peer Device TLS cert."""
    ctx = ssl.create_default_context(cadata=trust_pem)
    ctx.check_hostname = False
    # Present client cert via the context (httpx ``cert=`` is deprecated).
    return ctx


def build_peer_server_ssl_context(
    *,
    cert_file: Path | str,
    key_file: Path | str,
    trusted_client_pems: list[str] | None = None,
) -> ssl.SSLContext:
    """Peer listener context: CERT_OPTIONAL + CA of pinned Peer Device TLS certs.

    Missing client cert still completes the handshake (pairing TOFU). A presented
    cert must chain to a pinned PEM or OpenSSL aborts. App-level pin check then
    returns 401 when the cert is absent on protected routes.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert_file), str(key_file))
    ctx.verify_mode = ssl.CERT_OPTIONAL
    ctx.check_hostname = False
    for pem in trusted_client_pems or []:
        if pem and "BEGIN CERTIFICATE" in pem:
            ctx.load_verify_locations(cadata=pem)
    return ctx


def add_trusted_client_ca(ctx: ssl.SSLContext, cert_pem: str) -> None:
    """Extend a live Peer listener context after pairing TOFU."""
    if cert_pem and "BEGIN CERTIFICATE" in cert_pem:
        ctx.load_verify_locations(cadata=cert_pem)


def mtls_httpx_client(
    *,
    trust_pem: str,
    client_cert: Path | str,
    client_key: Path | str,
    timeout: float,
) -> httpx.Client:
    """httpx client: verify peer pin + present this Device's TLS cert."""
    ctx = ssl_context_for_peer_pin(trust_pem)
    ctx.load_cert_chain(str(client_cert), str(client_key))
    return httpx.Client(verify=ctx, timeout=timeout)


def tofu_httpx_client(*, timeout: float) -> httpx.Client:
    """Pairing TOFU window: HTTPS without pin (cert pinned after pair)."""
    return httpx.Client(verify=False, timeout=timeout)
