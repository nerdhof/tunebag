"""Device-local Release cover image bytes (not Event log / audio Cache)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)

CoverFetcher = Callable[[str], bytes]

_HTTP_TIMEOUT = 15.0

# OLAK / video thumbs often advertise maxresdefault that 404s; try smaller sizes.
_YOUTUBE_THUMB_VARIANTS = (
    "maxresdefault",
    "sddefault",
    "hqdefault",
    "mqdefault",
    "default",
)


def cover_path(data_dir: Path, mix_id: UUID) -> Path:
    """On-disk path for a Release cover image (extensionless)."""
    return data_dir / "covers" / str(mix_id)


def cover_media_type(data: bytes) -> str:
    """Best-effort Content-Type from image magic bytes."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def youtube_cover_fallback_urls(url: str) -> list[str]:
    """Alternate YouTube thumb filenames when the primary URL 404s."""
    found: str | None = None
    for name in _YOUTUBE_THUMB_VARIANTS:
        if name in url:
            found = name
            break
    if found is None:
        return []
    out: list[str] = []
    for alt in _YOUTUBE_THUMB_VARIANTS:
        if alt == found:
            continue
        candidate = url.replace(found, alt, 1)
        if candidate != url and candidate not in out:
            out.append(candidate)
    return out


def default_cover_fetcher(url: str) -> bytes:
    with httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


class CoverCache:
    """Local cover files under ``data_dir/covers/``."""

    def __init__(
        self,
        data_dir: Path,
        *,
        fetch: CoverFetcher | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._fetch = fetch if fetch is not None else default_cover_fetcher

    def path(self, mix_id: UUID) -> Path:
        return cover_path(self._data_dir, mix_id)

    def has(self, mix_id: UUID) -> bool:
        path = self.path(mix_id)
        return path.is_file() and path.stat().st_size > 0

    def remove(self, mix_id: UUID) -> bool:
        """Delete local cover if present. Returns True when a file was removed."""
        path = self.path(mix_id)
        if not path.is_file():
            return False
        path.unlink(missing_ok=True)
        return True

    def ensure(self, mix_id: UUID, url: str | None) -> bool:
        """Ensure a local cover exists for ``mix_id``. Soft-fails on network errors."""
        if self.has(mix_id):
            return True
        if not url:
            return False
        data = self._fetch_with_fallbacks(mix_id, url)
        if not data:
            return False
        path = self.path(mix_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        return True

    def _fetch_with_fallbacks(self, mix_id: UUID, url: str) -> bytes | None:
        candidates = [url, *youtube_cover_fallback_urls(url)]
        last_exc: Exception | None = None
        for candidate in candidates:
            try:
                data = self._fetch(candidate)
            except Exception as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                last_exc = exc
                logger.warning(
                    "cover fetch failed for %s (%s): %s", mix_id, candidate, exc
                )
                continue
            if data:
                return data
            logger.warning("cover fetch empty for %s (%s)", mix_id, candidate)
        if last_exc is not None:
            logger.warning(
                "cover fetch exhausted fallbacks for %s (started %s)", mix_id, url
            )
        return None
