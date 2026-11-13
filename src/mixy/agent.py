"""Device agent: the only seam for demo behavior and tests.

HTTP and the CLI are transports that call this same object. Pairing, catalog
writes, and sync happen here; the private key never leaves the process.
"""

from __future__ import annotations

import base64
import json
import random
from datetime import datetime
from pathlib import Path
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
from mixy.domain import (
    Artist,
    Assignment,
    Device,
    DeviceHours,
    Intent,
    Mix,
    Platform,
    Sequence,
    SequenceEntry,
    StarBucket,
    StarDistribution,
    Stars,
)
from mixy.events import Event, EventLog, EventType
from mixy.pairing import (
    DeviceIdentity,
    generate_identity,
    short_code_from_key,
)
from mixy.pairing import (
    pairing_payload as build_pairing_payload,
)
from mixy.sequence import assign_by_budget, build_sequence
from mixy.source import (
    DEFAULT_MIN_DURATION_SECONDS,
    Source,
    default_source,
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
        source: Source | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self._identity = identity or generate_identity(name)
        self._private_key = _load_private_key(self._identity.private_key_pem)
        self.device = Device(
            name=name,
            public_key_pem=self._identity.public_key_pem,
            priority=priority,
        )
        self.base_url = base_url
        self.source = source if source is not None else default_source()
        self.catalog = Catalog(data_dir=data_dir)
        self.catalog.local_device_id = self.device.id
        self.catalog.add_device(self.device)
        self._log = EventLog()
        self._reachable: list[DeviceAgent] = []
        self._peer_urls: dict[UUID, str] = {}
        self._seen_event_ids: set[UUID] = set()
        self._local_files: dict[UUID, bytes] = {}
        self.data_dir = self.catalog.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

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

    def disconnect(self, other: DeviceAgent) -> None:
        """Mark another in-process agent unreachable."""
        if other in self._reachable:
            self._reachable.remove(other)
        if self in other._reachable:
            other._reachable.remove(self)

    def peers(self) -> list[Device]:
        return [d for d in self.catalog.devices.values() if d.id != self.device.id]

    def mixes(self) -> list[Mix]:
        return self.catalog.mixes_list()

    def artists(self) -> list[Artist]:
        return list(self.catalog.artists.values())

    def intents(self) -> list[Intent]:
        return list(self.catalog.intents.values())

    def sequence(self, intent_id: UUID) -> Sequence | None:
        return self.catalog.sequences.get(intent_id)

    def assignment(
        self, intent_id: UUID, device_id: UUID | None = None
    ) -> Assignment | None:
        target = device_id if device_id is not None else self.device.id
        return self.catalog.assignments.get((intent_id, target))

    def files(self) -> list[Mix]:
        """Mixes that have local audio bytes on this device."""
        return [
            self.catalog.mixes[mix_id]
            for mix_id in self._local_files
            if mix_id in self.catalog.mixes
        ]

    def file_bytes(self, mix_id: UUID) -> bytes | None:
        """Local audio bytes for a mix, if present (peer handoff)."""
        return self._local_files.get(mix_id)

    def remove_local_file(self, mix_id: UUID) -> None:
        """Drop local audio for a mix so it can be fetched again."""
        self._local_files.pop(mix_id, None)
        blob = self._blob_path(mix_id)
        if blob.exists():
            blob.unlink()
        self._refresh_intent_folders()

    def intent_folder(self, intent_id: UUID) -> Path:
        """Directory of this device's assigned files for an intent."""
        path = self.data_dir / "intents" / str(intent_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def fill_caches(self) -> None:
        """Fill this device's assignments from peers or origin (unmetered)."""
        for intent in self.intents():
            assignment = self.assignment(intent.id)
            if assignment is None:
                continue
            for mix_id in assignment.mix_ids:
                self._ensure_local_file(intent.id, mix_id)
        self._refresh_intent_folders()

    def add_artists(
        self,
        urls: list[str],
        *,
        min_duration_seconds: int = DEFAULT_MIN_DURATION_SECONDS,
    ) -> list[Mix]:
        """List own uploads for each artist URL and write catalog rows only."""
        added: list[Mix] = []
        for url in urls:
            listing = self.source.list_uploads(url)
            artist = Artist(
                platform=listing.platform,
                platform_id=listing.platform_id,
                name=listing.name,
                url=listing.url,
            )
            self._append_and_apply(
                EventType.ARTIST_ADDED,
                {
                    "id": str(artist.id),
                    "platform": artist.platform.value,
                    "platform_id": artist.platform_id,
                    "name": artist.name,
                    "url": artist.url,
                },
            )
            for upload in listing.uploads:
                if upload.duration_seconds < min_duration_seconds:
                    continue
                mix = Mix(
                    artist_id=artist.id,
                    platform=upload.platform,
                    platform_id=upload.platform_id,
                    title=upload.title,
                    url=upload.url,
                    duration_seconds=upload.duration_seconds,
                )
                self._append_and_apply(
                    EventType.MIX_ADDED,
                    {
                        "id": str(mix.id),
                        "artist_id": str(mix.artist_id),
                        "platform": mix.platform.value,
                        "platform_id": mix.platform_id,
                        "title": mix.title,
                        "url": mix.url,
                        "duration_seconds": mix.duration_seconds,
                    },
                )
                added.append(self.catalog.mixes[mix.id])
        return added

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

    def tag_mix(self, mix_id: UUID, tags: list[str]) -> Mix:
        if mix_id not in self.catalog.mixes:
            raise KeyError(f"unknown mix {mix_id}")
        self._append_and_apply(
            EventType.MIX_TAGGED,
            {"mix_id": str(mix_id), "tags": list(tags)},
        )
        return self.catalog.mixes[mix_id]

    def rate_mix(self, mix_id: UUID, stars: Stars) -> Mix:
        if mix_id not in self.catalog.mixes:
            raise KeyError(f"unknown mix {mix_id}")
        self._append_and_apply(
            EventType.MIX_RATED,
            {"mix_id": str(mix_id), "stars": int(stars)},
        )
        return self.catalog.mixes[mix_id]

    def reject_mix(self, mix_id: UUID) -> Mix:
        """Commit a reject immediately (undo window is issue 07)."""
        if mix_id not in self.catalog.mixes:
            raise KeyError(f"unknown mix {mix_id}")
        self._append_and_apply(
            EventType.MIX_REJECTED,
            {"mix_id": str(mix_id)},
        )
        return self.catalog.mixes[mix_id]

    def create_intent(
        self,
        name: str,
        *,
        tags: list[str] | None = None,
        distribution: StarDistribution | None = None,
        seed: int | None = None,
        device_hours: list[tuple[UUID, int]] | None = None,
    ) -> Intent:
        hours = [
            DeviceHours(device_id=device_id, budget_seconds=budget)
            for device_id, budget in (device_hours or [])
        ]
        intent = Intent(
            name=name,
            tags=list(tags or []),
            distribution=distribution or StarDistribution(),
            device_hours=hours,
            seed=seed if seed is not None else random.randrange(1 << 31),
        )
        self._upsert_intent_and_rebuild(intent)
        return self.catalog.intents[intent.id]

    def set_device_hours(
        self,
        intent_id: UUID,
        device_id: UUID,
        budget_seconds: int,
    ) -> Intent:
        intent = self.catalog.intents.get(intent_id)
        if intent is None:
            raise KeyError(f"unknown intent {intent_id}")
        hours = [dh for dh in intent.device_hours if dh.device_id != device_id]
        hours.append(DeviceHours(device_id=device_id, budget_seconds=budget_seconds))
        updated = intent.model_copy(update={"device_hours": hours})
        self._upsert_intent_and_rebuild(updated)
        return self.catalog.intents[intent_id]

    def delete_intent(self, intent_id: UUID) -> None:
        if intent_id not in self.catalog.intents:
            raise KeyError(f"unknown intent {intent_id}")
        self._append_and_apply(
            EventType.INTENT_DELETED,
            {"id": str(intent_id)},
        )

    def update_intent(
        self,
        intent_id: UUID,
        *,
        name: str | None = None,
        tags: list[str] | None = None,
        distribution: StarDistribution | None = None,
        device_hours: list[tuple[UUID, int]] | None = None,
    ) -> Intent:
        intent = self.catalog.intents.get(intent_id)
        if intent is None:
            raise KeyError(f"unknown intent {intent_id}")
        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if tags is not None:
            updates["tags"] = list(tags)
        if distribution is not None:
            updates["distribution"] = distribution
        if device_hours is not None:
            updates["device_hours"] = [
                DeviceHours(device_id=device_id, budget_seconds=budget)
                for device_id, budget in device_hours
            ]
        if not updates:
            return intent
        updated = intent.model_copy(update=updates)
        self._upsert_intent_and_rebuild(updated)
        return self.catalog.intents[intent_id]

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

    def _ensure_local_file(self, intent_id: UUID, mix_id: UUID) -> None:
        if mix_id in self._local_files:
            return
        mix = self.catalog.mixes.get(mix_id)
        if mix is None:
            return

        # Prefer a copy from any reachable peer that already has the bytes.
        for peer in self._reachable:
            if not self._trusts_public_key(peer.public_key_pem):
                continue
            peer_bytes = peer.file_bytes(mix_id)
            if peer_bytes is not None:
                self._store_local_file(mix_id, peer_bytes)
                return

        preferred = self._preferred_origin_agent(intent_id, mix_id)
        if preferred is self:
            data = self.source.fetch_bytes(mix.url)
            self._store_local_file(mix_id, data)
            return
        if preferred is not None:
            # Preferred peer is reachable but does not have the file yet — wait.
            return
        # Preferred unreachable (or no other assignee): fetch our own hours.
        data = self.source.fetch_bytes(mix.url)
        self._store_local_file(mix_id, data)

    def _preferred_origin_agent(
        self, intent_id: UUID, mix_id: UUID
    ) -> DeviceAgent | None:
        """Highest-priority (lowest number) reachable agent whose assignment includes mix_id."""
        candidates: list[DeviceAgent] = []
        if self._assignment_includes(self, intent_id, mix_id):
            candidates.append(self)
        for peer in self._reachable:
            if not self._trusts_public_key(peer.public_key_pem):
                continue
            if self._assignment_includes(peer, intent_id, mix_id):
                candidates.append(peer)
        if not candidates:
            return None
        return min(candidates, key=lambda a: (a.device.priority, str(a.device_id)))

    @staticmethod
    def _assignment_includes(
        agent: DeviceAgent, intent_id: UUID, mix_id: UUID
    ) -> bool:
        assignment = agent.assignment(intent_id, agent.device_id)
        return assignment is not None and mix_id in assignment.mix_ids

    def _store_local_file(self, mix_id: UUID, data: bytes) -> None:
        self._local_files[mix_id] = data
        blob = self._blob_path(mix_id)
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(data)

    def _blob_path(self, mix_id: UUID) -> Path:
        return self.data_dir / "blobs" / str(mix_id)

    def _refresh_intent_folders(self) -> None:
        for intent in self.intents():
            folder = self.intent_folder(intent.id)
            # Clear previous links/files so folder matches current assignment.
            for existing in folder.iterdir():
                if existing.is_file() or existing.is_symlink():
                    existing.unlink()
            assignment = self.assignment(intent.id)
            if assignment is None:
                continue
            for mix_id in assignment.mix_ids:
                if mix_id not in self._local_files:
                    continue
                mix = self.catalog.mixes.get(mix_id)
                if mix is None:
                    continue
                blob = self._blob_path(mix_id)
                if not blob.exists():
                    blob.parent.mkdir(parents=True, exist_ok=True)
                    blob.write_bytes(self._local_files[mix_id])
                target = folder / _safe_filename(mix.title, mix_id)
                if target.exists() or target.is_symlink():
                    target.unlink()
                try:
                    target.hardlink_to(blob)
                except OSError:
                    target.write_bytes(self._local_files[mix_id])

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

    def _upsert_intent_and_rebuild(self, intent: Intent) -> None:
        self._append_and_apply(EventType.INTENT_UPSERTED, _intent_payload(intent))
        sequence = build_sequence(intent, self.catalog.mixes_list())
        self._append_and_apply(
            EventType.SEQUENCE_BUILT,
            {
                "intent_id": str(sequence.intent_id),
                "entries": [
                    {
                        "mix_id": str(entry.mix_id),
                        "position": entry.position,
                        "bucket": entry.bucket.value,
                    }
                    for entry in sequence.entries
                ],
            },
        )
        duration_by_mix = {
            mix_id: mix.duration_seconds for mix_id, mix in self.catalog.mixes.items()
        }
        for device_hours in intent.device_hours:
            mix_ids = assign_by_budget(
                sequence,
                device_hours.device_id,
                device_hours.budget_seconds,
                duration_by_mix,
            )
            self._append_and_apply(
                EventType.ASSIGNMENT_SET,
                {
                    "intent_id": str(intent.id),
                    "device_id": str(device_hours.device_id),
                    "mix_ids": [str(mix_id) for mix_id in mix_ids],
                    "budget_seconds": device_hours.budget_seconds,
                },
            )

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
        if event.type is EventType.MIX_TAGGED:
            mix = self.catalog.mixes.get(UUID(payload["mix_id"]))
            if mix is not None:
                self.catalog.add_mix(mix.model_copy(update={"tags": list(payload["tags"])}))
            return
        if event.type is EventType.MIX_RATED:
            mix = self.catalog.mixes.get(UUID(payload["mix_id"]))
            if mix is not None:
                self.catalog.add_mix(
                    mix.model_copy(update={"stars": Stars(int(payload["stars"]))})
                )
            return
        if event.type is EventType.MIX_REJECTED:
            mix = self.catalog.mixes.get(UUID(payload["mix_id"]))
            if mix is not None:
                self.catalog.add_mix(mix.model_copy(update={"rejected": True}))
            return
        if event.type is EventType.INTENT_UPSERTED:
            self.catalog.upsert_intent(_intent_from_payload(payload))
            return
        if event.type is EventType.INTENT_DELETED:
            self.catalog.delete_intent(UUID(payload["id"]))
            return
        if event.type is EventType.SEQUENCE_BUILT:
            self.catalog.set_sequence(
                Sequence(
                    intent_id=UUID(payload["intent_id"]),
                    entries=[
                        SequenceEntry(
                            mix_id=UUID(entry["mix_id"]),
                            position=int(entry["position"]),
                            bucket=StarBucket(entry["bucket"]),
                        )
                        for entry in payload["entries"]
                    ],
                )
            )
            return
        if event.type is EventType.ASSIGNMENT_SET:
            self.catalog.set_assignment(
                Assignment(
                    intent_id=UUID(payload["intent_id"]),
                    device_id=UUID(payload["device_id"]),
                    mix_ids=[UUID(mix_id) for mix_id in payload["mix_ids"]],
                    budget_seconds=int(payload["budget_seconds"]),
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


def _intent_payload(intent: Intent) -> dict[str, Any]:
    return {
        "id": str(intent.id),
        "name": intent.name,
        "tags": list(intent.tags),
        "distribution": {
            "five": intent.distribution.five,
            "four": intent.distribution.four,
            "three": intent.distribution.three,
            "rest": intent.distribution.rest,
        },
        "device_hours": [
            {
                "device_id": str(dh.device_id),
                "budget_seconds": dh.budget_seconds,
                "expires_at": dh.expires_at.isoformat() if dh.expires_at else None,
            }
            for dh in intent.device_hours
        ],
        "seed": intent.seed,
    }


def _intent_from_payload(payload: dict[str, Any]) -> Intent:
    dist = payload.get("distribution") or {}
    return Intent(
        id=UUID(payload["id"]),
        name=payload["name"],
        tags=list(payload.get("tags") or []),
        distribution=StarDistribution(
            five=float(dist.get("five", 0.4)),
            four=float(dist.get("four", 0.3)),
            three=float(dist.get("three", 0.2)),
            rest=float(dist.get("rest", 0.1)),
        ),
        device_hours=[
            DeviceHours(
                device_id=UUID(dh["device_id"]),
                budget_seconds=int(dh["budget_seconds"]),
                expires_at=(
                    datetime.fromisoformat(dh["expires_at"])
                    if dh.get("expires_at")
                    else None
                ),
            )
            for dh in payload.get("device_hours") or []
        ],
        seed=int(payload["seed"]),
    )


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


def _safe_filename(title: str, mix_id: UUID) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in title).strip()
    if not cleaned:
        cleaned = "mix"
    return f"{cleaned[:80]}-{mix_id}.bin"
