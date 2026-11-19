"""CatalogJournal seam: local append, replay, hold/export atomicity."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from uuid import UUID, uuid4

from tunebag.catalog_journal import CatalogJournal
from tunebag.domain import Platform
from tunebag.events import Event, EventLog, EventType
from tunebag.projection import CatalogState, LocalEffects


def _artist_payload(artist_id: UUID) -> dict:
    return {
        "id": str(artist_id),
        "platform": Platform.SOUNDCLOUD.value,
        "platform_id": "artist-1",
        "name": "DJ Example",
        "url": "https://example.com/artist",
    }


def _make_journal(
    *,
    catalog: CatalogState | None = None,
    log: EventLog | None = None,
    local_device_id: UUID | None = None,
    on_applied=None,
    clock=None,
) -> tuple[CatalogJournal, CatalogState, EventLog, list[tuple[Event, LocalEffects]], UUID]:
    device_id = local_device_id or uuid4()
    state = catalog or CatalogState()
    event_log = log or EventLog()
    applied: list[tuple[Event, LocalEffects]] = []

    def _on_applied(event: Event, effects: LocalEffects) -> None:
        applied.append((event, effects))
        if on_applied is not None:
            on_applied(event, effects)

    journal = CatalogJournal(
        catalog=state,
        log=event_log,
        local_device_id=device_id,
        local_public_key_pem="local-pem",
        clock=clock or (lambda: datetime(2024, 1, 1, 12, 0, 0)),
        sign=lambda event: "sig",
        verify=lambda event, pem: True,
        on_applied=_on_applied,
    )
    return journal, state, event_log, applied, device_id


def test_append_local_updates_catalog_and_calls_on_applied() -> None:
    journal, catalog, log, applied, _device_id = _make_journal()
    artist_id = uuid4()

    event = journal.append_local(EventType.ARTIST_ADDED, _artist_payload(artist_id))

    assert artist_id in catalog.artists
    assert catalog.artists[artist_id].name == "DJ Example"
    assert event.signature == "sig"
    assert event.seq == 1
    assert len(log.all()) == 1
    assert len(applied) == 1
    assert applied[0][0].id == event.id


def test_replay_rebuilds_catalog_without_on_applied() -> None:
    device_id = uuid4()
    artist_id = uuid4()
    t0 = datetime(2024, 1, 1, 12, 0, 0)
    durable = EventLog()
    seed = Event(
        type=EventType.ARTIST_ADDED,
        device_id=device_id,
        created_at=t0,
        seq=3,
        payload=_artist_payload(artist_id),
        signature="sig",
    )
    durable.append(seed)

    cold = CatalogState()
    journal, catalog, _log, applied, _ = _make_journal(
        catalog=cold,
        log=durable,
        local_device_id=device_id,
    )

    journal.replay()

    assert artist_id in catalog.artists
    assert catalog.artists[artist_id].name == "DJ Example"
    assert applied == []
    # Local seq restored so the next append continues monotonically.
    next_event = journal.append_local(
        EventType.ARTIST_ADDED,
        _artist_payload(uuid4()),
    )
    assert next_event.seq == 4


def _foreign_event(
    *,
    event_type: EventType,
    author_id: UUID,
    payload: dict,
    created_at: datetime | None = None,
    seq: int = 1,
    signature: str = "sig",
) -> Event:
    return Event(
        type=event_type,
        device_id=author_id,
        created_at=created_at or datetime(2024, 1, 1, 12, 0, 0),
        seq=seq,
        payload=payload,
        signature=signature,
    )


def _pair_payload(device_id: UUID, *, name: str = "peer") -> dict:
    return {
        "id": str(device_id),
        "name": name,
        "public_key_pem": f"pem-{device_id}",
        "priority": 10,
    }


def test_ingest_foreign_buffers_unknown_author_until_paired() -> None:
    journal, catalog, log, applied, _local_id = _make_journal()
    author_id = uuid4()
    artist_id = uuid4()
    foreign = _foreign_event(
        event_type=EventType.ARTIST_ADDED,
        author_id=author_id,
        payload=_artist_payload(artist_id),
    )

    journal.ingest_foreign(foreign)

    assert artist_id not in catalog.artists
    assert applied == []
    assert log.all() == []

    pair = journal.append_local(EventType.DEVICE_PAIRED, _pair_payload(author_id))

    assert artist_id in catalog.artists
    assert catalog.artists[artist_id].name == "DJ Example"
    assert foreign.id in {e.id for e in log.all()}
    # Pair Event's on_applied runs after the buffered flush.
    assert [e.id for e, _ in applied] == [foreign.id, pair.id]


def test_ingest_foreign_silently_skips_dedupe_self_and_unpaired() -> None:
    journal, catalog, log, applied, local_id = _make_journal()
    author_id = uuid4()
    journal.append_local(EventType.DEVICE_PAIRED, _pair_payload(author_id))
    applied.clear()

    artist_id = uuid4()
    foreign = _foreign_event(
        event_type=EventType.ARTIST_ADDED,
        author_id=author_id,
        payload=_artist_payload(artist_id),
    )
    journal.ingest_foreign(foreign)
    assert artist_id in catalog.artists
    assert len(applied) == 1

    journal.ingest_foreign(foreign)  # dedupe
    self_authored = _foreign_event(
        event_type=EventType.ARTIST_ADDED,
        author_id=local_id,
        payload=_artist_payload(uuid4()),
    )
    journal.ingest_foreign(self_authored)

    unpaired_id = uuid4()
    catalog.unpaired_device_ids.add(unpaired_id)
    unpaired = _foreign_event(
        event_type=EventType.ARTIST_ADDED,
        author_id=unpaired_id,
        payload=_artist_payload(uuid4()),
    )
    journal.ingest_foreign(unpaired)

    assert len(applied) == 1
    assert len(log.all()) == 2  # pair + first foreign


def test_ingest_foreign_known_author_applies_and_bad_sig_fails_fast() -> None:
    from cryptography.exceptions import InvalidSignature

    catalog = CatalogState()
    log = EventLog()
    applied: list[tuple[Event, LocalEffects]] = []
    local_id = uuid4()
    author_id = uuid4()
    verify_ok = {"value": True}

    journal = CatalogJournal(
        catalog=catalog,
        log=log,
        local_device_id=local_id,
        local_public_key_pem="local-pem",
        clock=lambda: datetime(2024, 1, 1, 12, 0, 0),
        sign=lambda event: "sig",
        verify=lambda event, pem: verify_ok["value"],
        on_applied=lambda event, effects: applied.append((event, effects)),
    )
    journal.append_local(EventType.DEVICE_PAIRED, _pair_payload(author_id))
    applied.clear()

    artist_id = uuid4()
    foreign = _foreign_event(
        event_type=EventType.ARTIST_ADDED,
        author_id=author_id,
        payload=_artist_payload(artist_id),
    )
    journal.ingest_foreign(foreign)
    assert artist_id in catalog.artists
    assert [e.id for e, _ in applied] == [foreign.id]

    verify_ok["value"] = False
    bad = _foreign_event(
        event_type=EventType.ARTIST_ADDED,
        author_id=author_id,
        payload=_artist_payload(uuid4()),
        signature="bad",
    )
    try:
        journal.ingest_foreign(bad)
        raise AssertionError("expected InvalidSignature")
    except InvalidSignature:
        pass
    assert bad.id not in {e.id for e in log.all()}


def test_unpair_drops_buffered_events_so_re_pair_does_not_apply_them() -> None:
    journal, catalog, log, _applied, _local_id = _make_journal()
    author_id = uuid4()
    artist_id = uuid4()
    foreign = _foreign_event(
        event_type=EventType.ARTIST_ADDED,
        author_id=author_id,
        payload=_artist_payload(artist_id),
    )
    journal.ingest_foreign(foreign)
    journal.append_local(EventType.DEVICE_UNPAIRED, {"id": str(author_id)})

    journal.append_local(EventType.DEVICE_PAIRED, _pair_payload(author_id))

    assert artist_id not in catalog.artists
    assert foreign.id not in {e.id for e in log.all()}


def test_hold_export_never_sees_half_written_section() -> None:
    journal, _catalog, _log, _applied, _device_id = _make_journal()
    first_id = uuid4()
    second_id = uuid4()
    first_appended = threading.Event()
    errors: list[BaseException] = []
    snapshots: list[int] = []

    def writer() -> None:
        try:
            with journal.hold():
                journal.append_local(EventType.ARTIST_ADDED, _artist_payload(first_id))
                first_appended.set()
                time.sleep(0.05)
                journal.append_local(
                    EventType.ARTIST_ADDED, _artist_payload(second_id)
                )
        except BaseException as exc:  # noqa: BLE001 — surface to main thread
            errors.append(exc)

    def reader() -> None:
        try:
            first_appended.wait(timeout=1.0)
            snapshots.append(len(journal.export()))
        except BaseException as exc:  # noqa: BLE001 — surface to main thread
            errors.append(exc)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2.0)

    assert errors == []
    assert snapshots == [2]
    assert {e.payload["id"] for e in journal.export()} == {
        str(first_id),
        str(second_id),
    }
