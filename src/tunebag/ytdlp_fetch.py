"""Download audio bytes for a track permalink via yt-dlp."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

AudioFetcher = Callable[[str], bytes]
ProgressCallback = Callable[[int, int | None], None]


@dataclass(frozen=True)
class YtdlpCookies:
    """Optional YouTube cookie escape hatch forwarded into YoutubeDL opts."""

    cookiefile: str | None = None
    cookiesfrombrowser: tuple[Any, ...] | None = None

    def __post_init__(self) -> None:
        if self.cookiefile and self.cookiesfrombrowser is not None:
            raise ValueError("set cookiefile or cookiesfrombrowser, not both")
        if not self.cookiefile and self.cookiesfrombrowser is None:
            raise ValueError("YtdlpCookies requires cookiefile or cookiesfrombrowser")

    @classmethod
    def from_cookiefile(cls, path: str) -> YtdlpCookies:
        return cls(cookiefile=path)

    @classmethod
    def from_browser(cls, spec: str) -> YtdlpCookies:
        """Parse yt-dlp --cookies-from-browser SPEC into the API tuple."""
        from yt_dlp import parse_options

        opts = parse_options(["--cookies-from-browser", spec]).ydl_opts
        value = opts.get("cookiesfrombrowser")
        if value is None:
            raise ValueError(f"invalid --cookies-from-browser spec: {spec!r}")
        return cls(cookiesfrombrowser=tuple(value))

    @property
    def configured(self) -> bool:
        return bool(self.cookiefile) or self.cookiesfrombrowser is not None


def apply_ytdlp_cookies(
    opts: dict[str, Any],
    cookies: YtdlpCookies | None,
    *,
    for_youtube: bool,
) -> None:
    """Merge cookie opts in-place for YouTube hosts only."""
    if not for_youtube or cookies is None:
        return
    if cookies.cookiefile:
        opts["cookiefile"] = cookies.cookiefile
    if cookies.cookiesfrombrowser is not None:
        opts["cookiesfrombrowser"] = cookies.cookiesfrombrowser


def fetch_audio_bytes(
    source_url: str,
    *,
    fetcher: AudioFetcher | None = None,
    on_progress: ProgressCallback | None = None,
    cookies: YtdlpCookies | None = None,
) -> bytes:
    """Return audio bytes for a track permalink (SoundCloud, hearthis, Bandcamp, YouTube)."""
    if fetcher is not None:
        return fetcher(source_url)
    return _ytdlp_fetch(source_url, on_progress=on_progress, cookies=cookies)


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


def _is_youtube(source_url: str) -> bool:
    host = (urlparse(source_url).hostname or "").lower()
    return "youtube.com" in host or host == "youtu.be"


def youtube_auth_challenge(exc: BaseException) -> bool:
    """True when yt-dlp failed due to login / bot / cookie gates."""
    text = str(exc).lower()
    markers = (
        "sign in",
        "login required",
        "confirm you're not a bot",
        "confirm you’re not a bot",
        "cookies are needed",
        "use --cookies",
        "cookie file",
    )
    return any(marker in text for marker in markers)


def youtube_anonymous_blocked_error(
    source_url: str,
    exc: BaseException,
    *,
    cookies: YtdlpCookies | None = None,
) -> ValueError:
    """Actionable error when YouTube access is blocked by auth / bot gates."""
    if cookies is not None and cookies.configured:
        hint = "cookies were configured but YouTube still blocked access"
    else:
        hint = (
            "pass tunebag serve --cookies FILE or "
            "--cookies-from-browser BROWSER when anonymous access is blocked"
        )
    return ValueError(
        f"YouTube blocked anonymous access for {source_url}; {hint}. "
        f"Original error: {exc}"
    )


def _ytdlp_fetch(
    source_url: str,
    *,
    on_progress: ProgressCallback | None = None,
    cookies: YtdlpCookies | None = None,
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
            if _is_youtube(source_url):
                # YouTube: always enable remote JS; cookies only when configured.
                opts["remote_components"] = ["ejs:github"]
                apply_ytdlp_cookies(opts, cookies, for_youtube=True)
            if on_progress is not None:
                opts["progress_hooks"] = [_hook]
            try:
                with YoutubeDL(opts) as ydl:
                    ydl.download([source_url])
            except DownloadError as exc:
                last_error = exc
                if index + 1 < len(formats) and _is_forbidden(exc):
                    continue
                if _is_youtube(source_url) and youtube_auth_challenge(exc):
                    raise youtube_anonymous_blocked_error(
                        source_url, exc, cookies=cookies
                    ) from exc
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
