"""Download audio bytes for a track permalink via yt-dlp."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

AudioFetcher = Callable[[str], bytes]
ProgressCallback = Callable[[int, int | None], None]


def fetch_audio_bytes(
    source_url: str,
    *,
    fetcher: AudioFetcher | None = None,
    on_progress: ProgressCallback | None = None,
) -> bytes:
    """Return audio bytes for a SoundCloud or hearthis permalink."""
    if fetcher is not None:
        return fetcher(source_url)
    return _ytdlp_fetch(source_url, on_progress=on_progress)


def _permalink_referer(source_url: str) -> str:
    parsed = urlparse(source_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/"
    return "https://hearthis.at/"


def _is_forbidden(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "403" in text or "forbidden" in text


def _is_hearthis(source_url: str) -> bool:
    host = (urlparse(source_url).hostname or "").lower()
    return host == "hearthis.at" or host.endswith(".hearthis.at")


def _ytdlp_fetch(
    source_url: str,
    *,
    on_progress: ProgressCallback | None = None,
) -> bytes:
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    def _hook(info: dict[str, Any]) -> None:
        if on_progress is None or info.get("status") != "downloading":
            return
        downloaded = int(info.get("downloaded_bytes") or 0)
        total = info.get("total_bytes")
        if total is None:
            total = info.get("total_bytes_estimate")
        total_int = int(total) if total is not None else None
        on_progress(downloaded, total_int)

    formats = ["bestaudio/best"]
    # hearthis.app CDN (Cloudflare) often 403s /download/ (even with Referer).
    # Prefer the /listen/ stream first. Selecting format id "mp3" is not enough:
    # when the download file is also mp3, yt-dlp renames formats to mp3-0/mp3-1
    # and a bare mp3 preference still picks the higher-quality /download/ URL.
    if _is_hearthis(source_url):
        formats = [
            "bestaudio[url*=listen]/bestaudio/best",
            "bestaudio/best",
        ]

    last_error: BaseException | None = None
    with tempfile.TemporaryDirectory() as tmp:
        outtmpl = str(Path(tmp) / "audio.%(ext)s")
        for index, fmt in enumerate(formats):
            for leftover in Path(tmp).iterdir():
                if leftover.is_file():
                    leftover.unlink()
            opts: dict[str, Any] = {
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "format": fmt,
                "outtmpl": outtmpl,
                "noplaylist": True,
                # Prefer progressive HTTP so demo fill does not require ffmpeg.
                "prefer_free_formats": True,
                "http_headers": {"Referer": _permalink_referer(source_url)},
            }
            if on_progress is not None:
                opts["progress_hooks"] = [_hook]
            try:
                with YoutubeDL(opts) as ydl:
                    ydl.download([source_url])
            except DownloadError as exc:
                last_error = exc
                if index + 1 < len(formats) and _is_forbidden(exc):
                    continue
                raise
            files = [p for p in Path(tmp).iterdir() if p.is_file()]
            if files:
                return files[0].read_bytes()
            last_error = ValueError(f"yt-dlp produced no audio for {source_url}")
            if index + 1 < len(formats):
                continue
            raise last_error
        if last_error is not None:
            raise last_error
        raise ValueError(f"yt-dlp produced no audio for {source_url}")
