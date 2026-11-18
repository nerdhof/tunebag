"""Pure path and Album-timeline helpers for Release Cache and playback.

Shared by Cache (on-disk File layout) and Playback supervision (timeline → track).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from tunebag.domain import AlbumTrack, Mix


def blob_path(data_dir: Path, mix_id: UUID) -> Path:
    """On-disk path for a Mix blob file or Album track directory."""
    return data_dir / "blobs" / str(mix_id)


def safe_filename(title: str, mix_id: UUID) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in title).strip()
    if not cleaned:
        cleaned = "mix"
    return f"{cleaned[:80]}-{mix_id}.bin"


def safe_album_dirname(title: str, mix_id: UUID) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in title).strip()
    if not cleaned:
        cleaned = "album"
    return f"{cleaned[:80]}-{mix_id}"


def album_track_filename(index: int, track: AlbumTrack) -> str:
    """Stable ordered name for a track file inside an Album cache directory."""
    cleaned = "".join(
        ch if ch.isalnum() or ch in "-_ ." else "_" for ch in track.title
    ).strip()
    if not cleaned:
        cleaned = "track"
    return f"{index + 1:02d}-{cleaned[:60]}-{track.platform_id}.bin"


def album_track_path(data_dir: Path, mix: Mix, index: int) -> Path:
    """Path to one Album track file under the Release Cache directory."""
    return blob_path(data_dir, mix.id) / album_track_filename(index, mix.tracks[index])


def album_timeline_location(mix: Mix, position_seconds: float) -> tuple[int, float]:
    """Map Album-timeline seconds to (track_index, offset_within_track)."""
    if not mix.tracks:
        return 0, 0.0
    remaining = max(0.0, float(position_seconds))
    last_index = len(mix.tracks) - 1
    for index, track in enumerate(mix.tracks):
        duration = float(track.duration_seconds)
        if index == last_index or remaining < duration:
            offset = min(remaining, duration) if duration > 0 else 0.0
            return index, offset
        remaining -= duration
    return last_index, float(mix.tracks[last_index].duration_seconds)
