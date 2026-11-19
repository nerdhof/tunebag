"""Device-local UI view notices (not the signed catalog EventLog).

Typed section signals so open browsers can refetch affected surfaces. Notices
stay on this Device; they are not replicated between Peers.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class UIViewSection(StrEnum):
    MIXES = "mixes"
    PLAY_HISTORY = "play_history"
    INTENTS = "intents"
    PEERS = "peers"
    CACHE = "cache"
    ACTIVITY = "activity"
    PAIRING_SESSION = "pairing_session"
    PLAYER = "player"


@dataclass(frozen=True)
class UIViewNotice:
    section: UIViewSection


_SECTION_ORDER = (
    UIViewSection.MIXES,
    UIViewSection.PLAY_HISTORY,
    UIViewSection.INTENTS,
    UIViewSection.PEERS,
    UIViewSection.CACHE,
    UIViewSection.ACTIVITY,
    UIViewSection.PAIRING_SESSION,
    UIViewSection.PLAYER,
)


class ViewNoticeBus:
    """Thread-safe coalesce of UI section notices for subscribers and drain."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: set[UIViewSection] = set()
        self._depth = 0
        self._drained: list[UIViewNotice] = []
        self._subscribers: list[Callable[[UIViewNotice], None]] = []

    def begin_batch(self) -> None:
        with self._lock:
            self._depth += 1

    def end_batch(self) -> None:
        callbacks: list[tuple[Callable[[UIViewNotice], None], UIViewNotice]] = []
        with self._lock:
            if self._depth <= 0:
                raise RuntimeError("view notice batch ended without begin")
            self._depth -= 1
            if self._depth == 0:
                callbacks = self._flush_locked()
        for callback, notice in callbacks:
            callback(notice)

    def mark(self, *sections: UIViewSection) -> None:
        callbacks: list[tuple[Callable[[UIViewNotice], None], UIViewNotice]] = []
        with self._lock:
            self._pending.update(sections)
            if self._depth == 0:
                callbacks = self._flush_locked()
        for callback, notice in callbacks:
            callback(notice)

    def drain(self) -> list[UIViewNotice]:
        with self._lock:
            notices = list(self._drained)
            self._drained.clear()
            return notices

    def subscribe(
        self, callback: Callable[[UIViewNotice], None]
    ) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._subscribers.remove(callback)
                except ValueError:
                    pass

        return unsubscribe

    def _flush_locked(
        self,
    ) -> list[tuple[Callable[[UIViewNotice], None], UIViewNotice]]:
        if not self._pending:
            return []
        notices = [
            UIViewNotice(section=section)
            for section in _SECTION_ORDER
            if section in self._pending
        ]
        self._pending.clear()
        self._drained.extend(notices)
        callbacks: list[tuple[Callable[[UIViewNotice], None], UIViewNotice]] = []
        for notice in notices:
            for callback in self._subscribers:
                callbacks.append((callback, notice))
        return callbacks
