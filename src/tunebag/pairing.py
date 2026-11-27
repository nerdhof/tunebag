"""Device identity + ephemeral pairing session helpers (PIN, SAS, transcripts)."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from tunebag.durable_store import DurableStore

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from tunebag.device_tls import (
    generate_device_tls_material,
    tls_cert_fingerprint as fingerprint_from_tls_cert,
)

# Crockford base32 (no I, L, O, U) for PINs / fingerprints / SAS.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PIN_LENGTH = 8
FINGERPRINT_LENGTH = 8
SAS_LENGTH = 6
PIN_TTL_SECONDS = 120.0
PIN_MAX_ATTEMPTS = 5


@dataclass
class DeviceIdentity:
    name: str
    private_key_pem: str
    public_key_pem: str
    tls_cert_pem: str
    tls_key_pem: str


@dataclass(frozen=True)
class PersistedIdentity:
    """Local Device identity on disk: device_id + keys + Device TLS cert."""

    device_id: UUID
    private_key_pem: str
    public_key_pem: str
    tls_cert_pem: str
    tls_key_pem: str


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
    # CN uses the display name for first mint; upgrades use device_id (stable).
    tls = generate_device_tls_material(common_name=f"tunebag:{name}")
    return DeviceIdentity(
        name=name,
        private_key_pem=private_pem,
        public_key_pem=public_pem,
        tls_cert_pem=tls.cert_pem,
        tls_key_pem=tls.key_pem,
    )


def _ensure_tls_fields(
    *,
    device_id: UUID,
    private_key_pem: str,
    public_key_pem: str,
    tls_cert_pem: str | None,
    tls_key_pem: str | None,
) -> PersistedIdentity:
    """Upgrade pre-TLS identity bags by generating Device TLS material once."""
    if tls_cert_pem and tls_key_pem:
        return PersistedIdentity(
            device_id=device_id,
            private_key_pem=private_key_pem,
            public_key_pem=public_key_pem,
            tls_cert_pem=tls_cert_pem,
            tls_key_pem=tls_key_pem,
        )
    tls = generate_device_tls_material(common_name=f"tunebag:{device_id}")
    return PersistedIdentity(
        device_id=device_id,
        private_key_pem=private_key_pem,
        public_key_pem=public_key_pem,
        tls_cert_pem=tls.cert_pem,
        tls_key_pem=tls.key_pem,
    )


def load_persisted_identity(path: Path) -> PersistedIdentity | None:
    if not path.is_file():
        return None
    raw = json.loads(path.read_text())
    return _ensure_tls_fields(
        device_id=UUID(raw["device_id"]),
        private_key_pem=raw["private_key_pem"],
        public_key_pem=raw["public_key_pem"],
        tls_cert_pem=raw.get("tls_cert_pem"),
        tls_key_pem=raw.get("tls_key_pem"),
    )


def save_persisted_identity(path: Path, identity: PersistedIdentity) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "device_id": str(identity.device_id),
                "private_key_pem": identity.private_key_pem,
                "public_key_pem": identity.public_key_pem,
                "tls_cert_pem": identity.tls_cert_pem,
                "tls_key_pem": identity.tls_key_pem,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def resolve_persisted_identity(
    path: Path,
    *,
    name: str,
    identity: DeviceIdentity | None = None,
) -> tuple[DeviceIdentity, UUID]:
    """Load identity from data_dir if present; otherwise create and persist."""
    loaded = load_persisted_identity(path)
    if loaded is not None:
        # Persist upgraded TLS material when migrating a pre-TLS identity.json.
        if "tls_cert_pem" not in json.loads(path.read_text()):
            save_persisted_identity(path, loaded)
        return (
            DeviceIdentity(
                name=name,
                private_key_pem=loaded.private_key_pem,
                public_key_pem=loaded.public_key_pem,
                tls_cert_pem=loaded.tls_cert_pem,
                tls_key_pem=loaded.tls_key_pem,
            ),
            loaded.device_id,
        )
    resolved = identity or generate_identity(name)
    device_id = uuid4()
    save_persisted_identity(
        path,
        PersistedIdentity(
            device_id=device_id,
            private_key_pem=resolved.private_key_pem,
            public_key_pem=resolved.public_key_pem,
            tls_cert_pem=resolved.tls_cert_pem,
            tls_key_pem=resolved.tls_key_pem,
        ),
    )
    return resolved, device_id


def resolve_store_identity(
    store: DurableStore,
    *,
    name: str,
    identity: DeviceIdentity | None = None,
) -> tuple[DeviceIdentity, UUID]:
    """Load identity from a DurableStore if present; otherwise create and persist."""
    loaded = store.load_identity()
    if loaded is not None:
        # Upgrade bags that predate Device TLS cert material.
        if store.get_meta("tls_cert_pem") is None:
            store.save_identity(loaded)
        return (
            DeviceIdentity(
                name=name,
                private_key_pem=loaded.private_key_pem,
                public_key_pem=loaded.public_key_pem,
                tls_cert_pem=loaded.tls_cert_pem,
                tls_key_pem=loaded.tls_key_pem,
            ),
            loaded.device_id,
        )
    resolved = identity or generate_identity(name)
    device_id = uuid4()
    store.save_identity(
        PersistedIdentity(
            device_id=device_id,
            private_key_pem=resolved.private_key_pem,
            public_key_pem=resolved.public_key_pem,
            tls_cert_pem=resolved.tls_cert_pem,
            tls_key_pem=resolved.tls_key_pem,
        )
    )
    return resolved, device_id


def load_locator_hints(path: Path) -> dict[UUID, str]:
    """Load last-known Locator hints (device_id → URL). Missing file ⇒ empty."""
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        return {}
    hints: dict[UUID, str] = {}
    for device_id, locator in raw.items():
        if not isinstance(locator, str) or not locator:
            continue
        hints[UUID(device_id)] = locator
    return hints


def save_locator_hints(path: Path, hints: dict[UUID, str]) -> None:
    """Persist last-known Locator hints (non-authoritative; never grant trust)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {str(device_id): locator for device_id, locator in sorted(hints.items())}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def public_key_raw_bytes(public_key_pem: str) -> bytes:
    """32-byte raw Ed25519 public key (not PEM ASCII)."""
    key = serialization.load_pem_public_key(public_key_pem.encode())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("expected Ed25519 public key")
    return key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _crockford_from_bytes(data: bytes, length: int) -> str:
    """Encode digest bytes as Crockford base32 and truncate to length."""
    bits = 0
    value = 0
    out: list[str] = []
    for byte in data:
        value = (value << 8) | byte
        bits += 8
        while bits >= 5 and len(out) < length:
            bits -= 5
            out.append(_CROCKFORD[(value >> bits) & 31])
    while len(out) < length:
        out.append(_CROCKFORD[0])
    return "".join(out[:length])


def fingerprint_from_key(public_key_pem: str, length: int = FINGERPRINT_LENGTH) -> str:
    """Stable discovery label from raw public key material (not a pairing secret)."""
    digest = hashlib.sha256(public_key_raw_bytes(public_key_pem)).digest()
    return _crockford_from_bytes(digest, length)


# Back-compat alias used by older call sites / tests during migration.
def short_code_from_key(public_key_pem: str, length: int = FINGERPRINT_LENGTH) -> str:
    return fingerprint_from_key(public_key_pem, length=length)


def generate_pairing_pin(length: int = PIN_LENGTH) -> str:
    """Cryptographically random one-time pairing PIN."""
    return "".join(secrets.choice(_CROCKFORD) for _ in range(length))


def normalize_pin(pin: str) -> str:
    return pin.strip().upper().replace("-", "").replace(" ", "")


def pins_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(normalize_pin(a), normalize_pin(b))


def pairing_payload(
    name: str,
    public_key_pem: str,
    *,
    device_id: str | None = None,
    priority: int | None = None,
    fingerprint: str | None = None,
    short_code: str | None = None,
    url: str | None = None,
    tls_cert_pem: str | None = None,
    tls_cert_fingerprint: str | None = None,
) -> dict:
    fp = fingerprint or short_code or fingerprint_from_key(public_key_pem)
    payload = {
        "v": 1,
        "name": name,
        "public_key_pem": public_key_pem,
        "fingerprint": fp,
        # Alias for older UI / discovery readers.
        "short_code": fp,
    }
    if device_id is not None:
        payload["device_id"] = device_id
    if priority is not None:
        payload["priority"] = priority
    if url is not None:
        payload["url"] = url
    if tls_cert_pem is not None:
        payload["tls_cert_pem"] = tls_cert_pem
        payload["tls_cert_fingerprint"] = (
            tls_cert_fingerprint or fingerprint_from_tls_cert(tls_cert_pem)
        )
    return payload


def ephemeral_pair_offer(
    *,
    url: str,
    session_id: str,
    pin: str,
) -> dict:
    """QR / paste payload for an active pairing session (not durable identity trust)."""
    return {
        "v": 2,
        "url": url,
        "session_id": session_id,
        "pin": normalize_pin(pin),
    }


def payload_to_qr_text(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def join_transcript(
    *,
    session_id: str,
    pin: str,
    host_public_key_pem: str,
    guest_public_key_pem: str,
    guest_nonce: str,
    host_tls_cert_fingerprint: str | None = None,
    guest_tls_cert_fingerprint: str | None = None,
) -> bytes:
    host_raw = public_key_raw_bytes(host_public_key_pem)
    guest_raw = public_key_raw_bytes(guest_public_key_pem)
    parts = [
        b"tunebag-pair-join-v1",
        session_id.encode("utf-8"),
        normalize_pin(pin).encode("ascii"),
        host_raw,
        guest_raw,
        guest_nonce.encode("utf-8"),
    ]
    # TOFU Device TLS pins into the signed join when both sides present them.
    if host_tls_cert_fingerprint and guest_tls_cert_fingerprint:
        parts.extend(
            [
                host_tls_cert_fingerprint.encode("ascii"),
                guest_tls_cert_fingerprint.encode("ascii"),
            ]
        )
    return b"|".join(parts)


def confirm_transcript(
    *,
    session_id: str,
    host_public_key_pem: str,
    guest_public_key_pem: str,
    role: str,
    host_tls_cert_fingerprint: str | None = None,
    guest_tls_cert_fingerprint: str | None = None,
) -> bytes:
    host_raw = public_key_raw_bytes(host_public_key_pem)
    guest_raw = public_key_raw_bytes(guest_public_key_pem)
    parts = [
        b"tunebag-pair-confirm-v1",
        session_id.encode("utf-8"),
        host_raw,
        guest_raw,
        role.encode("ascii"),
    ]
    if host_tls_cert_fingerprint and guest_tls_cert_fingerprint:
        parts.extend(
            [
                host_tls_cert_fingerprint.encode("ascii"),
                guest_tls_cert_fingerprint.encode("ascii"),
            ]
        )
    return b"|".join(parts)


def sas_for_session(
    *,
    session_id: str,
    host_public_key_pem: str,
    guest_public_key_pem: str,
    length: int = SAS_LENGTH,
) -> str:
    """Short authentication string both humans compare during Confirm."""
    host_raw = public_key_raw_bytes(host_public_key_pem)
    guest_raw = public_key_raw_bytes(guest_public_key_pem)
    first, second = sorted([host_raw, guest_raw])
    digest = hashlib.sha256(
        b"tunebag-sas-v1|" + session_id.encode("utf-8") + b"|" + first + b"|" + second
    ).digest()
    return _crockford_from_bytes(digest, length)
