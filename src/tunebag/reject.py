"""Local reject with a 20s undo window. Nothing syncs until the timer commits."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from tunebag.domain import RejectPending

UNDO_SECONDS = 20


class RejectBuffer:
    def __init__(self, undo_seconds: int = UNDO_SECONDS) -> None:
        self.undo_seconds = undo_seconds
        self._pending: dict[UUID, RejectPending] = {}

    def start(self, mix_id: UUID, device_id: UUID, now: datetime | None = None) -> RejectPending:
        now = now or datetime.utcnow()
        pending = RejectPending(
            mix_id=mix_id,
            device_id=device_id,
            created_at=now,
            undo_until=now + timedelta(seconds=self.undo_seconds),
        )
        self._pending[mix_id] = pending
        return pending

    def undo(self, mix_id: UUID) -> bool:
        return self._pending.pop(mix_id, None) is not None

    def ready_to_commit(self, now: datetime | None = None) -> list[RejectPending]:
        now = now or datetime.utcnow()
        ready = [p for p in self._pending.values() if p.undo_until <= now]
        for pending in ready:
            self._pending.pop(pending.mix_id, None)
        return ready

    def pending(self) -> list[RejectPending]:
        return list(self._pending.values())
