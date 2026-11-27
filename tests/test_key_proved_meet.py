"""Issue 04 (durable-sync): key-proved meet before Catalog sync via DeviceAgent."""

from __future__ import annotations

from pathlib import Path

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform
from tunebag.pairing import PersistedIdentity, generate_identity, save_persisted_identity
from tunebag.source import FakeSource


def _pair(tmp_path: Path) -> tuple[DeviceAgent, DeviceAgent, FakeSource]:
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
    return laptop, phone, src


def _impostor_claiming(victim: DeviceAgent, *, data_dir: Path, source: FakeSource) -> DeviceAgent:
    """Locator that claims victim's Identity but cannot sign with the private key."""
    attacker_keys = generate_identity("impostor")
    data_dir.mkdir(parents=True, exist_ok=True)
    save_persisted_identity(
        data_dir / "identity.json",
        PersistedIdentity(
            device_id=victim.device_id,
            private_key_pem=attacker_keys.private_key_pem,
            public_key_pem=victim.public_key_pem,
            tls_cert_pem=attacker_keys.tls_cert_pem,
            tls_key_pem=attacker_keys.tls_key_pem,
        ),
    )
    return DeviceAgent(
        victim.name,
        priority=victim.device.priority,
        source=source,
        data_dir=data_dir,
    )


def test_after_proof_catalog_sync_proceeds_for_live_session(tmp_path: Path) -> None:
    laptop, phone, src = _pair(tmp_path)
    url = "https://example.com/proved-sync"
    src.bytes_by_url[url] = b"audio:proved"
    mix = laptop.add_mix(
        title="Proved sync set",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="proved-sync-1",
        artist_name="DJ Example",
    )
    laptop.sync(fill=False)
    phone.sync(fill=False)

    assert mix.id in {m.id for m in phone.mixes()}
    assert next(m for m in phone.mixes() if m.id == mix.id).title == "Proved sync set"


def test_impostor_locator_claiming_trusted_key_does_not_sync_catalog(tmp_path: Path) -> None:
    laptop, phone, src = _pair(tmp_path)
    laptop.disconnect(phone)

    impostor = _impostor_claiming(
        laptop,
        data_dir=tmp_path / "impostor",
        source=src,
    )
    url = "https://example.com/impostor-only"
    src.bytes_by_url[url] = b"audio:impostor"
    evil_mix = impostor.add_mix(
        title="Impostor only",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="impostor-1",
        artist_name="Evil DJ",
    )

    phone.connect(impostor)
    phone.sync(fill=False)
    impostor.sync(fill=False)

    assert evil_mix.id not in {m.id for m in phone.mixes()}
    assert [p.name for p in phone.peers()] == ["laptop"]


def test_after_disconnect_new_meet_requires_proof_again(tmp_path: Path) -> None:
    laptop, phone, src = _pair(tmp_path)
    # Establish a proved live session, then drop reachability.
    laptop.sync(fill=False)
    phone.sync(fill=False)
    laptop.disconnect(phone)

    impostor = _impostor_claiming(
        laptop,
        data_dir=tmp_path / "impostor-after-session",
        source=src,
    )
    url = "https://example.com/after-session"
    src.bytes_by_url[url] = b"audio:after"
    evil_mix = impostor.add_mix(
        title="After session impostor",
        url=url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="after-session-1",
        artist_name="Evil DJ",
    )

    # Same trusted public key at a new Locator must not inherit the old session.
    phone.connect(impostor)
    phone.sync(fill=False)

    assert evil_mix.id not in {m.id for m in phone.mixes()}

    # Real Peer reconnects and proves again; Catalog sync resumes.
    phone.disconnect(impostor)
    laptop.connect(phone)
    real_url = "https://example.com/real-after-reproof"
    src.bytes_by_url[real_url] = b"audio:real"
    real_mix = laptop.add_mix(
        title="Real after reproof",
        url=real_url,
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="real-after-1",
        artist_name="DJ Example",
    )
    laptop.sync(fill=False)
    phone.sync(fill=False)

    assert real_mix.id in {m.id for m in phone.mixes()}
    assert evil_mix.id not in {m.id for m in phone.mixes()}
