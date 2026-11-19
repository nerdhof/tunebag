"""CatalogJournal — Event log spine for local Catalog writes and cold-start rebuild."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidSignature

from tunebag.events import Event, EventLog, EventType
from tunebag.projection import CatalogState, LocalEffects
from tunebag.projection import apply as apply_catalog_event

OnApplied = Callable[[Event, LocalEffects], None]
SignFn = Callable[[Event], str]
VerifyFn = Callable[[Event, str], bool]
ClockFn = Callable[[], datetime]


class CatalogJournal:
    """Event log spine: lock, seq, dedupe, sign/verify, unknown-author buffer, apply."""

    def __init__(
        self,
        *,
        catalog: CatalogState,
        log: EventLog,
        local_device_id: UUID,
        local_public_key_pem: str,
        clock: ClockFn,
        sign: SignFn,
        verify: VerifyFn,
        on_applied: OnApplied,
    ) -> None:
        self._catalog = catalog
        self._log = log
        self._local_device_id = local_device_id
        self._local_public_key_pem = local_public_key_pem
        self._clock = clock
        self._sign = sign
        self._verify = verify
        self._on_applied = on_applied
        self._lock = threading.RLock()
        self._event_seq = 0
        self._seen_event_ids: set[UUID] = set()
        self._unknown_author_buffer: dict[UUID, Event] = {}

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Hold the Event log RLock across nested append_local / live apply."""
        with self._lock:
            yield

    def export(self) -> list[Event]:
        """Snapshot the Event log under the lock (consistent vs hold sections)."""
        with self._lock:
            return list(self._log.all())

    def append_local(self, event_type: EventType, payload: dict[str, Any]) -> Event:
        """Bump local seq, sign, append, project, and run on_applied under the lock."""
        with self._lock:
            self._event_seq += 1
            event = Event(
                type=event_type,
                device_id=self._local_device_id,
                created_at=self._clock(),
                seq=self._event_seq,
                payload=payload,
            )
            event.signature = self._sign(event)
            self._log.append(event)
            self._seen_event_ids.add(event.id)
            self._apply_live(event)
            return event

    def ingest_foreign(self, event: Event) -> None:
        """Verify and apply a peer Event, or buffer it until the author is paired.

        Silent skips: already seen, self-authored, or unpaired author.
        ``InvalidSignature`` fails fast when the author is known.
        """
        with self._lock:
            if event.id in self._seen_event_ids:
                return
            if event.device_id == self._local_device_id:
                return
            if event.device_id in self._catalog.unpaired_device_ids:
                return
            author = self._catalog.devices.get(event.device_id)
            if author is None:
                self._unknown_author_buffer[event.id] = event
                return
            self._unknown_author_buffer.pop(event.id, None)
            self._commit_foreign(event, author.public_key_pem)

    def replay(self) -> None:
        """Rebuild Catalog from the durable Event log (cold start; no on_applied)."""
        with self._lock:
            for event in self._log.all():
                if event.device_id == self._local_device_id:
                    if not self._verify(event, self._local_public_key_pem):
                        raise InvalidSignature("event signature mismatch")
                    self._event_seq = max(self._event_seq, int(event.seq))
                else:
                    if event.device_id in self._catalog.unpaired_device_ids:
                        self._seen_event_ids.add(event.id)
                        continue
                    author = self._catalog.devices.get(event.device_id)
                    # Unknown author: still apply; event was verified when ingested.
                    if author is not None and not self._verify(
                        event, author.public_key_pem
                    ):
                        raise InvalidSignature("event signature mismatch")
                self._seen_event_ids.add(event.id)
                apply_catalog_event(
                    self._catalog,
                    event,
                    local_device_id=self._local_device_id,
                    now=self._clock(),
                )

    def _commit_foreign(self, event: Event, public_key_pem: str) -> None:
        """Verify, append, and live-apply a peer Event. Caller must hold ``_lock``."""
        if not self._verify(event, public_key_pem):
            raise InvalidSignature("event signature mismatch")
        self._seen_event_ids.add(event.id)
        self._log.append(event)
        self._apply_live(event)

    def _flush_buffered_events_for(self, author_id: UUID) -> None:
        """Re-enter ``ingest_foreign`` for buffered Events of a newly known author.

        Caller must hold ``_lock``. Applying a buffered ``DEVICE_PAIRED`` may
        flush further authors. Order follows signed author time then seq.
        """
        pending = sorted(
            (
                event
                for event in self._unknown_author_buffer.values()
                if event.device_id == author_id
            ),
            key=lambda e: (e.created_at, int(e.seq), e.id),
        )
        for event in pending:
            self.ingest_foreign(event)

    def _drop_buffered_events_for(self, author_id: UUID) -> None:
        """Drop buffered Events for an unpaired author. Caller must hold ``_lock``."""
        for event_id, buffered in list(self._unknown_author_buffer.items()):
            if buffered.device_id == author_id:
                self._unknown_author_buffer.pop(event_id, None)

    def _apply_live(self, event: Event) -> None:
        """Project one Event, flush/drop trust buffers, then on_applied.

        Caller must hold ``_lock``. After live ``DEVICE_PAIRED``, buffered
        Events for that author flush (re-entrant ingest) before ``on_applied``.
        """
        _, effects = apply_catalog_event(
            self._catalog,
            event,
            local_device_id=self._local_device_id,
            now=self._clock(),
        )
        if event.type is EventType.DEVICE_PAIRED:
            device_id = UUID(event.payload["id"])
            if device_id != self._local_device_id and device_id in self._catalog.devices:
                self._flush_buffered_events_for(device_id)
        elif event.type is EventType.DEVICE_UNPAIRED:
            device_id = UUID(event.payload["id"])
            if device_id != self._local_device_id:
                self._drop_buffered_events_for(device_id)
        self._on_applied(event, effects)
