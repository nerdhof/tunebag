"""Secure ephemeral pairing session: PIN limits, dual confirm, SAS, accept removal."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.pairing import (
    PIN_MAX_ATTEMPTS,
    fingerprint_from_key,
    generate_identity,
    public_key_raw_bytes,
    sas_for_session,
)
from tunebag.web import create_app


def test_fingerprint_uses_raw_key_not_pem_prefix() -> None:
    a = generate_identity("a")
    b = generate_identity("b")
    assert fingerprint_from_key(a.public_key_pem) != fingerprint_from_key(b.public_key_pem)
    # Old bug: base32 of PEM text was identical for every key.
    assert not fingerprint_from_key(a.public_key_pem).startswith("FUWS")
    assert len(public_key_raw_bytes(a.public_key_pem)) == 32


def test_wrong_pin_rejected_and_locks_out() -> None:
    host = DeviceAgent("host")
    guest = DeviceAgent("guest")
    host.connect(guest)
    host.start_pairing_session()
    session = host._pairing_session
    assert session is not None

    for _ in range(PIN_MAX_ATTEMPTS - 1):
        with pytest.raises(ValueError, match="invalid PIN"):
            guest.join_pairing_session(pin="00000000", host_agent=host)

    with pytest.raises(ValueError, match="too many PIN attempts"):
        guest.join_pairing_session(pin="00000000", host_agent=host)

    assert host._pairing_session is not None
    assert host._pairing_session["state"] == "cancelled"
    assert guest.peers() == []
    assert host.peers() == []


def test_dual_confirm_required_cancel_leaves_no_trust() -> None:
    host = DeviceAgent("host")
    guest = DeviceAgent("guest")
    host.connect(guest)
    host.start_pairing_session()
    pin = host.pairing_session_status(include_pin=True)["pin"]
    guest.join_pairing_session(pin=pin, host_agent=host)

    assert host.peers() == []
    assert guest.peers() == []

    host.confirm_pairing_session()
    assert host.peers() == []
    assert guest.peers() == []

    host.cancel_pairing_session()
    with pytest.raises(ValueError):
        guest.confirm_pairing_session()

    assert host.peers() == []
    assert guest.peers() == []


def test_both_confirms_establish_mutual_trust() -> None:
    host = DeviceAgent("host", priority=1)
    guest = DeviceAgent("guest", priority=10)
    host.connect(guest)
    host.start_pairing_session()
    pin = host.pairing_session_status(include_pin=True)["pin"]
    guest.join_pairing_session(pin=pin, host_agent=host)

    host_sas = host.pairing_session_status()["sas"]
    guest_sas = guest.pairing_session_status()["sas"]
    assert host_sas == guest_sas
    assert host_sas == sas_for_session(
        session_id=host._pairing_session["session_id"],  # type: ignore[index]
        host_public_key_pem=host.public_key_pem,
        guest_public_key_pem=guest.public_key_pem,
    )

    assert host.confirm_pairing_session() is None
    peer = guest.confirm_pairing_session()
    assert peer is not None
    assert peer.name == "host"
    assert [p.name for p in host.peers()] == ["guest"]
    assert [p.name for p in guest.peers()] == ["host"]


def test_sas_differs_when_peer_keys_differ() -> None:
    host = DeviceAgent("host")
    guest = DeviceAgent("guest")
    mallory = DeviceAgent("mallory")
    session_id = "test-session"
    real = sas_for_session(
        session_id=session_id,
        host_public_key_pem=host.public_key_pem,
        guest_public_key_pem=guest.public_key_pem,
    )
    mitm = sas_for_session(
        session_id=session_id,
        host_public_key_pem=host.public_key_pem,
        guest_public_key_pem=mallory.public_key_pem,
    )
    assert real != mitm


def test_pair_accept_endpoint_gone() -> None:
    agent = DeviceAgent("solo")
    client = TestClient(create_app(agent))
    gone = client.post("/api/pair/accept", json={"payload": agent.pairing_payload()})
    assert gone.status_code == 410
    legacy = client.post("/api/pair", json={"payload": agent.pairing_payload()})
    assert legacy.status_code == 410


def test_join_requires_valid_signature() -> None:
    host = DeviceAgent("host")
    guest = DeviceAgent("guest")
    host.connect(guest)
    host.start_pairing_session()
    session = host._pairing_session
    assert session is not None
    pin = session["pin"]

    with pytest.raises(ValueError, match="invalid join signature"):
        host.receive_pair_join(
            {
                "session_id": session["session_id"],
                "pin": pin,
                "nonce": "nonce",
                "signature": base64.b64encode(b"not-a-real-signature").decode("ascii"),
                "payload": guest.pairing_payload(),
            }
        )
