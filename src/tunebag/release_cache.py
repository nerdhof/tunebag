"""Release Cache: device-local File set for assignments.

Owns completeness checks, staging, blob paths, intent-folder linking, and
``ensure_complete`` (peer then optional origin). Fetch ports are injected;
urgency / metered / preferred-origin policy stay on DeviceAgent.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Protocol
from uuid import UUID

from tunebag.domain import Mix, ReleaseKind, new_id
from tunebag.projection import CatalogState
from tunebag.release_layout import (
    album_track_filename,
    album_track_path,
    blob_path,
    safe_album_dirname,
    safe_filename,
)


class PeerBytes(Protocol):
    """Reachable peer that may already hold Release File bytes."""

    @property
    def name(self) -> str: ...

    def file_bytes(self, mix_id: UUID) -> bytes | None: ...

    def album_track_bytes(self, mix_id: UUID) -> list[bytes] | None: ...


class OriginFetch(Protocol):
    """Origin (source platform) byte fetch for one Release."""

    def fetch_mix(self, mix: Mix) -> bytes: ...

    def fetch_album(self, mix: Mix) -> list[bytes]: ...


class ReleaseCache:
    """Device-local Files for Mix blobs and complete Album track directories."""

    def __init__(
        self,
        data_dir: Path,
        catalog: CatalogState,
        *,
        on_changed: Callable[[], None] | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.catalog = catalog
        self._on_changed = on_changed
        # In-memory Mix blobs (Albums live only on disk under blobs/<id>/).
        self._memory: dict[UUID, bytes] = {}

    def blob_path(self, mix_id: UUID) -> Path:
        return blob_path(self.data_dir, mix_id)

    def album_track_path(self, mix: Mix, index: int) -> Path:
        return album_track_path(self.data_dir, mix, index)

    def intent_folder(self, intent_id: UUID) -> Path:
        path = self.data_dir / "intents" / str(intent_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def has(self, mix_id: UUID) -> bool:
        mix = self.catalog.mixes.get(mix_id)
        if mix is not None and mix.kind is ReleaseKind.ALBUM:
            return self.album_complete(mix)
        return mix_id in self._memory or self.blob_path(mix_id).is_file()

    def album_complete(self, mix: Mix) -> bool:
        if mix.kind is not ReleaseKind.ALBUM or not mix.tracks:
            return False
        cache_dir = self.blob_path(mix.id)
        if not cache_dir.is_dir():
            return False
        return all(
            (cache_dir / album_track_filename(index, track)).is_file()
            for index, track in enumerate(mix.tracks)
        )

    def local_ids(self) -> set[UUID]:
        ids = set(self._memory)
        blobs = self.data_dir / "blobs"
        if blobs.is_dir():
            for path in blobs.iterdir():
                try:
                    mix_id = UUID(path.name)
                except ValueError:
                    continue
                if path.is_file():
                    ids.add(mix_id)
                    continue
                if path.is_dir():
                    mix = self.catalog.mixes.get(mix_id)
                    if mix is not None and self.album_complete(mix):
                        ids.add(mix_id)
        return ids

    def size(self, mix_id: UUID) -> int | None:
        mix = self.catalog.mixes.get(mix_id)
        if mix is not None and mix.kind is ReleaseKind.ALBUM:
            if not self.album_complete(mix):
                return None
            cache_dir = self.blob_path(mix_id)
            return sum(
                (cache_dir / album_track_filename(index, track)).stat().st_size
                for index, track in enumerate(mix.tracks)
            )
        path = self.blob_path(mix_id)
        if path.is_file():
            return path.stat().st_size
        data = self._memory.get(mix_id)
        if data is not None:
            return len(data)
        return None

    def mix_bytes(self, mix_id: UUID) -> bytes | None:
        """Local audio bytes for a Mix, if present (peer handoff).

        Albums use ``album_bytes`` — a single blob is not meaningful.
        """
        mix = self.catalog.mixes.get(mix_id)
        if mix is not None and mix.kind is ReleaseKind.ALBUM:
            return None
        if mix_id in self._memory:
            return self._memory[mix_id]
        path = self.blob_path(mix_id)
        if path.is_file():
            data = path.read_bytes()
            self._memory[mix_id] = data
            return data
        return None

    def album_bytes(self, mix_id: UUID) -> list[bytes] | None:
        """Ordered track bytes for a complete Album, else None (peer handoff)."""
        mix = self.catalog.mixes.get(mix_id)
        if mix is None or mix.kind is not ReleaseKind.ALBUM:
            return None
        if not self.album_complete(mix):
            return None
        cache_dir = self.blob_path(mix_id)
        return [
            (cache_dir / album_track_filename(index, track)).read_bytes()
            for index, track in enumerate(mix.tracks)
        ]

    def store_mix(self, mix_id: UUID, data: bytes) -> None:
        self._memory[mix_id] = data
        path = self.blob_path(mix_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self._notify_changed()

    def store_album(self, mix: Mix, payloads: list[bytes]) -> None:
        """Write all Album tracks into one cache directory (all-or-nothing)."""
        if len(payloads) != len(mix.tracks):
            raise ValueError("album track count mismatch")
        cache_dir = self.blob_path(mix.id)
        # Unique staging dir so a concurrent fill cannot rmtree another attempt.
        staging = cache_dir.parent / f".{mix.id}.{new_id()}.partial"
        staging.mkdir(parents=True, exist_ok=True)
        try:
            for index, (track, data) in enumerate(zip(mix.tracks, payloads, strict=True)):
                (staging / album_track_filename(index, track)).write_bytes(data)
            if cache_dir.exists():
                shutil.rmtree(cache_dir, ignore_errors=True)
            staging.rename(cache_dir)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        self._notify_changed()

    def remove(self, mix_id: UUID) -> bool:
        """Drop local audio for a Release. Returns whether anything was present."""
        path = self.blob_path(mix_id)
        had = mix_id in self._memory or path.exists()
        self._memory.pop(mix_id, None)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file():
            path.unlink()
        return had

    def clear_incomplete_album(self, mix_id: UUID) -> None:
        """Drop an incomplete Album cache dir; leave complete discs alone."""
        cache_dir = self.blob_path(mix_id)
        if not cache_dir.is_dir():
            return
        mix = self.catalog.mixes.get(mix_id)
        if mix is not None and self.album_complete(mix):
            return
        shutil.rmtree(cache_dir, ignore_errors=True)

    def ensure_on_disk(self, mix_id: UUID) -> Path:
        path = self.blob_path(mix_id)
        if path.is_file():
            return path
        mix = self.catalog.mixes.get(mix_id)
        if mix is not None and mix.kind is ReleaseKind.ALBUM:
            if self.album_complete(mix):
                return path
            raise ValueError("album has no complete local files")
        data = self._memory.get(mix_id)
        if data is None:
            raise ValueError("mix has no local file")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def ensure_complete(
        self,
        mix: Mix,
        *,
        peers: Sequence[PeerBytes],
        origin: OriginFetch | None,
        still_assigned: Callable[[], bool],
        note: Callable[[str], None] | None = None,
        wrap_download: Callable[[UUID, Callable[[], None]], None] | None = None,
    ) -> None:
        """Ensure Mix/Album Files are local via peer copy then optional origin.

        ``origin`` None means do not fetch from origin this pass (metered wait,
        preferred peer reachable, etc.). Peer copies ignore that gate.
        """
        if mix.kind is ReleaseKind.ALBUM:
            self._ensure_album(
                mix,
                peers=peers,
                origin=origin,
                still_assigned=still_assigned,
                note=note,
                wrap_download=wrap_download,
            )
            return
        self._ensure_mix(
            mix,
            peers=peers,
            origin=origin,
            still_assigned=still_assigned,
            note=note,
            wrap_download=wrap_download,
        )

    def refresh_intent_folders(
        self,
        intent_ids: Iterable[UUID],
        assigned_mix_ids: Callable[[UUID], Sequence[UUID]],
    ) -> None:
        self._remove_orphan_intent_folders(intent_ids)
        for intent_id in intent_ids:
            folder = self.intent_folder(intent_id)
            for existing in folder.iterdir():
                if existing.is_dir() and not existing.is_symlink():
                    shutil.rmtree(existing, ignore_errors=True)
                elif existing.is_file() or existing.is_symlink():
                    existing.unlink()
            for mix_id in assigned_mix_ids(intent_id):
                if not self.has(mix_id):
                    continue
                mix = self.catalog.mixes.get(mix_id)
                if mix is None:
                    continue
                if mix.kind is ReleaseKind.ALBUM:
                    self._link_album(folder, mix)
                else:
                    self._link_mix(folder, mix)

    def remove_intent_folder(self, intent_id: UUID) -> None:
        folder = self.data_dir / "intents" / str(intent_id)
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)

    def _ensure_mix(
        self,
        mix: Mix,
        *,
        peers: Sequence[PeerBytes],
        origin: OriginFetch | None,
        still_assigned: Callable[[], bool],
        note: Callable[[str], None] | None,
        wrap_download: Callable[[UUID, Callable[[], None]], None] | None,
    ) -> None:
        mix_id = mix.id
        label = mix.title
        if not still_assigned():
            self._note(note, f"fill skip unassigned: {label}")
            return

        def _store_if_still_assigned(payload: bytes) -> bool:
            if not still_assigned():
                self._note(note, f"fill discard unassigned: {label}")
                return False
            self.store_mix(mix_id, payload)
            return True

        for peer in peers:
            peer_bytes = peer.file_bytes(mix_id)
            if peer_bytes is None:
                continue
            self._note(note, f"copy from peer {peer.name}: {label}")
            kept = False

            def _copy() -> None:
                nonlocal kept
                kept = _store_if_still_assigned(peer_bytes)

            self._run_download(wrap_download, mix_id, _copy)
            if kept:
                self._note(note, f"cached: {label}")
            return

        if origin is None:
            return
        self._note(note, f"download from origin: {label}")
        kept = False

        def _fetch() -> None:
            nonlocal kept
            kept = _store_if_still_assigned(origin.fetch_mix(mix))

        self._run_download(wrap_download, mix_id, _fetch)
        if kept:
            self._note(note, f"cached: {label}")

    def _ensure_album(
        self,
        mix: Mix,
        *,
        peers: Sequence[PeerBytes],
        origin: OriginFetch | None,
        still_assigned: Callable[[], bool],
        note: Callable[[str], None] | None,
        wrap_download: Callable[[UUID, Callable[[], None]], None] | None,
    ) -> None:
        mix_id = mix.id
        label = mix.title
        # Incomplete leftover dirs must not linger as fake cache state.
        self.clear_incomplete_album(mix_id)
        if not still_assigned():
            self._note(note, f"fill skip unassigned: {label}")
            return

        def _store_tracks_if_still_assigned(payloads: list[bytes]) -> bool:
            if not still_assigned():
                self._note(note, f"fill discard unassigned: {label}")
                return False
            self.store_album(mix, payloads)
            return True

        for peer in peers:
            peer_tracks = peer.album_track_bytes(mix_id)
            if peer_tracks is None:
                continue
            self._note(note, f"copy from peer {peer.name}: {label}")
            kept = False

            def _copy() -> None:
                nonlocal kept
                kept = _store_tracks_if_still_assigned(peer_tracks)

            self._run_download(wrap_download, mix_id, _copy)
            if kept:
                self._note(note, f"cached: {label}")
            return

        if origin is None:
            return
        self._note(note, f"download from origin: {label}")
        kept = False

        def _fetch() -> None:
            nonlocal kept
            try:
                payloads = origin.fetch_album(mix)
            except Exception:
                self.clear_incomplete_album(mix_id)
                raise
            kept = _store_tracks_if_still_assigned(payloads)

        self._run_download(wrap_download, mix_id, _fetch)
        if kept:
            self._note(note, f"cached: {label}")

    def _link_mix(self, folder: Path, mix: Mix) -> None:
        blob = self.ensure_on_disk(mix.id)
        target = folder / safe_filename(mix.title, mix.id)
        if target.exists() or target.is_symlink():
            target.unlink()
        try:
            target.hardlink_to(blob)
        except OSError:
            target.write_bytes(blob.read_bytes())

    def _link_album(self, folder: Path, mix: Mix) -> None:
        cache_dir = self.ensure_on_disk(mix.id)
        album_folder = folder / safe_album_dirname(mix.title, mix.id)
        if album_folder.exists():
            shutil.rmtree(album_folder, ignore_errors=True)
        album_folder.mkdir(parents=True, exist_ok=True)
        for index, track in enumerate(mix.tracks):
            src = cache_dir / album_track_filename(index, track)
            target = album_folder / album_track_filename(index, track)
            try:
                target.hardlink_to(src)
            except OSError:
                target.write_bytes(src.read_bytes())

    def _remove_orphan_intent_folders(self, live_intent_ids: Iterable[UUID]) -> None:
        root = self.data_dir / "intents"
        if not root.is_dir():
            return
        live = {str(intent_id) for intent_id in live_intent_ids}
        for path in list(root.iterdir()):
            if not path.is_dir():
                continue
            if path.name in live:
                continue
            shutil.rmtree(path, ignore_errors=True)

    def _notify_changed(self) -> None:
        if self._on_changed is not None:
            self._on_changed()

    @staticmethod
    def _note(note: Callable[[str], None] | None, message: str) -> None:
        if note is not None:
            note(message)

    @staticmethod
    def _run_download(
        wrap: Callable[[UUID, Callable[[], None]], None] | None,
        mix_id: UUID,
        action: Callable[[], None],
    ) -> None:
        if wrap is not None:
            wrap(mix_id, action)
        else:
            action()
