"""yt-dlp fetch hardening: Referer header and hearthis 403 stream fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Self

import pytest

from tunebag.ytdlp_fetch import fetch_audio_bytes


class _FakeYDL:
    """Capture opts and optionally fail once with a DownloadError."""

    instances: ClassVar[list[_FakeYDL]] = []
    download_calls: ClassVar[int] = 0
    fail_on_call: ClassVar[int | None] = None

    def __init__(self, opts: dict[str, Any]) -> None:
        self.opts = opts
        self._tmp = Path(opts["outtmpl"]).parent
        _FakeYDL.instances.append(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def download(self, urls: list[str]) -> None:
        del urls
        _FakeYDL.download_calls += 1
        if (
            _FakeYDL.fail_on_call is not None
            and _FakeYDL.download_calls == _FakeYDL.fail_on_call
        ):
            from yt_dlp.utils import DownloadError

            raise DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden")
        (self._tmp / "audio.mp3").write_bytes(b"fake-audio")


@pytest.fixture(autouse=True)
def _reset_fake_ydl() -> None:
    _FakeYDL.instances = []
    _FakeYDL.download_calls = 0
    _FakeYDL.fail_on_call = None


def test_hearthis_fetch_sends_permalink_referer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yt_dlp.YoutubeDL", _FakeYDL)

    data = fetch_audio_bytes("https://hearthis.at/tasmo/echochamber280/")

    assert data == b"fake-audio"
    assert len(_FakeYDL.instances) == 1
    headers = _FakeYDL.instances[0].opts.get("http_headers") or {}
    assert headers.get("Referer") == "https://hearthis.at/"


def test_hearthis_403_retries_with_stream_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yt_dlp.YoutubeDL", _FakeYDL)
    _FakeYDL.fail_on_call = 1

    data = fetch_audio_bytes("https://hearthis.at/tasmo/echochamber280/")

    assert data == b"fake-audio"
    assert _FakeYDL.download_calls == 2
    assert _FakeYDL.instances[0].opts["format"] == "bestaudio/best"
    assert _FakeYDL.instances[1].opts["format"] == "mp3/bestaudio/best"
    assert _FakeYDL.instances[1].opts["http_headers"]["Referer"] == "https://hearthis.at/"
