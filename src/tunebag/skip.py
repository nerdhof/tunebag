"""Local skip with a 5 min delay. Nothing syncs until the timer commits."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from tunebag.domain import SkipPending

SKIP_EFFECTIVE_SECONDS = 300


class SkipBuffer:
    def __init__(self, effective_seconds: int = SKIP_EFFECTIVE_SECONDS) -> None:
        self.effective_seconds = effective_seconds
        self._pending: dict[UUID, SkipPending] = {}

    def start(
        self, mix_id: UUID, device_id: UUID, now: datetime | None = None
    ) -> SkipPending:
        now = now or datetime.utcnow()
        pending = SkipPending(
            mix_id=mix_id,
            device_id=device_id,
            created_at=now,
            effective_at=now + timedelta(seconds=self.effective_seconds),
        )
        self._pending[mix_id] = pending
        return pending

    def cancel(self, mix_id: UUID) -> bool:
        return self._pending.pop(mix_id, None) is not None

    def ready_to_commit(self, now: datetime | None = None) -> list[SkipPending]:
        now = now or datetime.utcnow()
        ready = [p for p in self._pending.values() if p.effective_at <= now]
        for pending in ready:
            self._pending.pop(pending.mix_id, None)
        return ready

    def pending(self) -> list[SkipPending]:
        return list(self._pending.values())
