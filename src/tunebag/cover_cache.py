"""Device-local Release cover image bytes (not Event log / audio Cache)."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse
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

# img.hearthis.at often 403s mid/large square sizes while siblings still 200.
# Try normal squares first, then page-style slug URLs (better quality), then
# tiny squares as last resort (e.g. Saetchmo Naughtylist3).
_HEARTHIS_SIZE_VARIANTS = (
    "w800_h800",
    "w500_h500",
    "w400_h400",
    "w200_h200",
    "w160_h160",
)
_HEARTHIS_TINY_SIZE_VARIANTS = (
    "w80_h80",
    "w40_h40",
)
# Page HTML uses permalink----wNNN_hNNN_c3a3a3a_… when API squares 403.
_HEARTHIS_SLUG_SIZE_VARIANTS = (
    "w880_h880",
    "w640_h640",
    "w440_h440",
    "w320_h320",
    "w160_h160",
)
_HEARTHIS_SIZE_RE = re.compile(r"w\d+_h\d+")
# API squares omit the page ``c3a3a3a`` color token; mid sizes with it often 200.
_HEARTHIS_SIZE_Q_RE = re.compile(r"(w\d+_h\d+_)(?:c[0-9a-f]+_)?(q\d+_ptrue_v2_)")
# …/image_track/ID/w800_h800_q70_…----cropped_<32hex><slug>.jpg
_HEARTHIS_EMBEDDED_SLUG_RE = re.compile(
    r"(/image_track/\d+/)(w\d+_h\d+_)"
    r"(q\d+_ptrue_v2_(?:m\d+)?----cropped_)"
    r"([a-f0-9]{32})([a-zA-Z][\w-]*)(\.jpg(?:\?.*)?)$"
)
_HEARTHIS_IMG_RE = re.compile(r"https://img\.hearthis\.at/[^\s\"'<>\\]+")
_HEARTHIS_TRACK_ID_RE = re.compile(r"/image_track/(\d+)/")
_HEARTHIS_UPLOADS_ID_RE = re.compile(r"/uploads/(\d+)/")
_HEARTHIS_DIM_RE = re.compile(r"w(\d+)(?:_h(\d+))?")
_HEARTHIS_OVERLAY_RE = re.compile(r"_btrue_|_o\d+_")


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


def _hearthis_rewrite_size(url: str, size: str, match: re.Match[str]) -> str | None:
    if size == match.group(0):
        return None
    candidate = url[: match.start()] + size + url[match.end() :]
    return candidate if candidate != url else None


def hearthis_cover_fallback_urls(url: str) -> list[str]:
    """Alternate hearthis artwork sizes / slug forms when the primary URL 403s."""
    out: list[str] = []
    match = _HEARTHIS_SIZE_RE.search(url)

    def _add(candidate: str | None) -> None:
        if candidate is not None and candidate not in out:
            out.append(candidate)

    if match is not None:
        for alt in _HEARTHIS_SIZE_VARIANTS:
            _add(_hearthis_rewrite_size(url, alt, match))

    # Page/CDN often serves mid squares only with the ``c3a3a3a`` token
    # (common when artwork_url is actually image_user / profile art).
    size_q = _HEARTHIS_SIZE_Q_RE.search(url)
    if size_q is not None:
        for size in _HEARTHIS_SLUG_SIZE_VARIANTS:
            candidate = (
                url[: size_q.start(1)]
                + f"{size}_c3a3a3a_"
                + size_q.group(2)
                + url[size_q.end(2) :]
            )
            _add(candidate if candidate != url else None)

    slug = _HEARTHIS_EMBEDDED_SLUG_RE.search(url)
    if slug is not None:
        # API:  …/ID/w800_h800_q70_…----cropped_<hash><slug>.jpg
        # Page: …/ID/<slug>----w640_h640_c3a3a3a_q70_…----cropped_<hash><slug>.jpg
        for size in _HEARTHIS_SLUG_SIZE_VARIANTS:
            candidate = (
                url[: slug.start(2)]
                + f"{slug.group(5)}----{size}_c3a3a3a_"
                + slug.group(3)
                + slug.group(4)
                + slug.group(5)
                + slug.group(6)
            )
            _add(candidate if candidate != url else None)

    if match is not None:
        for alt in _HEARTHIS_TINY_SIZE_VARIANTS:
            _add(_hearthis_rewrite_size(url, alt, match))
    return out


def hearthis_track_id_from_cover_url(url: str) -> str | None:
    match = _HEARTHIS_TRACK_ID_RE.search(url)
    return match.group(1) if match else None


def is_hearthis_page_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host == "hearthis.at" or host.endswith(".hearthis.at")


def hearthis_cover_urls_from_html(
    html: str,
    *,
    track_id: str | None = None,
    cover_url: str | None = None,
) -> list[str]:
    """Ranked ``img.hearthis.at`` artwork URLs scraped from a track page.

    Uses ``image_track`` when present; otherwise the uploader's ``image_user``
    avatar (hearthis shows the profile picture as the cover in that case).
    """
    uploads_id: str | None = None
    if cover_url:
        match = _HEARTHIS_UPLOADS_ID_RE.search(cover_url)
        if match is not None:
            uploads_id = match.group(1)

    track_scored: list[tuple[tuple[int, int, int], str]] = []
    user_scored: list[tuple[tuple[int, int, int], str]] = []
    seen: set[str] = set()
    for raw in _HEARTHIS_IMG_RE.findall(html):
        candidate = raw.rstrip(").,;\"'")
        if candidate in seen:
            continue
        if "/image_track/" in candidate:
            if track_id is not None and f"/image_track/{track_id}/" not in candidate:
                continue
            seen.add(candidate)
            track_scored.append((_hearthis_page_url_score(candidate), candidate))
            continue
        if "/image_user/" not in candidate:
            continue
        # Skip commenter avatars when we know the upload owner folder.
        if uploads_id is not None and f"/uploads/{uploads_id}/" not in candidate:
            continue
        seen.add(candidate)
        user_scored.append((_hearthis_page_url_score(candidate), candidate))

    # Prefer track art; keep uploader avatars as lower-priority fallbacks when
    # every image_track CDN URL 403s (common for some older uploads).
    track_scored.sort(key=lambda item: item[0], reverse=True)
    user_scored.sort(key=lambda item: item[0], reverse=True)
    if track_scored:
        scored = track_scored + user_scored
    else:
        scored = user_scored
    return [url for _, url in scored]


def _hearthis_page_url_score(url: str) -> tuple[int, int, int]:
    """Prefer near-square covers; deprioritize watermark overlays."""
    overlay = -2 if _HEARTHIS_OVERLAY_RE.search(url) else 0
    match = _HEARTHIS_DIM_RE.search(url)
    if match is None:
        return (overlay, 0, 0)
    width = int(match.group(1))
    height = int(match.group(2) or width)
    ratio = width / height if height else 0.0
    square = 1 if 0.7 <= ratio <= 1.3 else 0
    return (overlay + square, width * height, width)


def cover_fetch_headers(url: str) -> dict[str, str]:
    """Optional hearthis CDN headers.

    Some older ``img.hearthis.at`` artworks 403 unless ``Origin: https://hearthis.at``
    is set; the same header 403s many normal thumbs. Callers should try bare first,
    then retry with these headers on 403 only.
    """
    host = urlparse(url).netloc.lower()
    if host == "img.hearthis.at" or host.endswith(".hearthis.at"):
        return {"Origin": "https://hearthis.at"}
    return {}


def default_cover_fetcher(url: str) -> bytes:
    with httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        response = client.get(url)
        if response.status_code == 403:
            unlock = cover_fetch_headers(url)
            if unlock:
                response = client.get(url, headers=unlock)
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

    def ensure(
        self,
        mix_id: UUID,
        url: str | None,
        *,
        page_url: str | None = None,
    ) -> bool:
        """Ensure a local cover exists for ``mix_id``. Soft-fails on network errors."""
        if self.has(mix_id):
            return True
        if not url:
            return False
        data = self._fetch_with_fallbacks(mix_id, url, page_url=page_url)
        if not data:
            return False
        path = self.path(mix_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        return True

    def _fetch_with_fallbacks(
        self,
        mix_id: UUID,
        url: str,
        *,
        page_url: str | None = None,
    ) -> bytes | None:
        candidates: list[str] = [url]
        for candidate in (
            *youtube_cover_fallback_urls(url),
            *hearthis_cover_fallback_urls(url),
        ):
            if candidate not in candidates:
                candidates.append(candidate)
        data, last_exc = self._try_candidates(mix_id, candidates)
        if data:
            return data
        page_candidates = self._hearthis_page_candidates(
            mix_id, url, page_url=page_url, tried=candidates
        )
        if page_candidates:
            data, page_exc = self._try_candidates(mix_id, page_candidates)
            if data:
                return data
            if page_exc is not None:
                last_exc = page_exc
        if last_exc is not None:
            logger.warning(
                "cover fetch exhausted fallbacks for %s (started %s)", mix_id, url
            )
        return None

    def _hearthis_page_candidates(
        self,
        mix_id: UUID,
        cover_url: str,
        *,
        page_url: str | None,
        tried: list[str],
    ) -> list[str]:
        if not page_url or not is_hearthis_page_url(page_url):
            return []
        try:
            html_bytes = self._fetch(page_url)
        except Exception as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            logger.warning(
                "cover page scrape failed for %s (%s): %s", mix_id, page_url, exc
            )
            return []
        html = html_bytes.decode("utf-8", errors="ignore")
        track_id = hearthis_track_id_from_cover_url(cover_url)
        scraped = hearthis_cover_urls_from_html(
            html, track_id=track_id, cover_url=cover_url
        )
        out = [candidate for candidate in scraped if candidate not in tried]
        if out:
            logger.info(
                "cover page scrape for %s: %d candidate(s) from %s",
                mix_id,
                len(out),
                page_url,
            )
        return out

    def _try_candidates(
        self, mix_id: UUID, candidates: list[str]
    ) -> tuple[bytes | None, Exception | None]:
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
                return data, last_exc
            logger.warning("cover fetch empty for %s (%s)", mix_id, candidate)
        return None, last_exc
