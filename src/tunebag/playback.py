"""Playback supervision: local-only timeline, anchors, Album advance, thresholds.

Owns the AudioPlayer and playing state. Emits structured intents for DeviceAgent
to translate into Events (Playhead / Last heard / Played) and auto-ContinueTo.
Playing state is not an Event.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from tunebag.domain import Mix, ReleaseKind
from tunebag.player import AudioPlayer
from tunebag.release_layout import album_timeline_location

PLAYED_THRESHOLD = 0.75
# Meaningful listen: position reaches min(10s, 2% of duration); rising edge only.
LAST_HEARD_CAP_SECONDS = 10.0
LAST_HEARD_DURATION_FRACTION = 0.02


def last_heard_threshold(duration_seconds: int) -> float:
    """Meaningful-listen threshold: min(10s, 2% of duration)."""
    return min(
        LAST_HEARD_CAP_SECONDS,
        LAST_HEARD_DURATION_FRACTION * float(duration_seconds),
    )


@dataclass(frozen=True)
class ReportPlayhead:
    mix_id: UUID
    position_seconds: float


@dataclass(frozen=True)
class EmitLastHeard:
    mix_id: UUID


@dataclass(frozen=True)
class MarkPlayed:
    mix_id: UUID


@dataclass(frozen=True)
class ContinueTo:
    intent_id: UUID
    mix_id: UUID


PlaybackIntent = ReportPlayhead | EmitLastHeard | MarkPlayed | ContinueTo

# (path, start_seconds within that file) for a Release timeline position.
AudioLocator = Callable[[Mix, float], tuple[Path, float]]


class PlaybackSupervisor:
    """Local playback state machine; Event authorship stays on DeviceAgent."""

    def __init__(
        self,
        player: AudioPlayer,
        clock: Callable[[], datetime],
        *,
        locate_audio: AudioLocator,
    ) -> None:
        self._player = player
        self._clock = clock
        self._locate_audio = locate_audio
        self.playing = False
        self.intent_id: UUID | None = None
        self.position: float = 0.0
        self._anchor_position: float = 0.0
        self._anchor_at: datetime | None = None
        self.album_index: int | None = None
        # Next local assignment id after the release started by start() (no wrap).
        # Stashed at play time so mid-release mark_played rebuilds do not lose it.
        self.continue_next_id: UUID | None = None

    @property
    def has_live_anchor(self) -> bool:
        return self.playing and self._anchor_at is not None

    def start(
        self,
        mix: Mix,
        timeline_seconds: float,
        *,
        intent_id: UUID,
        continue_next_id: UUID | None,
    ) -> None:
        """Start local audio for a Release at a timeline position."""
        self._start_audio(mix, timeline_seconds)
        self.playing = True
        self.intent_id = intent_id
        self.continue_next_id = continue_next_id
        self._set_anchor(timeline_seconds)

    def stop(self) -> None:
        """Stop local playback without marking the mix played."""
        self.freeze()
        self._player.stop()
        self.playing = False
        self.intent_id = None
        self.album_index = None
        self.continue_next_id = None

    def pause_audio(self) -> None:
        """Stop the player; keep intent/position for resume (playhead already committed)."""
        self._player.stop()
        self.playing = False
        self.album_index = None
        self._clear_anchor()

    def live_position(self, mix: Mix | None = None) -> float:
        """Current local playback position (including a mid-mix resume point)."""
        if self.has_live_anchor:
            return self._computed_position(mix)
        return self.position

    def freeze(self) -> None:
        if self._anchor_at is not None:
            self.position = self._computed_position()
            self._clear_anchor()

    def note_position(
        self,
        mix: Mix,
        position_seconds: float,
        *,
        previous_position: float,
    ) -> list[PlaybackIntent]:
        """Update local position/anchors; emit Playhead / Last heard / MarkPlayed intents."""
        pos = float(position_seconds)
        self.position = pos
        if self.has_live_anchor:
            self._anchor_position = pos
            self._anchor_at = self._clock()
        return self._threshold_intents(
            mix, pos, previous_position=previous_position
        )

    def seek(
        self,
        mix: Mix,
        position_seconds: float,
        *,
        was_playing: bool,
        keep_playing: bool,
    ) -> None:
        """Restart audio at a seek point when still playing; else idle at position."""
        pos = float(position_seconds)
        if was_playing and keep_playing and self.intent_id is not None:
            self._start_audio(mix, pos)
            self.playing = True
            self._set_anchor(pos)
            return
        self.position = pos
        self.album_index = None
        self._clear_anchor()

    def supervise(
        self,
        mix: Mix | None,
        *,
        previous_position: float,
        fallback_next_id: UUID | None = None,
    ) -> list[PlaybackIntent]:
        """Advance Album tracks; on release end, finalize and optionally ContinueTo.

        Start the next track (or clear playing) before returning ReportPlayhead so a
        nested ``is_playing`` from prune/auto-sync cannot re-enter mid-advance.
        """
        if not self.playing or self._player.is_alive():
            return []
        if (
            mix is not None
            and mix.kind is ReleaseKind.ALBUM
            and self.album_index is not None
        ):
            next_index = self.album_index + 1
            if next_index < len(mix.tracks):
                timeline = float(
                    sum(t.duration_seconds for t in mix.tracks[:next_index])
                )
                path, _offset = self._locate_audio(mix, timeline)
                self._player.play(path, start_seconds=0.0)
                self.album_index = next_index
                self._set_anchor(timeline)
                return self.note_position(
                    mix, timeline, previous_position=previous_position
                )
            return self._continue_after_end(
                mix,
                previous_position=previous_position,
                fallback_next_id=fallback_next_id,
            )
        if mix is not None:
            return self._continue_after_end(
                mix,
                previous_position=previous_position,
                fallback_next_id=fallback_next_id,
            )
        # Unknown current release; keep catalog current_mix for metered/resume.
        self.freeze()
        self.playing = False
        self.album_index = None
        return []

    def _continue_after_end(
        self,
        mix: Mix,
        *,
        previous_position: float,
        fallback_next_id: UUID | None,
    ) -> list[PlaybackIntent]:
        intent_id = self.intent_id
        next_id = self.continue_next_id
        if next_id is None:
            next_id = fallback_next_id
        self.continue_next_id = None
        end = float(mix.duration_seconds)
        self.position = end
        self.playing = False
        self.album_index = None
        self._clear_anchor()
        intents = self.note_position(
            mix, end, previous_position=previous_position
        )
        if next_id is not None and intent_id is not None:
            intents.append(ContinueTo(intent_id=intent_id, mix_id=next_id))
        return intents

    def _threshold_intents(
        self,
        mix: Mix,
        position_seconds: float,
        *,
        previous_position: float,
    ) -> list[PlaybackIntent]:
        intents: list[PlaybackIntent] = [
            ReportPlayhead(mix_id=mix.id, position_seconds=position_seconds)
        ]
        threshold = last_heard_threshold(mix.duration_seconds)
        if previous_position < threshold <= position_seconds:
            intents.append(EmitLastHeard(mix_id=mix.id))
        if (
            not mix.played
            and mix.duration_seconds > 0
            and position_seconds >= PLAYED_THRESHOLD * mix.duration_seconds
        ):
            intents.append(MarkPlayed(mix_id=mix.id))
        return intents

    def _start_audio(self, mix: Mix, timeline_seconds: float) -> None:
        path, offset = self._locate_audio(mix, float(timeline_seconds))
        self._player.play(path, start_seconds=offset)
        if mix.kind is ReleaseKind.ALBUM:
            if not mix.tracks:
                raise ValueError("album has no tracks")
            index, _ = album_timeline_location(mix, timeline_seconds)
            self.album_index = index
            return
        self.album_index = None

    def _set_anchor(self, position: float) -> None:
        self.position = float(position)
        self._anchor_position = float(position)
        self._anchor_at = self._clock()

    def _clear_anchor(self) -> None:
        self._anchor_at = None

    def _computed_position(self, mix: Mix | None = None) -> float:
        if self._anchor_at is None:
            return self.position
        elapsed = (self._clock() - self._anchor_at).total_seconds()
        pos = self._anchor_position + max(0.0, elapsed)
        if mix is not None and mix.duration_seconds > 0:
            pos = min(float(mix.duration_seconds), pos)
        return round(pos, 3)


def clamp_seek_position(position_seconds: float, duration_seconds: float) -> float:
    pos = max(0.0, float(position_seconds))
    if duration_seconds > 0:
        pos = min(duration_seconds, pos)
    return pos
