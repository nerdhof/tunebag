"""Download audio bytes for a track permalink via yt-dlp."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

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


def _ytdlp_fetch(
    source_url: str,
    *,
    on_progress: ProgressCallback | None = None,
) -> bytes:
    from yt_dlp import YoutubeDL

    def _hook(info: dict[str, Any]) -> None:
        if on_progress is None or info.get("status") != "downloading":
            return
        downloaded = int(info.get("downloaded_bytes") or 0)
        total = info.get("total_bytes")
        if total is None:
            total = info.get("total_bytes_estimate")
        total_int = int(total) if total is not None else None
        on_progress(downloaded, total_int)

    with tempfile.TemporaryDirectory() as tmp:
        outtmpl = str(Path(tmp) / "audio.%(ext)s")
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "noplaylist": True,
            # Prefer progressive HTTP so demo fill does not require ffmpeg.
            "prefer_free_formats": True,
        }
        if on_progress is not None:
            opts["progress_hooks"] = [_hook]
        with YoutubeDL(opts) as ydl:
            ydl.download([source_url])
        files = [p for p in Path(tmp).iterdir() if p.is_file()]
        if not files:
            raise ValueError(f"yt-dlp produced no audio for {source_url}")
        return files[0].read_bytes()
