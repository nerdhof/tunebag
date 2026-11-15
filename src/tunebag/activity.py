"""Operational activity ring buffer (not the signed catalog EventLog)."""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

logger = logging.getLogger("tunebag")

_DEFAULT_CAPACITY = 200


@dataclass(frozen=True)
class ActivityEntry:
    ts: str
    level: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


class ActivityLog:
    """Thread-safe ring of recent operational notes for terminal + UI."""

    def __init__(self, *, capacity: int = _DEFAULT_CAPACITY) -> None:
        self._entries: deque[ActivityEntry] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def note(self, message: str, *, level: int = logging.INFO) -> None:
        level_name = logging.getLevelName(level)
        if not isinstance(level_name, str):
            level_name = str(level)
        entry = ActivityEntry(
            ts=datetime.now(UTC).isoformat(timespec="seconds"),
            level=level_name,
            message=message,
        )
        with self._lock:
            self._entries.append(entry)
        logger.log(level, message)

    def entries(self) -> list[ActivityEntry]:
        with self._lock:
            return list(self._entries)
