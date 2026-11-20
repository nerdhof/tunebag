"""SequenceProvisioner seam: need-rebuild decisions and Event drafts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from tunebag.catalog_journal import CatalogJournal
from tunebag.domain import (
    Assignment,
    DeviceHours,
    Intent,
    Mix,
    Platform,
    Sequence,
    SequenceEntry,
    StarBucket,
    Stars,
)
from tunebag.event_payloads import encode_intent
from tunebag.events import EventLog, EventType
from tunebag.projection import CatalogState
from tunebag.sequence_provision import SequenceProvisioner


def _mix(*, duration_seconds: int = 3600, title: str = "Set") -> Mix:
    return Mix(
        artist_id=uuid4(),
        platform=Platform.SOUNDCLOUD,
        platform_id=title.lower().replace(" ", "-"),
        title=title,
        url=f"https://example.com/{title}",
        duration_seconds=duration_seconds,
        tags=["set"],
        stars=Stars.FIVE,
    )


def _intent_with_hours(
    device_id: UUID,
    *,
    budget_seconds: int = 2 * 3600,
    seed: int = 1,
) -> Intent:
    return Intent(
        name="Explore",
        tags=["set"],
        seed=seed,
        device_hours=[DeviceHours(device_id=device_id, budget_seconds=budget_seconds)],
    )


def test_needs_rebuild_when_assignment_missing() -> None:
    device_id = uuid4()
    mix = _mix()
    intent = _intent_with_hours(device_id)
    catalog = CatalogState()
    catalog.add_mix(mix)
    catalog.upsert_intent(intent)

    assert SequenceProvisioner().needs_rebuild(
        intent, catalog, include_underfilled=False
    )


def test_needs_rebuild_false_when_budget_is_zero() -> None:
    intent = Intent(name="Idle", tags=["set"], seed=1, device_hours=[])
    catalog = CatalogState()
    catalog.upsert_intent(intent)

    assert not SequenceProvisioner().needs_rebuild(
        intent, catalog, include_underfilled=True
    )


def test_needs_rebuild_when_assignment_mix_ids_empty_but_sequence_has_entries() -> None:
    """Explore seed leaves mix_ids=[]; a peer-filled Sequence must still rebuild."""
    device_id = uuid4()
    mix = _mix()
    intent = _intent_with_hours(device_id)
    catalog = CatalogState()
    catalog.add_mix(mix)
    catalog.upsert_intent(intent)
    catalog.set_sequence(
        Sequence(
            intent_id=intent.id,
            entries=[
                SequenceEntry(mix_id=mix.id, position=0, bucket=StarBucket.FIVE),
            ],
        )
    )
    catalog.set_assignment(
        Assignment(
            intent_id=intent.id,
            device_id=device_id,
            mix_ids=[],
            budget_seconds=intent.device_hours[0].budget_seconds,
        )
    )

    assert SequenceProvisioner().needs_rebuild(
        intent, catalog, include_underfilled=False
    )


def test_needs_rebuild_underfilled_when_new_mixes_would_change_sequence() -> None:
    device_id = uuid4()
    first = _mix(title="First")
    second = _mix(title="Second")
    intent = _intent_with_hours(device_id, budget_seconds=2 * 3600)
    catalog = CatalogState()
    catalog.add_mix(first)
    catalog.add_mix(second)
    catalog.upsert_intent(intent)
    # Current sequence is short of budget (1h of 2h) with only first mix.
    catalog.set_sequence(
        Sequence(
            intent_id=intent.id,
            entries=[
                SequenceEntry(mix_id=first.id, position=0, bucket=StarBucket.FIVE),
            ],
        )
    )
    catalog.set_assignment(
        Assignment(
            intent_id=intent.id,
            device_id=device_id,
            mix_ids=[first.id],
            budget_seconds=2 * 3600,
        )
    )

    assert SequenceProvisioner().needs_rebuild(
        intent, catalog, include_underfilled=True
    )


def test_needs_rebuild_false_when_underfilled_but_rebuild_unchanged() -> None:
    """No new eligible mixes → under-budget Explore must not rebuild forever."""
    device_id = uuid4()
    mix = _mix(title="Only")
    intent = _intent_with_hours(device_id, budget_seconds=4 * 3600)
    catalog = CatalogState()
    catalog.add_mix(mix)
    catalog.upsert_intent(intent)
    catalog.set_sequence(
        Sequence(
            intent_id=intent.id,
            entries=[
                SequenceEntry(mix_id=mix.id, position=0, bucket=StarBucket.FIVE),
            ],
        )
    )
    catalog.set_assignment(
        Assignment(
            intent_id=intent.id,
            device_id=device_id,
            mix_ids=[mix.id],
            budget_seconds=4 * 3600,
        )
    )

    assert not SequenceProvisioner().needs_rebuild(
        intent, catalog, include_underfilled=True
    )


def test_needs_rebuild_skips_underfilled_when_flag_false() -> None:
    device_id = uuid4()
    first = _mix(title="First")
    second = _mix(title="Second")
    intent = _intent_with_hours(device_id, budget_seconds=2 * 3600)
    catalog = CatalogState()
    catalog.add_mix(first)
    catalog.add_mix(second)
    catalog.upsert_intent(intent)
    catalog.set_sequence(
        Sequence(
            intent_id=intent.id,
            entries=[
                SequenceEntry(mix_id=first.id, position=0, bucket=StarBucket.FIVE),
            ],
        )
    )
    catalog.set_assignment(
        Assignment(
            intent_id=intent.id,
            device_id=device_id,
            mix_ids=[first.id],
            budget_seconds=2 * 3600,
        )
    )

    assert not SequenceProvisioner().needs_rebuild(
        intent, catalog, include_underfilled=False
    )


def test_provision_fillup_keeps_queued_order_and_drops_played() -> None:
    device_id = uuid4()
    first = _mix(title="First")
    second = _mix(title="Second")
    third = _mix(title="Third")
    first.played = True
    intent = _intent_with_hours(device_id, budget_seconds=2 * 3600, seed=5)
    catalog = CatalogState()
    for mix in (first, second, third):
        catalog.add_mix(mix)
    catalog.upsert_intent(intent)
    catalog.set_sequence(
        Sequence(
            intent_id=intent.id,
            entries=[
                SequenceEntry(mix_id=first.id, position=0, bucket=StarBucket.FIVE),
                SequenceEntry(mix_id=second.id, position=1, bucket=StarBucket.FIVE),
            ],
        )
    )

    drafts = SequenceProvisioner().provision_fillup(intent, catalog)
    seq = next(d for d in drafts if d.type is EventType.SEQUENCE_BUILT)
    entry_ids = [UUID(e["mix_id"]) for e in seq.payload["entries"]]
    assert first.id not in entry_ids
    assert entry_ids[0] == second.id
    assert len(entry_ids) == 2
    assert entry_ids[1] == third.id


def test_provision_drafts_sequence_and_assignment() -> None:
    device_id = uuid4()
    mixes = [_mix(title=f"Mix {i}") for i in range(3)]
    intent = _intent_with_hours(device_id, budget_seconds=2 * 3600, seed=7)
    catalog = CatalogState()
    for mix in mixes:
        catalog.add_mix(mix)
    catalog.upsert_intent(intent)

    drafts = SequenceProvisioner().provision(intent, catalog)

    assert [d.type for d in drafts] == [
        EventType.SEQUENCE_BUILT,
        EventType.ASSIGNMENT_SET,
    ]
    seq_payload = drafts[0].payload
    assert seq_payload["intent_id"] == str(intent.id)
    entry_ids = [UUID(e["mix_id"]) for e in seq_payload["entries"]]
    assert len(entry_ids) == 2  # 2h budget, 1h mixes
    asg = drafts[1].payload
    assert asg["device_id"] == str(device_id)
    assert asg["budget_seconds"] == 2 * 3600
    assert [UUID(m) for m in asg["mix_ids"]] == entry_ids


def test_provision_clears_stale_device_assignment() -> None:
    active = uuid4()
    stale = uuid4()
    mix = _mix()
    intent = _intent_with_hours(active, budget_seconds=3600)
    catalog = CatalogState()
    catalog.add_mix(mix)
    catalog.upsert_intent(intent)
    catalog.set_assignment(
        Assignment(
            intent_id=intent.id,
            device_id=stale,
            mix_ids=[mix.id],
            budget_seconds=3600,
        )
    )

    drafts = SequenceProvisioner().provision(intent, catalog)

    assert drafts[0].type is EventType.ASSIGNMENT_CLEARED
    assert drafts[0].payload == {
        "intent_id": str(intent.id),
        "device_id": str(stale),
    }
    assert EventType.SEQUENCE_BUILT in {d.type for d in drafts}
    assert EventType.ASSIGNMENT_SET in {d.type for d in drafts}


def test_caller_appends_provision_drafts_under_hold_to_event_log() -> None:
    """Caller commits drafts via CatalogJournal; Catalog gets Sequence + Assignment."""
    device_id = uuid4()
    mixes = [_mix(title=f"Mix {i}") for i in range(3)]
    intent = _intent_with_hours(device_id, budget_seconds=2 * 3600, seed=3)
    catalog = CatalogState()
    log = EventLog()
    for mix in mixes:
        catalog.add_mix(mix)
    journal = CatalogJournal(
        catalog=catalog,
        log=log,
        local_device_id=device_id,
        local_public_key_pem="pem",
        clock=lambda: datetime(2024, 6, 1, 12, 0, 0),
        sign=lambda event: "sig",
        verify=lambda event, pem: True,
        on_applied=lambda event, effects: None,
    )
    provisioner = SequenceProvisioner()

    with journal.hold():
        journal.append_local(EventType.INTENT_UPSERTED, encode_intent(intent))
        for draft in provisioner.provision(intent, catalog):
            journal.append_local(draft.type, draft.payload)

    types = [event.type for event in log.all()]
    assert EventType.INTENT_UPSERTED in types
    assert EventType.SEQUENCE_BUILT in types
    assert EventType.ASSIGNMENT_SET in types
    assert intent.id in catalog.sequences
    assert len(catalog.sequences[intent.id].entries) == 2
    assignment = catalog.assignments[(intent.id, device_id)]
    assert len(assignment.mix_ids) == 2
