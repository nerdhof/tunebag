"""CatalogJournal — Event log spine for local Catalog writes and cold-start rebuild."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from cryptography.exceptions import InvalidSignature

from tunebag.events import Event, EventLog, EventType
from tunebag.projection import (
    PROJECTION_VERSION,
    CatalogState,
    LocalEffects,
    dump_catalog_snapshot,
    load_catalog_snapshot,
)
from tunebag.projection import apply as apply_catalog_event

if TYPE_CHECKING:
    from tunebag.durable_store import DurableStore

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
        store: DurableStore | None = None,
    ) -> None:
        self._catalog = catalog
        self._log = log
        self._store = store if store is not None else log.store
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
        self._hold_depth = 0
        self._dirty = False

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Hold the Event log RLock; map to one SQLite transaction when durable."""
        with self._lock:
            self._hold_depth += 1
            started_txn = False
            if self._hold_depth == 1 and self._store is not None:
                self._store.begin()
                started_txn = True
            try:
                yield
                if started_txn:
                    self._store.commit()
            except BaseException:
                if started_txn:
                    self._store.rollback()
                    self._dirty = False
                    self._restore_projection_from_durable()
                raise
            finally:
                self._hold_depth -= 1
                if self._hold_depth == 0 and self._dirty:
                    self._write_snapshot()
                    self._dirty = False

    def export(self) -> list[Event]:
        """Snapshot the Event log under the lock (consistent vs hold sections)."""
        with self._lock:
            return list(self._log.all())

    def iter_all(self) -> Iterator[Event]:
        with self._lock:
            events = list(self._log.iter_all())
        yield from events

    def iter_after_cursors(self, cursors: dict[str, int]) -> Iterator[Event]:
        with self._lock:
            events = list(self._log.iter_after_cursors(cursors))
        yield from events

    def author_cursors(self) -> dict[str, int]:
        """Per-author max seq watermarks for incremental pull."""
        with self._lock:
            return {
                str(device_id): seq
                for device_id, seq in self._log.max_seq_by_device().items()
            }

    def append_local(self, event_type: EventType, payload: dict[str, Any]) -> Event:
        """Bump local seq, sign, append, project, and run on_applied under the lock."""
        with self._lock:
            owned_txn = self._owns_write_txn()
            if owned_txn:
                assert self._store is not None
                self._store.begin()
            try:
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
                self._dirty = True
                if owned_txn:
                    self._store.commit()
            except BaseException:
                if owned_txn:
                    self._store.rollback()
                raise
            if owned_txn and self._dirty:
                self._write_snapshot()
                self._dirty = False
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
            owned_txn = self._owns_write_txn()
            if owned_txn:
                assert self._store is not None
                self._store.begin()
            try:
                self._commit_foreign(event, author.public_key_pem)
                self._dirty = True
                if owned_txn:
                    self._store.commit()
            except BaseException:
                if owned_txn:
                    self._store.rollback()
                raise
            if owned_txn and self._dirty:
                self._write_snapshot()
                self._dirty = False

    def boot(self) -> None:
        """Cold start: load disposable snapshot + tail, or full replay; then rewrite tip."""
        with self._lock:
            local = self._catalog.devices.get(self._local_device_id)
            local_id = self._catalog.local_device_id or self._local_device_id
            if self._try_boot_from_snapshot():
                if local is not None:
                    self._catalog.devices[self._local_device_id] = local
                self._catalog.local_device_id = local_id
                return
            self._catalog.clear_projection()
            self._seen_event_ids.clear()
            self._event_seq = 0
            if local is not None:
                self._catalog.add_device(local)
            self._catalog.local_device_id = local_id
            self._replay_unlocked()
            self._write_snapshot()

    def replay(self) -> None:
        """Rebuild Catalog from the durable Event log (cold start; no on_applied)."""
        with self._lock:
            self._replay_unlocked()

    def _try_boot_from_snapshot(self) -> bool:
        """Load snapshot + index through tip + tail-apply. False ⇒ caller full-replays."""
        if self._store is None:
            return False
        tip = self._store.get_snapshot_tip_rowid()
        version = self._store.get_projection_version()
        blob = self._store.get_snapshot_blob()
        if tip is None or version != PROJECTION_VERSION or blob is None:
            return False
        try:
            load_catalog_snapshot(self._catalog, blob)
            self._seen_event_ids.clear()
            self._event_seq = 0
            for rowid, event in self._log.iter_with_rowids():
                if rowid <= tip:
                    self._index_event(event)
                else:
                    self._replay_one(event)
            self._write_snapshot()
            return True
        except Exception:
            self._store.clear_snapshot()
            return False

    def _owns_write_txn(self) -> bool:
        """True when this call should BEGIN/COMMIT (not nested under hold or outer txn)."""
        return (
            self._hold_depth == 0
            and self._store is not None
            and not self._store.in_transaction
        )

    def _restore_projection_from_durable(self) -> None:
        """Rebuild Catalog + seq/seen after a rolled-back hold transaction."""
        local = self._catalog.devices.get(self._local_device_id)
        local_id = self._catalog.local_device_id or self._local_device_id
        if self._try_boot_from_snapshot():
            if local is not None:
                self._catalog.devices[self._local_device_id] = local
            self._catalog.local_device_id = local_id
            return
        self._catalog.clear_projection()
        self._seen_event_ids.clear()
        self._event_seq = 0
        if local is not None:
            self._catalog.add_device(local)
        self._catalog.local_device_id = local_id
        self._replay_unlocked()

    def _replay_unlocked(self) -> None:
        for event in self._log.iter_all():
            self._replay_one(event)

    def _index_event(self, event: Event) -> None:
        """Record seen id + local seq without projecting (events covered by snapshot)."""
        self._seen_event_ids.add(event.id)
        if event.device_id == self._local_device_id:
            self._event_seq = max(self._event_seq, int(event.seq))

    def _replay_one(self, event: Event) -> None:
        if event.device_id == self._local_device_id:
            if not self._verify(event, self._local_public_key_pem):
                raise InvalidSignature("event signature mismatch")
            self._event_seq = max(self._event_seq, int(event.seq))
        else:
            if event.device_id in self._catalog.unpaired_device_ids:
                self._seen_event_ids.add(event.id)
                return
            author = self._catalog.devices.get(event.device_id)
            # Unknown author: still apply; event was verified when ingested.
            if author is not None and not self._verify(event, author.public_key_pem):
                raise InvalidSignature("event signature mismatch")
        self._seen_event_ids.add(event.id)
        apply_catalog_event(
            self._catalog,
            event,
            local_device_id=self._local_device_id,
            now=self._clock(),
        )

    def _write_snapshot(self) -> None:
        if self._store is None:
            return
        blob = dump_catalog_snapshot(self._catalog)
        self._store.write_snapshot(
            blob=blob,
            projection_version=PROJECTION_VERSION,
            tip_rowid=self._log.max_rowid(),
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
