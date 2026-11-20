"""Unit tests for Catalog maintenance policy (fake ports, no DeviceAgent)."""

from __future__ import annotations

from uuid import uuid4

from tunebag.domain import Intent
from tunebag.maintenance import (
    CatalogChange,
    CatalogChangeReason,
    after_catalog_change,
)


class FakeActions:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.rebuild_unfilled_result = False

    def rebuild_all_sequences(self) -> None:
        self.calls.append(("rebuild_all", None))

    def fillup_all_sequences(self) -> None:
        self.calls.append(("fillup_all", None))

    def rebuild_unfilled_sequences(self, *, include_underfilled: bool = True) -> bool:
        self.calls.append(("rebuild_unfilled", include_underfilled))
        return self.rebuild_unfilled_result

    def rebuild_sequence_for_intent(self, intent: Intent) -> None:
        self.calls.append(("rebuild_intent", intent.id))

    def fill_caches(self) -> int:
        self.calls.append(("fill_caches", None))
        return 0

    def request_fill(self) -> bool:
        self.calls.append(("request_fill", None))
        return True

    def prune_unassigned_files(self) -> None:
        self.calls.append(("prune", None))

    def delete_retired_file_if_replaced(self, mix_id) -> None:
        self.calls.append(("retire", mix_id))


def _intent() -> Intent:
    return Intent(name="Test", seed=1)


def test_mark_played_fillups_request_fill_and_retires() -> None:
    actions = FakeActions()
    mix_id = uuid4()
    assert after_catalog_change(
        actions,
        CatalogChange(CatalogChangeReason.MARK_PLAYED, mix_id=mix_id),
    )
    assert actions.calls == [
        ("fillup_all", None),
        ("request_fill", None),
        ("retire", mix_id),
    ]


def test_un_reject_rebuilds_and_request_fill() -> None:
    actions = FakeActions()
    assert after_catalog_change(actions, CatalogChange(CatalogChangeReason.UN_REJECT))
    assert actions.calls == [
        ("rebuild_all", None),
        ("request_fill", None),
    ]


def test_intent_upsert_rebuilds_prunes_and_optionally_fills() -> None:
    actions = FakeActions()
    intent = _intent()
    assert after_catalog_change(
        actions,
        CatalogChange(
            CatalogChangeReason.INTENT_UPSERT,
            intent=intent,
            fill_async=True,
        ),
    )
    assert actions.calls == [
        ("rebuild_intent", intent.id),
        ("prune", None),
        ("request_fill", None),
    ]

    actions = FakeActions()
    after_catalog_change(
        actions,
        CatalogChange(
            CatalogChangeReason.INTENT_UPSERT,
            intent=intent,
            fill_async=False,
        ),
    )
    assert actions.calls == [
        ("rebuild_intent", intent.id),
        ("prune", None),
    ]


def test_intent_delete_only_prunes() -> None:
    actions = FakeActions()
    assert not after_catalog_change(
        actions, CatalogChange(CatalogChangeReason.INTENT_DELETE)
    )
    assert actions.calls == [("prune", None)]


def test_artist_ingest_fills_only_when_rebuild_happens() -> None:
    actions = FakeActions()
    actions.rebuild_unfilled_result = False
    assert not after_catalog_change(
        actions,
        CatalogChange(CatalogChangeReason.ARTIST_INGEST, mixes_added=True),
    )
    assert actions.calls == [("rebuild_unfilled", True)]

    actions = FakeActions()
    actions.rebuild_unfilled_result = True
    assert after_catalog_change(
        actions,
        CatalogChange(CatalogChangeReason.ARTIST_INGEST, mixes_added=True),
    )
    assert actions.calls == [
        ("rebuild_unfilled", True),
        ("request_fill", None),
    ]

    actions = FakeActions()
    assert not after_catalog_change(
        actions,
        CatalogChange(CatalogChangeReason.ARTIST_INGEST, mixes_added=False),
    )
    assert actions.calls == []


def test_peer_ingest_passes_underfilled_flag() -> None:
    actions = FakeActions()
    actions.rebuild_unfilled_result = True
    assert after_catalog_change(
        actions,
        CatalogChange(CatalogChangeReason.PEER_INGEST, mixes_added=False),
    )
    assert actions.calls == [
        ("rebuild_unfilled", False),
        ("request_fill", None),
    ]


def test_sync_fill_vs_async_when_rebuilt() -> None:
    actions = FakeActions()
    actions.rebuild_unfilled_result = True
    assert after_catalog_change(
        actions,
        CatalogChange(CatalogChangeReason.SYNC, mixes_added=True, fill=True),
    )
    assert actions.calls == [
        ("prune", None),
        ("rebuild_unfilled", True),
        ("fill_caches", None),
    ]

    actions = FakeActions()
    actions.rebuild_unfilled_result = True
    assert after_catalog_change(
        actions,
        CatalogChange(CatalogChangeReason.SYNC, mixes_added=False, fill=False),
    )
    assert actions.calls == [
        ("prune", None),
        ("rebuild_unfilled", False),
        ("request_fill", None),
    ]

    actions = FakeActions()
    actions.rebuild_unfilled_result = False
    assert not after_catalog_change(
        actions,
        CatalogChange(CatalogChangeReason.SYNC, mixes_added=False, fill=False),
    )
    assert actions.calls == [
        ("prune", None),
        ("rebuild_unfilled", False),
    ]


def test_reject_and_skip_commit_fillup_policies() -> None:
    actions = FakeActions()
    assert after_catalog_change(
        actions, CatalogChange(CatalogChangeReason.REJECT_COMMIT)
    )
    assert actions.calls == [("fillup_all", None), ("fill_caches", None)]

    actions = FakeActions()
    mix_id = uuid4()
    assert after_catalog_change(
        actions,
        CatalogChange(CatalogChangeReason.SKIP_COMMIT, mix_id=mix_id),
    )
    assert actions.calls == [
        ("fillup_all", None),
        ("fill_caches", None),
        ("retire", mix_id),
    ]


def test_artist_delete_still_rebuilds() -> None:
    actions = FakeActions()
    assert after_catalog_change(
        actions, CatalogChange(CatalogChangeReason.ARTIST_DELETE)
    )
    assert actions.calls == [("rebuild_all", None), ("fill_caches", None)]
