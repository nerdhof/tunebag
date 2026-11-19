"""Soft Rejected window: defer File byte deletion until Soft ages to Hard.

Reject Events append immediately (confirm-click). Soft vs Hard are UI visibility
over Reject author time; File deletes wait ``SOFT_REJECT_SECONDS`` after that time.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

SOFT_REJECT_SECONDS = 5 * 60


def soft_reject_until(rejected_at: datetime) -> datetime:
    """Instant Soft Rejected becomes Hard (and File bytes may be deleted)."""
    return rejected_at + timedelta(seconds=SOFT_REJECT_SECONDS)


def is_soft_rejected(
    *,
    rejected: bool,
    rejected_at: datetime | None,
    now: datetime,
) -> bool:
    """True when Rejected and Reject author time is still inside the soft window."""
    if not rejected or rejected_at is None:
        return False
    return soft_reject_until(rejected_at) > now


class RejectFileDeleteBuffer:
    """Local-only schedule: delete File bytes when Soft → Hard."""

    def __init__(self, soft_seconds: int = SOFT_REJECT_SECONDS) -> None:
        self.soft_seconds = soft_seconds
        self._delete_at: dict[UUID, datetime] = {}

    def schedule(self, mix_id: UUID, rejected_at: datetime) -> None:
        self._delete_at[mix_id] = rejected_at + timedelta(seconds=self.soft_seconds)

    def cancel(self, mix_id: UUID) -> bool:
        return self._delete_at.pop(mix_id, None) is not None

    def ready_to_delete(self, now: datetime | None = None) -> list[UUID]:
        now = now or datetime.utcnow()
        ready = [mix_id for mix_id, at in self._delete_at.items() if at <= now]
        for mix_id in ready:
            del self._delete_at[mix_id]
        return ready

    def pending(self) -> dict[UUID, datetime]:
        return dict(self._delete_at)
