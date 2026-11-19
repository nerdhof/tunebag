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
