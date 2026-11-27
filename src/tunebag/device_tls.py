"""Device TLS cert material (distinct from Event-signing keys)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


@dataclass(frozen=True)
class DeviceTlsMaterial:
    """Self-signed Device TLS cert + private key (PEM)."""

    cert_pem: str
    key_pem: str


def generate_device_tls_material(*, common_name: str) -> DeviceTlsMaterial:
    """Create a long-lived self-signed cert for Peer listener mTLS."""
    key = ec.generate_private_key(ec.SECP256R1())
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, common_name[:64] or "tunebag"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "tunebag"),
        ]
    )
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                key_agreement=False,
                content_commitment=False,
                data_encipherment=False,
                key_cert_sign=True,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage(
                [
                    x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
                    x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return DeviceTlsMaterial(cert_pem=cert_pem, key_pem=key_pem)


def tls_cert_fingerprint(cert_pem: str) -> str:
    """Stable pin: lowercase hex SHA-256 of the DER-encoded certificate."""
    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    digest = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).digest()
    return digest.hex()


def write_tls_files(
    directory: Path, *, cert_pem: str, key_pem: str
) -> tuple[Path, Path]:
    """Write cert/key PEMs under directory; return (cert_path, key_path)."""
    directory.mkdir(parents=True, exist_ok=True)
    cert_path = directory / "device_tls_cert.pem"
    key_path = directory / "device_tls_key.pem"
    cert_path.write_text(cert_pem)
    key_path.write_text(key_pem)
    return cert_path, key_path
