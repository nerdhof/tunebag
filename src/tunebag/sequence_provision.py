"""SequenceProvisioner: rebuild/fillup decisions and Sequence/Assignment Event drafts.

Pure helpers ``build_sequence`` / ``fill_sequence`` / ``assign_by_budget`` stay in
``sequence.py``. The caller appends returned drafts (typically via CatalogJournal
under ``hold``). Does not own Cache fill or prune.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tunebag.domain import Intent, Sequence
from tunebag.events import EventType
from tunebag.projection import CatalogState
from tunebag.sequence import assign_by_budget, build_sequence, fill_sequence


@dataclass(frozen=True)
class EventDraft:
    type: EventType
    payload: dict[str, Any]


class SequenceProvisioner:
    """Decide rebuild/fillup need and draft Sequence/Assignment Events for one Intent."""

    def needs_rebuild(
        self,
        intent: Intent,
        catalog: CatalogState,
        *,
        include_underfilled: bool = True,
    ) -> bool:
        """True when a device_hours row lacks a usable assignment, or under budget.

        Explore seed writes ``ASSIGNMENT_SET`` with ``mix_ids=[]``. After pair, a
        peer's filled Sequence may win LWW while that empty assignment remains —
        treat empty ``mix_ids`` as needing rebuild when the Sequence has entries.

        Under-budget rebuilds only run when a fresh ``build_sequence`` would change
        the mix id list (new eligible Catalog mixes). Otherwise an empty/short
        Sequence with no further eligible mixes would rebuild on every sync.
        """
        if intent.max_budget_seconds <= 0:
            return False
        sequence = catalog.sequences.get(intent.id)
        sequence_has_entries = sequence is not None and bool(sequence.entries)
        for device_hours in intent.device_hours:
            assignment = catalog.assignments.get((intent.id, device_hours.device_id))
            if assignment is None:
                return True
            if sequence_has_entries and not assignment.mix_ids:
                return True
        if not include_underfilled:
            return False
        if self._sequence_duration_seconds(intent, catalog) >= intent.max_budget_seconds:
            return False
        current_ids = [entry.mix_id for entry in sequence.entries] if sequence else []
        rebuilt_ids = [
            entry.mix_id
            for entry in build_sequence(intent, catalog.mixes_list()).entries
        ]
        return rebuilt_ids != current_ids

    def provision(self, intent: Intent, catalog: CatalogState) -> list[EventDraft]:
        """Full redraw: draft SEQUENCE_BUILT / ASSIGNMENT_CLEARED / ASSIGNMENT_SET."""
        sequence = build_sequence(intent, catalog.mixes_list())
        return self._drafts_for_sequence(intent, catalog, sequence)

    def provision_fillup(
        self,
        intent: Intent,
        catalog: CatalogState,
        *,
        current: Sequence | None = None,
    ) -> list[EventDraft]:
        """Keep remaining queued order; drop retired; append only if under budget.

        ``current`` defaults to the Catalog Sequence for the Intent. Callers may
        pass a trimmed Sequence (e.g. Drop) so fillup starts from that list.
        """
        if current is None:
            current = catalog.sequences.get(intent.id)
        sequence = fill_sequence(intent, catalog.mixes_list(), current)
        return self._drafts_for_sequence(intent, catalog, sequence)

    def _drafts_for_sequence(
        self,
        intent: Intent,
        catalog: CatalogState,
        sequence: Sequence,
    ) -> list[EventDraft]:
        drafts: list[EventDraft] = []
        active_devices = {dh.device_id for dh in intent.device_hours}
        for iid, device_id in list(catalog.assignments):
            if iid == intent.id and device_id not in active_devices:
                drafts.append(
                    EventDraft(
                        type=EventType.ASSIGNMENT_CLEARED,
                        payload={
                            "intent_id": str(intent.id),
                            "device_id": str(device_id),
                        },
                    )
                )
        drafts.append(
            EventDraft(
                type=EventType.SEQUENCE_BUILT,
                payload={
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
        )
        duration_by_mix = {
            mix_id: mix.duration_seconds for mix_id, mix in catalog.mixes.items()
        }
        for device_hours in intent.device_hours:
            mix_ids = assign_by_budget(
                sequence,
                device_hours.device_id,
                device_hours.budget_seconds,
                duration_by_mix,
            )
            drafts.append(
                EventDraft(
                    type=EventType.ASSIGNMENT_SET,
                    payload={
                        "intent_id": str(intent.id),
                        "device_id": str(device_hours.device_id),
                        "mix_ids": [str(mix_id) for mix_id in mix_ids],
                        "budget_seconds": device_hours.budget_seconds,
                    },
                )
            )
        return drafts

    def _sequence_duration_seconds(
        self, intent: Intent, catalog: CatalogState
    ) -> int:
        sequence = catalog.sequences.get(intent.id)
        if sequence is None:
            return 0
        total = 0
        for entry in sequence.entries:
            mix = catalog.mixes.get(entry.mix_id)
            if mix is not None:
                total += mix.duration_seconds
        return total
