"""SQLite durable bag: events, identity, locator hints, disposable Catalog snapshot."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from tunebag.device_tls import generate_device_tls_material
from tunebag.events import Event
from tunebag.pairing import PersistedIdentity

DB_FILENAME = "tunebag.sqlite"
EVENTS_JSONL = "events.jsonl"
IDENTITY_JSON = "identity.json"
LOCATOR_HINTS_JSON = "locator_hints.json"

META_DEVICE_ID = "device_id"
META_PRIVATE_KEY_PEM = "private_key_pem"
META_PUBLIC_KEY_PEM = "public_key_pem"
META_TLS_CERT_PEM = "tls_cert_pem"
META_TLS_KEY_PEM = "tls_key_pem"
META_PROJECTION_VERSION = "projection_version"
META_SNAPSHOT_TIP_ROWID = "snapshot_tip_rowid"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS locator_hints (
    device_id TEXT PRIMARY KEY,
    url TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT NOT NULL UNIQUE,
    device_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_device_seq ON events (device_id, seq);
CREATE TABLE IF NOT EXISTS catalog_snapshot (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    blob BLOB NOT NULL
);
"""


class DurableStore:
    """One-file SQLite bag with WAL, nestable write transactions, and migration."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._txn_depth = 0
        self._conn = sqlite3.connect(
            str(path),
            check_same_thread=False,
            isolation_level=None,  # manual BEGIN/COMMIT
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self.migrate_legacy_sidecars_if_needed()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- transactions -----------------------------------------------------

    def begin(self) -> None:
        with self._lock:
            if self._txn_depth == 0:
                self._conn.execute("BEGIN IMMEDIATE")
            self._txn_depth += 1

    def commit(self) -> None:
        with self._lock:
            if self._txn_depth == 0:
                return
            self._txn_depth -= 1
            if self._txn_depth == 0:
                self._conn.execute("COMMIT")

    def rollback(self) -> None:
        with self._lock:
            if self._txn_depth == 0:
                return
            self._txn_depth = 0
            self._conn.execute("ROLLBACK")

    @property
    def in_transaction(self) -> bool:
        return self._txn_depth > 0

    @contextmanager
    def write_txn(self) -> Iterator[None]:
        """Begin a write txn if not already nested; commit/rollback on exit."""
        with self._lock:
            owned = self._txn_depth == 0
            if owned:
                self.begin()
            try:
                yield
                if owned:
                    self.commit()
            except BaseException:
                if owned:
                    self.rollback()
                raise

    # --- meta / identity --------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
            return None if row is None else str(row[0])

    def set_meta(self, key: str, value: str) -> None:
        with self._lock, self.write_txn():
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def delete_meta(self, key: str) -> None:
        with self._lock, self.write_txn():
            self._conn.execute("DELETE FROM meta WHERE key = ?", (key,))

    def load_identity(self) -> PersistedIdentity | None:
        device_id = self.get_meta(META_DEVICE_ID)
        private_pem = self.get_meta(META_PRIVATE_KEY_PEM)
        public_pem = self.get_meta(META_PUBLIC_KEY_PEM)
        if not device_id or not private_pem or not public_pem:
            return None
        tls_cert = self.get_meta(META_TLS_CERT_PEM)
        tls_key = self.get_meta(META_TLS_KEY_PEM)
        identity = PersistedIdentity(
            device_id=UUID(device_id),
            private_key_pem=private_pem,
            public_key_pem=public_pem,
            tls_cert_pem=tls_cert or "",
            tls_key_pem=tls_key or "",
        )
        if not tls_cert or not tls_key:
            tls = generate_device_tls_material(common_name=f"tunebag:{device_id}")
            identity = PersistedIdentity(
                device_id=UUID(device_id),
                private_key_pem=private_pem,
                public_key_pem=public_pem,
                tls_cert_pem=tls.cert_pem,
                tls_key_pem=tls.key_pem,
            )
            # Persist the upgrade so a second load does not mint a new cert.
            self.save_identity(identity)
        return identity

    def save_identity(self, identity: PersistedIdentity) -> None:
        with self._lock, self.write_txn():
            for key, value in (
                (META_DEVICE_ID, str(identity.device_id)),
                (META_PRIVATE_KEY_PEM, identity.private_key_pem),
                (META_PUBLIC_KEY_PEM, identity.public_key_pem),
                (META_TLS_CERT_PEM, identity.tls_cert_pem),
                (META_TLS_KEY_PEM, identity.tls_key_pem),
            ):
                self._conn.execute(
                    "INSERT INTO meta(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )

    # --- locator hints ----------------------------------------------------

    def load_locator_hints(self) -> dict[UUID, str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT device_id, url FROM locator_hints"
            ).fetchall()
        return {UUID(str(device_id)): str(url) for device_id, url in rows}

    def save_locator_hints(self, hints: dict[UUID, str]) -> None:
        with self._lock, self.write_txn():
            self._conn.execute("DELETE FROM locator_hints")
            self._conn.executemany(
                "INSERT INTO locator_hints(device_id, url) VALUES(?, ?)",
                [
                    (str(device_id), url)
                    for device_id, url in sorted(hints.items(), key=lambda i: str(i[0]))
                ],
            )

    # --- events -----------------------------------------------------------

    def event_count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()
            return int(row[0]) if row else 0

    def is_empty(self) -> bool:
        return self.event_count() == 0

    def append_event(self, event: Event) -> int:
        """Insert one Event; return its rowid. Caller manages write_txn nesting."""
        payload = event.model_dump_json()
        with self._lock, self.write_txn():
            cur = self._conn.execute(
                "INSERT INTO events(id, device_id, seq, payload_json) "
                "VALUES(?, ?, ?, ?)",
                (str(event.id), str(event.device_id), int(event.seq), payload),
            )
            return int(cur.lastrowid)

    def iter_events(self) -> Iterator[Event]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM events ORDER BY rowid"
            ).fetchall()
        for (payload_json,) in rows:
            yield Event.model_validate_json(payload_json)

    def iter_events_with_rowids(self) -> Iterator[tuple[int, Event]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT rowid, payload_json FROM events ORDER BY rowid"
            ).fetchall()
        for rowid, payload_json in rows:
            yield int(rowid), Event.model_validate_json(payload_json)

    def iter_events_since_rowid(self, after_rowid: int) -> Iterator[tuple[int, Event]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT rowid, payload_json FROM events "
                "WHERE rowid > ? ORDER BY rowid",
                (after_rowid,),
            ).fetchall()
        for rowid, payload_json in rows:
            yield int(rowid), Event.model_validate_json(payload_json)

    def iter_events_after_cursors(
        self, cursors: dict[str, int]
    ) -> Iterator[Event]:
        """Yield events whose author is missing from cursors or seq > cursor."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT device_id, seq, payload_json FROM events ORDER BY rowid"
            ).fetchall()
        for device_id, seq, payload_json in rows:
            key = str(device_id)
            if key in cursors and int(seq) <= int(cursors[key]):
                continue
            yield Event.model_validate_json(payload_json)

    def max_seq_by_device(self) -> dict[UUID, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT device_id, MAX(seq) FROM events GROUP BY device_id"
            ).fetchall()
        return {UUID(str(device_id)): int(seq) for device_id, seq in rows}

    def max_rowid(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT MAX(rowid) FROM events").fetchone()
            if row is None or row[0] is None:
                return 0
            return int(row[0])

    # --- catalog snapshot -------------------------------------------------

    def get_snapshot_blob(self) -> bytes | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT blob FROM catalog_snapshot WHERE id = 1"
            ).fetchone()
            return None if row is None else bytes(row[0])

    def put_snapshot_blob(self, blob: bytes) -> None:
        with self._lock, self.write_txn():
            self._conn.execute(
                "INSERT INTO catalog_snapshot(id, blob) VALUES(1, ?) "
                "ON CONFLICT(id) DO UPDATE SET blob = excluded.blob",
                (blob,),
            )

    def get_projection_version(self) -> int | None:
        raw = self.get_meta(META_PROJECTION_VERSION)
        if raw is None:
            return None
        return int(raw)

    def get_snapshot_tip_rowid(self) -> int | None:
        raw = self.get_meta(META_SNAPSHOT_TIP_ROWID)
        if raw is None:
            return None
        return int(raw)

    def put_snapshot_meta(self, *, projection_version: int, tip_rowid: int) -> None:
        with self._lock, self.write_txn():
            for key, value in (
                (META_PROJECTION_VERSION, str(projection_version)),
                (META_SNAPSHOT_TIP_ROWID, str(tip_rowid)),
            ):
                self._conn.execute(
                    "INSERT INTO meta(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )

    def write_snapshot(self, *, blob: bytes, projection_version: int, tip_rowid: int) -> None:
        with self._lock, self.write_txn():
            self._conn.execute(
                "INSERT INTO catalog_snapshot(id, blob) VALUES(1, ?) "
                "ON CONFLICT(id) DO UPDATE SET blob = excluded.blob",
                (blob,),
            )
            for key, value in (
                (META_PROJECTION_VERSION, str(projection_version)),
                (META_SNAPSHOT_TIP_ROWID, str(tip_rowid)),
            ):
                self._conn.execute(
                    "INSERT INTO meta(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )

    def clear_snapshot(self) -> None:
        with self._lock, self.write_txn():
            self._conn.execute("DELETE FROM catalog_snapshot")
            self._conn.execute(
                "DELETE FROM meta WHERE key IN (?, ?)",
                (META_PROJECTION_VERSION, META_SNAPSHOT_TIP_ROWID),
            )

    # --- migration --------------------------------------------------------

    def migrate_legacy_sidecars_if_needed(self) -> bool:
        """Import JSONL/JSON sidecars when the DB has no events and no identity.

        Renames imported files to ``*.migrated`` after a verified import.
        Returns True if a migration ran.
        """
        data_dir = self.path.parent
        events_path = data_dir / EVENTS_JSONL
        identity_path = data_dir / IDENTITY_JSON
        hints_path = data_dir / LOCATOR_HINTS_JSON

        has_legacy = (
            events_path.is_file() or identity_path.is_file() or hints_path.is_file()
        )
        if not has_legacy:
            return False

        # Only migrate into an empty bag (no events and no identity meta).
        if self.event_count() > 0 or self.load_identity() is not None:
            return False

        imported_events: list[Event] = []
        if events_path.is_file():
            for line in events_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                imported_events.append(Event.model_validate_json(line))

        identity: PersistedIdentity | None = None
        if identity_path.is_file():
            raw = json.loads(identity_path.read_text(encoding="utf-8"))
            device_id = UUID(raw["device_id"])
            tls_cert = raw.get("tls_cert_pem")
            tls_key = raw.get("tls_key_pem")
            if not tls_cert or not tls_key:
                tls = generate_device_tls_material(common_name=f"tunebag:{device_id}")
                tls_cert = tls.cert_pem
                tls_key = tls.key_pem
            identity = PersistedIdentity(
                device_id=device_id,
                private_key_pem=raw["private_key_pem"],
                public_key_pem=raw["public_key_pem"],
                tls_cert_pem=tls_cert,
                tls_key_pem=tls_key,
            )

        hints: dict[UUID, str] = {}
        if hints_path.is_file():
            raw_hints = json.loads(hints_path.read_text(encoding="utf-8"))
            if isinstance(raw_hints, dict):
                for device_id, locator in raw_hints.items():
                    if isinstance(locator, str) and locator:
                        hints[UUID(device_id)] = locator

        with self._lock, self.write_txn():
            for event in imported_events:
                self._conn.execute(
                    "INSERT INTO events(id, device_id, seq, payload_json) "
                    "VALUES(?, ?, ?, ?)",
                    (
                        str(event.id),
                        str(event.device_id),
                        int(event.seq),
                        event.model_dump_json(),
                    ),
                )
            if identity is not None:
                for key, value in (
                    (META_DEVICE_ID, str(identity.device_id)),
                    (META_PRIVATE_KEY_PEM, identity.private_key_pem),
                    (META_PUBLIC_KEY_PEM, identity.public_key_pem),
                    (META_TLS_CERT_PEM, identity.tls_cert_pem),
                    (META_TLS_KEY_PEM, identity.tls_key_pem),
                ):
                    self._conn.execute(
                        "INSERT INTO meta(key, value) VALUES(?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, value),
                    )
            if hints:
                self._conn.executemany(
                    "INSERT INTO locator_hints(device_id, url) VALUES(?, ?)",
                    [(str(device_id), url) for device_id, url in hints.items()],
                )

        # Verify round-trip before renaming legacy files aside.
        if len(imported_events) != self.event_count():
            raise RuntimeError("legacy events migration count mismatch")
        if identity is not None:
            loaded = self.load_identity()
            if loaded is None or loaded.device_id != identity.device_id:
                raise RuntimeError("legacy identity migration failed verification")
        if hints and self.load_locator_hints() != hints:
            raise RuntimeError("legacy locator hints migration failed verification")

        for path in (events_path, identity_path, hints_path):
            if path.is_file():
                aside = path.with_name(path.name + ".migrated")
                path.rename(aside)
        return True


def open_durable_store(data_dir: Path) -> DurableStore:
    return DurableStore(data_dir / DB_FILENAME)
