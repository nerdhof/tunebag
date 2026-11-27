"""SQLite durable bag: migration, hold txn, snapshot/tail boot, cursor pull."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from tunebag.agent import DeviceAgent
from tunebag.catalog_journal import CatalogJournal
from tunebag.domain import Platform
from tunebag.durable_store import (
    DB_FILENAME,
    EVENTS_JSONL,
    IDENTITY_JSON,
    LOCATOR_HINTS_JSON,
    DurableStore,
)
from tunebag.events import Event, EventLog, EventType
from tunebag.pairing import PersistedIdentity, generate_identity, save_persisted_identity
from tunebag.projection import PROJECTION_VERSION, CatalogState
from tunebag.source import FakeSource
from tunebag.web import create_peer_app


def _artist_payload(artist_id) -> dict:
    return {
        "id": str(artist_id),
        "platform": Platform.SOUNDCLOUD.value,
        "platform_id": "artist-1",
        "name": "DJ Example",
        "url": "https://example.com/artist",
    }


def test_migrates_jsonl_and_sidecars_then_renames_aside(tmp_path: Path) -> None:
    data_dir = tmp_path / "legacy"
    data_dir.mkdir()
    identity = generate_identity("legacy")
    device_id = uuid4()
    save_persisted_identity(
        data_dir / IDENTITY_JSON,
        PersistedIdentity(
            device_id=device_id,
            private_key_pem=identity.private_key_pem,
            public_key_pem=identity.public_key_pem,
            tls_cert_pem=identity.tls_cert_pem,
            tls_key_pem=identity.tls_key_pem,
        ),
    )
    peer_id = uuid4()
    (data_dir / LOCATOR_HINTS_JSON).write_text(
        json.dumps({str(peer_id): "http://peer.example:8765"}) + "\n"
    )
    event = Event(
        type=EventType.ARTIST_ADDED,
        device_id=device_id,
        seq=1,
        payload=_artist_payload(uuid4()),
        signature="sig",
    )
    (data_dir / EVENTS_JSONL).write_text(event.model_dump_json() + "\n")

    store = DurableStore(data_dir / DB_FILENAME)

    assert store.event_count() == 1
    loaded = store.load_identity()
    assert loaded is not None
    assert loaded.device_id == device_id
    assert store.load_locator_hints()[peer_id] == "http://peer.example:8765"
    assert not (data_dir / EVENTS_JSONL).exists()
    assert (data_dir / f"{EVENTS_JSONL}.migrated").is_file()
    assert (data_dir / f"{IDENTITY_JSON}.migrated").is_file()
    assert (data_dir / f"{LOCATOR_HINTS_JSON}.migrated").is_file()
    store.close()


def test_hold_rolls_back_partial_section(tmp_path: Path) -> None:
    store = DurableStore(tmp_path / DB_FILENAME)
    log = EventLog(store=store)
    catalog = CatalogState()
    applied: list = []

    journal = CatalogJournal(
        catalog=catalog,
        log=log,
        local_device_id=uuid4(),
        local_public_key_pem="pem",
        clock=lambda: __import__("datetime").datetime(2024, 1, 1),
        sign=lambda event: "sig",
        verify=lambda event, pem: True,
        on_applied=lambda event, effects: applied.append(event),
        store=store,
    )
    first_id = uuid4()
    second_id = uuid4()

    try:
        with journal.hold():
            journal.append_local(EventType.ARTIST_ADDED, _artist_payload(first_id))
            assert second_id  # keep intent of two-id section for readers
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert store.event_count() == 0
    assert first_id not in catalog.artists
    store.close()


def test_hold_commits_nested_appends_together(tmp_path: Path) -> None:
    store = DurableStore(tmp_path / DB_FILENAME)
    log = EventLog(store=store)
    catalog = CatalogState()
    device_id = uuid4()
    journal = CatalogJournal(
        catalog=catalog,
        log=log,
        local_device_id=device_id,
        local_public_key_pem="pem",
        clock=lambda: __import__("datetime").datetime(2024, 1, 1),
        sign=lambda event: "sig",
        verify=lambda event, pem: True,
        on_applied=lambda event, effects: None,
        store=store,
    )
    a = uuid4()
    b = uuid4()
    with journal.hold():
        journal.append_local(EventType.ARTIST_ADDED, _artist_payload(a))
        journal.append_local(EventType.ARTIST_ADDED, _artist_payload(b))

    assert store.event_count() == 2
    assert a in catalog.artists and b in catalog.artists
    store.close()


def test_snapshot_tail_boot_applies_only_new_events(tmp_path: Path) -> None:
    data_dir = tmp_path / "laptop"
    source = FakeSource()
    first = DeviceAgent("laptop", source=source, data_dir=data_dir)
    mix = first.add_mix(
        title="Seed",
        url="https://example.com/seed",
        duration_seconds=100,
        platform=Platform.SOUNDCLOUD,
        platform_id="seed-1",
        artist_name="DJ Seed",
    )
    assert first._store is not None
    tip_after_seed = first._store.get_snapshot_tip_rowid()
    assert tip_after_seed is not None and tip_after_seed > 0

    # Append one more event without rewriting snapshot tip (simulate crash after
    # commit before write-through by freezing tip, then writing via store).
    extra = Event(
        type=EventType.MIX_RATED,
        device_id=first.device_id,
        seq=first._journal._event_seq + 1,
        payload={"mix_id": str(mix.id), "stars": 5},
        signature="sig",
    )
    # Sign properly so boot verify passes.
    extra.signature = first._sign(extra)
    first._store.append_event(extra)
    # Tip still points at pre-extra watermark.
    first._store.put_snapshot_meta(
        projection_version=PROJECTION_VERSION,
        tip_rowid=tip_after_seed,
    )

    second = DeviceAgent("laptop", source=FakeSource(), data_dir=data_dir)
    assert mix.id in second.catalog.mixes
    assert second.catalog.mixes[mix.id].stars is not None
    assert int(second.catalog.mixes[mix.id].stars) == 5


def test_cursor_pull_returns_only_newer_author_events(tmp_path: Path) -> None:
    laptop = DeviceAgent("laptop", data_dir=tmp_path / "laptop")
    phone = DeviceAgent("phone", data_dir=tmp_path / "phone")
    laptop.connect(phone)
    phone.pair(laptop.pairing_payload())
    laptop.sync(fill=False)
    phone.sync(fill=False)

    # Capture before add_mix: auto-sync would otherwise advance phone's watermarks.
    cursors = phone.event_cursors()
    laptop.add_mix(
        title="Only on laptop",
        url="https://example.com/only",
        duration_seconds=60,
        platform=Platform.SOUNDCLOUD,
        platform_id="only-1",
        artist_name="DJ Only",
    )
    app = create_peer_app(laptop)
    client = TestClient(app)
    response = client.post("/api/events/pull", json={"cursors": cursors})
    assert response.status_code == 200
    assert "application/x-ndjson" in response.headers["content-type"]
    lines = [line for line in response.text.splitlines() if line.strip()]
    assert lines, "expected at least the new laptop-authored events"
    events = [Event.model_validate_json(line) for line in lines]
    assert all(
        str(event.device_id) not in cursors or event.seq > cursors[str(event.device_id)]
        for event in events
    )
    assert any(event.type is EventType.MIX_ADDED for event in events)

    full = client.get("/api/events")
    assert full.status_code == 200
    full_lines = [line for line in full.text.splitlines() if line.strip()]
    assert len(full_lines) >= len(lines)


def test_agent_uses_sqlite_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "d"
    agent = DeviceAgent("d", data_dir=data_dir)
    agent.seed_default_intents_if_empty()
    assert (data_dir / DB_FILENAME).is_file()
    assert not (data_dir / EVENTS_JSONL).exists()
    restarted = DeviceAgent("d", data_dir=data_dir)
    assert restarted.intents()[0].name == "Explore"
