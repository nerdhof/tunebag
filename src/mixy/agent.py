"""Device agent: the only seam for demo behavior and tests.

HTTP and the CLI are transports that call this same object. Pairing, catalog
writes, and sync happen here; the private key never leaves the process.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from uuid import UUID

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from mixy.catalog import Catalog
from mixy.domain import Artist, Device, Mix, Platform
from mixy.events import Event, EventLog, EventType
from mixy.pairing import (
    DeviceIdentity,
    generate_identity,
    short_code_from_key,
)
from mixy.pairing import (
    pairing_payload as build_pairing_payload,
)

_HTTP_TIMEOUT = 5.0


class DeviceAgent:
    def __init__(
        self,
        name: str,
        *,
        priority: int = 100,
        base_url: str | None = None,
        identity: DeviceIdentity | None = None,
    ) -> None:
        self._identity = identity or generate_identity(name)
        self._private_key = _load_private_key(self._identity.private_key_pem)
        self.device = Device(
            name=name,
            public_key_pem=self._identity.public_key_pem,
            priority=priority,
        )
        self.base_url = base_url
        self.catalog = Catalog()
        self.catalog.local_device_id = self.device.id
        self.catalog.add_device(self.device)
        self._log = EventLog()
        self._reachable: list[DeviceAgent] = []
        self._peer_urls: dict[UUID, str] = {}
        self._seen_event_ids: set[UUID] = set()

    @property
    def device_id(self) -> UUID:
        return self.device.id

    @property
    def name(self) -> str:
        return self.device.name

    @property
    def public_key_pem(self) -> str:
        return self.device.public_key_pem

    @property
    def private_key_pem(self) -> str:
        return self._identity.private_key_pem

    def short_code(self) -> str:
        return short_code_from_key(self.public_key_pem)

    def pairing_payload(self) -> dict[str, Any]:
        return build_pairing_payload(
            self.name,
            self.public_key_pem,
            device_id=str(self.device.id),
            priority=self.device.priority,
            url=self.base_url,
        )

    def connect(self, other: DeviceAgent) -> None:
        """Mark another in-process agent reachable (test / same-host peer)."""
        if other is self:
            return
        if other not in self._reachable:
            self._reachable.append(other)
        if self not in other._reachable:
            other._reachable.append(self)

    def peers(self) -> list[Device]:
        return [d for d in self.catalog.devices.values() if d.id != self.device.id]

    def mixes(self) -> list[Mix]:
        return self.catalog.mixes_list()

    def pair(self, payload: dict[str, Any]) -> Device:
        peer = self._trust_payload(payload)
        for agent in self._reachable:
            if agent.public_key_pem == payload["public_key_pem"]:
                agent.accept_pair_offer(self.pairing_payload())
                return peer
        if url := payload.get("url"):
            self._http_offer_pair(url)
        return peer

    def pair_by_short_code(self, code: str, *, peer_url: str | None = None) -> Device:
        needle = code.strip().upper()
        if peer_url:
            payload = self._http_fetch_pairing(peer_url)
            if payload.get("short_code", "").upper() != needle:
                raise ValueError("short code does not match peer")
            payload["url"] = payload.get("url") or peer_url.rstrip("/")
            return self.pair(payload)
        for agent in self._reachable:
            if agent.short_code() == needle:
                return self.pair(agent.pairing_payload())
        raise ValueError(f"no reachable peer with short code {needle}")

    def accept_pair_offer(self, payload: dict[str, Any]) -> Device:
        """Remote peer completed pairing and is offering their identity."""
        return self._trust_payload(payload)

    def remember_peer_url(self, peer_id: UUID, url: str) -> None:
        self._peer_urls[peer_id] = url

    def peer_urls(self) -> dict[UUID, str]:
        return dict(self._peer_urls)

    def ingest_events(self, events: list[Event]) -> None:
        for event in events:
            self._ingest(event)

    def add_mix(
        self,
        *,
        title: str,
        url: str,
        duration_seconds: int,
        platform: Platform,
        platform_id: str,
        artist_name: str,
    ) -> Mix:
        artist = Artist(
            platform=platform,
            platform_id=f"artist:{platform_id}",
            name=artist_name,
            url=url,
        )
        mix = Mix(
            artist_id=artist.id,
            platform=platform,
            platform_id=platform_id,
            title=title,
            url=url,
            duration_seconds=duration_seconds,
        )
        self._append_and_apply(
            EventType.ARTIST_ADDED,
            {
                "id": str(artist.id),
                "platform": platform.value,
                "platform_id": artist.platform_id,
                "name": artist.name,
                "url": artist.url,
            },
        )
        self._append_and_apply(
            EventType.MIX_ADDED,
            {
                "id": str(mix.id),
                "artist_id": str(mix.artist_id),
                "platform": platform.value,
                "platform_id": mix.platform_id,
                "title": mix.title,
                "url": mix.url,
                "duration_seconds": mix.duration_seconds,
            },
        )
        return self.catalog.mixes[mix.id]

    def export_events(self) -> list[Event]:
        return self._log.all()

    def sync(self) -> None:
        for agent in list(self._reachable):
            if not self._trusts_public_key(agent.public_key_pem):
                continue
            for event in agent.export_events():
                self._ingest(event)
        trusted_ids = {peer.id for peer in self.peers()}
        for peer_id, url in list(self._peer_urls.items()):
            if peer_id not in trusted_ids:
                continue
            self.ingest_events(self._http_fetch_events(url))

    def _trust_payload(self, payload: dict[str, Any]) -> Device:
        if payload.get("v") != 1:
            raise ValueError("unsupported pairing payload version")
        name = payload["name"]
        public_key_pem = payload["public_key_pem"]
        if "device_id" not in payload:
            raise ValueError("pairing payload missing device_id")
        peer_id = UUID(payload["device_id"])
        priority = int(payload.get("priority", 100))
        expected = short_code_from_key(public_key_pem)
        if payload.get("short_code") and payload["short_code"].upper() != expected:
            raise ValueError("short code does not match public key")
        existing = self.catalog.devices.get(peer_id)
        if existing is not None:
            peer = existing
        else:
            peer = Device(
                id=peer_id,
                name=name,
                public_key_pem=public_key_pem,
                priority=priority,
            )
            self._append_and_apply(
                EventType.DEVICE_PAIRED,
                {
                    "id": str(peer.id),
                    "name": peer.name,
                    "public_key_pem": peer.public_key_pem,
                    "priority": peer.priority,
                },
            )
            peer = self.catalog.devices[peer_id]
        if url := payload.get("url"):
            self._peer_urls[peer.id] = url
        return peer

    def _trusts_public_key(self, public_key_pem: str) -> bool:
        return any(d.public_key_pem == public_key_pem for d in self.peers())

    def _append_and_apply(self, event_type: EventType, payload: dict[str, Any]) -> Event:
        event = Event(type=event_type, device_id=self.device.id, payload=payload)
        event.signature = self._sign(event)
        self._log.append(event)
        self._seen_event_ids.add(event.id)
        self._apply(event)
        return event

    def _ingest(self, event: Event) -> None:
        if event.id in self._seen_event_ids:
            return
        if event.device_id == self.device.id:
            return
        author = self.catalog.devices.get(event.device_id)
        if author is None:
            return
        if not self._verify(event, author.public_key_pem):
            raise InvalidSignature("event signature mismatch")
        self._seen_event_ids.add(event.id)
        self._log.append(event)
        self._apply(event)

    def _apply(self, event: Event) -> None:
        payload = event.payload
        if event.type is EventType.DEVICE_PAIRED:
            device_id = UUID(payload["id"])
            if device_id == self.device.id:
                return
            if device_id not in self.catalog.devices:
                self.catalog.add_device(
                    Device(
                        id=device_id,
                        name=payload["name"],
                        public_key_pem=payload["public_key_pem"],
                        priority=int(payload.get("priority", 100)),
                    )
                )
            return
        if event.type is EventType.ARTIST_ADDED:
            artist_id = UUID(payload["id"])
            if artist_id not in self.catalog.artists:
                self.catalog.add_artist(
                    Artist(
                        id=artist_id,
                        platform=Platform(payload["platform"]),
                        platform_id=payload["platform_id"],
                        name=payload["name"],
                        url=payload["url"],
                    )
                )
            return
        if event.type is EventType.MIX_ADDED:
            mix_id = UUID(payload["id"])
            if mix_id not in self.catalog.mixes:
                self.catalog.add_mix(
                    Mix(
                        id=mix_id,
                        artist_id=UUID(payload["artist_id"]),
                        platform=Platform(payload["platform"]),
                        platform_id=payload["platform_id"],
                        title=payload["title"],
                        url=payload["url"],
                        duration_seconds=int(payload["duration_seconds"]),
                    )
                )
            return

    def _sign(self, event: Event) -> str:
        signature = self._private_key.sign(_event_bytes(event))
        return base64.b64encode(signature).decode("ascii")

    def _verify(self, event: Event, public_key_pem: str) -> bool:
        if not event.signature:
            return False
        public_key = _load_public_key(public_key_pem)
        try:
            public_key.verify(base64.b64decode(event.signature), _event_bytes(event))
        except InvalidSignature:
            return False
        return True

    def _http_offer_pair(self, peer_url: str) -> None:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.post(
                f"{peer_url.rstrip('/')}/api/pair/accept",
                json={"payload": self.pairing_payload()},
            )
            response.raise_for_status()

    def _http_fetch_pairing(self, peer_url: str) -> dict[str, Any]:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.get(f"{peer_url.rstrip('/')}/api/pairing")
            response.raise_for_status()
            return response.json()

    def _http_fetch_events(self, peer_url: str) -> list[Event]:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.get(f"{peer_url.rstrip('/')}/api/events")
            response.raise_for_status()
            raw_events = response.json().get("events", [])
        return [Event.model_validate(raw) for raw in raw_events]


def _event_bytes(event: Event) -> bytes:
    body = {
        "id": str(event.id),
        "type": event.type.value,
        "device_id": str(event.device_id),
        "payload": event.payload,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def _load_private_key(pem: str) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("expected Ed25519 private key")
    return key


def _load_public_key(pem: str) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(pem.encode())
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("expected Ed25519 public key")
    return key
