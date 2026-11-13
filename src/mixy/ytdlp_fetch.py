"""Download audio bytes for a track permalink via yt-dlp."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path

AudioFetcher = Callable[[str], bytes]


def fetch_audio_bytes(
    source_url: str,
    *,
    fetcher: AudioFetcher | None = None,
) -> bytes:
    """Return audio bytes for a SoundCloud or hearthis permalink."""
    if fetcher is not None:
        return fetcher(source_url)
    return _ytdlp_fetch(source_url)


def _ytdlp_fetch(source_url: str) -> bytes:
    from yt_dlp import YoutubeDL

    with tempfile.TemporaryDirectory() as tmp:
        outtmpl = str(Path(tmp) / "audio.%(ext)s")
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "noplaylist": True,
            # Prefer progressive HTTP so demo fill does not require ffmpeg.
            "prefer_free_formats": True,
        }
        with YoutubeDL(opts) as ydl:
            ydl.download([source_url])
        files = [p for p in Path(tmp).iterdir() if p.is_file()]
        if not files:
            raise ValueError(f"yt-dlp produced no audio for {source_url}")
        return files[0].read_bytes()
