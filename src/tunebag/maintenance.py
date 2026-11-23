"""Catalog maintenance: device-local sequence rebuild/fillup, Cache fill, and prune.

After Catalog mutations, ``after_catalog_change`` runs the follow-up work
(sequence rebuild or fillup, Cache fill, prune). These steps are device-local,
not Events.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol
from uuid import UUID

from tunebag.domain import Intent


class CatalogChangeReason(Enum):
    """Why Catalog maintenance is running after a mutation."""

    MARK_PLAYED = auto()
    SKIP_COMMIT = auto()
    REJECT_COMMIT = auto()
    UN_REJECT = auto()
    ARTIST_INGEST = auto()  # add_artists / refresh_artists
    ARTIST_DELETE = auto()
    INTENT_UPSERT = auto()  # create / update / hours / refresh seed
    INTENT_DELETE = auto()
    PEER_INGEST = auto()
    SYNC = auto()


@dataclass(frozen=True)
class CatalogChange:
    reason: CatalogChangeReason
    mixes_added: bool = False
    fill: bool = False
    """SYNC: when True, ``fill_caches`` synchronously; else async if rebuilt."""
    fill_async: bool = False
    """INTENT_UPSERT: start background ``request_fill`` after rebuild + prune."""
    mix_id: UUID | None = None
    """MARK_PLAYED / SKIP_COMMIT: retire File once a replacement is local."""
    intent: Intent | None = None
    """INTENT_UPSERT: intent to rebuild (caller should hold the event lock)."""


class MaintenanceActions(Protocol):
    """Ports onto DeviceAgent rebuild / fillup / fill / prune / retire helpers."""

    def rebuild_all_sequences(self) -> None: ...

    def fillup_all_sequences(self) -> None: ...

    def rebuild_unfilled_sequences(self, *, include_underfilled: bool = True) -> bool: ...

    def rebuild_sequence_for_intent(self, intent: Intent) -> None: ...

    def fill_caches(self) -> int: ...

    def request_fill(self) -> bool: ...

    def prune_unassigned_files(self) -> None: ...

    def delete_retired_file_if_replaced(self, mix_id: UUID) -> None: ...


@dataclass(frozen=True)
class BoundMaintenance:
    """Callables bound to a DeviceAgent; satisfies ``MaintenanceActions``."""

    rebuild_all_sequences: Callable[[], None]
    fillup_all_sequences: Callable[[], None]
    rebuild_unfilled_sequences: Callable[..., bool]
    rebuild_sequence_for_intent: Callable[[Intent], None]
    fill_caches: Callable[[], int]
    request_fill: Callable[[], bool]
    prune_unassigned_files: Callable[[], None]
    delete_retired_file_if_replaced: Callable[[UUID], None]

    def after_catalog_change(self, change: CatalogChange) -> bool:
        return after_catalog_change(self, change)


def after_catalog_change(actions: MaintenanceActions, change: CatalogChange) -> bool:
    """Run device-local follow-up for a Catalog mutation.

    Returns True when sequences were rebuilt/filled up and/or a fill was started.
    """
    reason = change.reason

    if reason is CatalogChangeReason.INTENT_DELETE:
        actions.prune_unassigned_files()
        return False

    if reason is CatalogChangeReason.INTENT_UPSERT:
        if change.intent is None:
            raise ValueError("INTENT_UPSERT requires change.intent")
        actions.rebuild_sequence_for_intent(change.intent)
        actions.prune_unassigned_files()
        if change.fill_async:
            actions.request_fill()
        return True

    if reason is CatalogChangeReason.UN_REJECT:
        actions.rebuild_all_sequences()
        actions.request_fill()
        return True

    if reason is CatalogChangeReason.MARK_PLAYED:
        # Async fill so natural-end ContinueTo is never blocked by wait_for_fill.
        actions.fillup_all_sequences()
        actions.request_fill()
        if change.mix_id is not None:
            actions.delete_retired_file_if_replaced(change.mix_id)
        return True

    if reason is CatalogChangeReason.SKIP_COMMIT:
        # Async fill so Skip / commit_pending_skips never blocks the UI on
        # origin downloads (same shape as MARK_PLAYED). Retire before kicking
        # fill so a coalesced pass does not race the delete.
        actions.fillup_all_sequences()
        if change.mix_id is not None:
            actions.delete_retired_file_if_replaced(change.mix_id)
        actions.request_fill()
        return True

    if reason is CatalogChangeReason.REJECT_COMMIT:
        # Async fill so Reject never blocks the UI on origin downloads
        # (same shape as MARK_PLAYED / SKIP_COMMIT). Soft-reject file deletes
        # stay on the Soft→Hard timer path.
        actions.fillup_all_sequences()
        actions.request_fill()
        return True

    if reason is CatalogChangeReason.ARTIST_DELETE:
        actions.rebuild_all_sequences()
        actions.fill_caches()
        return True

    if reason is CatalogChangeReason.ARTIST_INGEST:
        if change.mixes_added and actions.rebuild_unfilled_sequences():
            actions.request_fill()
            return True
        return False

    if reason is CatalogChangeReason.PEER_INGEST:
        if actions.rebuild_unfilled_sequences(include_underfilled=change.mixes_added):
            actions.request_fill()
            return True
        return False

    if reason is CatalogChangeReason.SYNC:
        actions.prune_unassigned_files()
        rebuilt = actions.rebuild_unfilled_sequences(
            include_underfilled=change.mixes_added
        )
        if change.fill:
            actions.fill_caches()
            return True
        if rebuilt:
            actions.request_fill()
        return rebuilt

    raise ValueError(f"unhandled catalog change reason: {reason!r}")
