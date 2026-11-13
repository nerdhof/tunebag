"""Device pairing via QR (device name + public key) with short-code fallback."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


@dataclass
class DeviceIdentity:
    name: str
    private_key_pem: str
    public_key_pem: str


def generate_identity(name: str) -> DeviceIdentity:
    private_key = ed25519.Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return DeviceIdentity(name=name, private_key_pem=private_pem, public_key_pem=public_pem)


def pairing_payload(
    name: str,
    public_key_pem: str,
    *,
    device_id: str | None = None,
    priority: int | None = None,
    short_code: str | None = None,
    url: str | None = None,
) -> dict:
    payload = {
        "v": 1,
        "name": name,
        "public_key_pem": public_key_pem,
        "short_code": short_code or short_code_from_key(public_key_pem),
    }
    if device_id is not None:
        payload["device_id"] = device_id
    if priority is not None:
        payload["priority"] = priority
    if url is not None:
        payload["url"] = url
    return payload


def short_code_from_key(public_key_pem: str, length: int = 6) -> str:
    digest = base64.b32encode(public_key_pem.encode()).decode("ascii")
    # Stable short code derived from the key so both sides can verify.
    return digest.replace("=", "")[:length].upper()


def payload_to_qr_text(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)
