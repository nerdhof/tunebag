"""Issue 01: pair two devices — exercised only through DeviceAgent."""

from __future__ import annotations

from tunebag.agent import DeviceAgent
from tunebag.domain import Platform
from tunebag.pairing import generate_identity


def test_pairing_payload_has_name_public_key_and_short_code_not_private_key() -> None:
    laptop = DeviceAgent("laptop")

    payload = laptop.pairing_payload()

    assert payload["name"] == "laptop"
    assert payload["device_id"] == str(laptop.device_id)
    assert "BEGIN PUBLIC KEY" in payload["public_key_pem"]
    assert payload["short_code"] == laptop.short_code()
    assert "private" not in {k.lower() for k in payload}
    assert "PRIVATE" not in payload["public_key_pem"]
    assert laptop.private_key_pem  # exists locally
    assert "PRIVATE KEY" in laptop.private_key_pem


def test_after_pairing_each_device_shows_the_other_as_peer() -> None:
    laptop = DeviceAgent("laptop", priority=1)
    phone = DeviceAgent("phone", priority=10)
    laptop.connect(phone)

    phone.pair(laptop.pairing_payload())

    assert [p.name for p in phone.peers()] == ["laptop"]
    assert [p.name for p in laptop.peers()] == ["phone"]
    assert phone.peers()[0].priority == 1
    assert laptop.peers()[0].priority == 10
    assert all(p.public_key_pem for p in phone.peers())
    assert all("PRIVATE" not in p.public_key_pem for p in laptop.peers())


def test_short_code_pairs_when_peer_is_reachable() -> None:
    laptop = DeviceAgent("laptop", priority=1)
    phone = DeviceAgent("phone", priority=10)
    laptop.connect(phone)

    phone.pair_by_short_code(laptop.short_code())

    assert [p.name for p in phone.peers()] == ["laptop"]
    assert [p.name for p in laptop.peers()] == ["phone"]


def test_pairing_same_peer_again_does_not_duplicate() -> None:
    laptop = DeviceAgent("laptop", priority=1)
    phone = DeviceAgent("phone", priority=10)
    laptop.connect(phone)

    phone.pair(laptop.pairing_payload())
    phone.pair(laptop.pairing_payload())

    assert [p.name for p in phone.peers()] == ["laptop"]
    assert [p.name for p in laptop.peers()] == ["phone"]


def test_pairing_same_public_key_under_new_device_id_does_not_duplicate() -> None:
    identity = generate_identity("laptop")
    laptop_a = DeviceAgent("laptop", identity=identity, priority=1)
    laptop_b = DeviceAgent("laptop", identity=identity, priority=1)
    phone = DeviceAgent("phone", priority=10)
    phone.connect(laptop_a)
    phone.pair(laptop_a.pairing_payload())

    phone.connect(laptop_b)
    phone.pair(laptop_b.pairing_payload())

    assert len(phone.peers()) == 1
    assert phone.peers()[0].public_key_pem == identity.public_key_pem


def test_catalog_event_on_one_device_visible_on_other_after_sync() -> None:
    laptop = DeviceAgent("laptop", priority=1)
    phone = DeviceAgent("phone", priority=10)
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())

    mix = laptop.add_mix(
        title="Warmup set",
        url="https://example.com/warmup",
        duration_seconds=3600,
        platform=Platform.SOUNDCLOUD,
        platform_id="warmup-1",
        artist_name="DJ Example",
    )
    laptop.sync()
    phone.sync()

    assert mix.id in {m.id for m in phone.mixes()}
    tagged = next(m for m in phone.mixes() if m.id == mix.id)
    assert tagged.title == "Warmup set"
