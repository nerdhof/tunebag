"""yt-dlp fetch hardening: Referer header and hearthis 403 stream fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Self

import pytest

from tunebag.ytdlp_fetch import YtdlpCookies, fetch_audio_bytes


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


def test_hearthis_prefers_listen_stream_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yt_dlp.YoutubeDL", _FakeYDL)

    data = fetch_audio_bytes("https://hearthis.at/tasmo/echochamber280/")

    assert data == b"fake-audio"
    assert _FakeYDL.download_calls == 1
    assert _FakeYDL.instances[0].opts["format"] == "bestaudio[url*=listen]/bestaudio/best"
    assert _FakeYDL.instances[0].opts["http_headers"]["Referer"] == "https://hearthis.at/"


def test_hearthis_403_retries_with_download_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yt_dlp.YoutubeDL", _FakeYDL)
    _FakeYDL.fail_on_call = 1

    data = fetch_audio_bytes("https://hearthis.at/tasmo/echochamber280/")

    assert data == b"fake-audio"
    assert _FakeYDL.download_calls == 2
    assert _FakeYDL.instances[0].opts["format"] == "bestaudio[url*=listen]/bestaudio/best"
    assert _FakeYDL.instances[1].opts["format"] == "bestaudio/best"
    assert _FakeYDL.instances[1].opts["http_headers"]["Referer"] == "https://hearthis.at/"


def test_youtube_fetch_uses_progressive_bestaudio_ejs_noplaylist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("yt_dlp.YoutubeDL", _FakeYDL)

    data = fetch_audio_bytes("https://www.youtube.com/watch?v=abcdefghijk")

    assert data == b"fake-audio"
    assert len(_FakeYDL.instances) == 1
    opts = _FakeYDL.instances[0].opts
    assert opts["format"] == "bestaudio/best"
    assert opts["noplaylist"] is True
    assert opts["prefer_free_formats"] is True
    assert opts.get("remote_components") == ["ejs:github"]
    assert "cookiefile" not in opts
    assert "cookiesfrombrowser" not in opts
    assert "postprocessors" not in opts


def test_music_youtube_fetch_also_enables_ejs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yt_dlp.YoutubeDL", _FakeYDL)

    data = fetch_audio_bytes("https://music.youtube.com/watch?v=abcdefghijk")

    assert data == b"fake-audio"
    assert _FakeYDL.instances[0].opts.get("remote_components") == ["ejs:github"]
    assert _FakeYDL.instances[0].opts["noplaylist"] is True


def test_non_youtube_fetch_does_not_enable_ejs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yt_dlp.YoutubeDL", _FakeYDL)

    for url in (
        "https://soundcloud.com/dj-x/track",
        "https://hearthis.at/tasmo/echochamber280/",
        "https://artist.bandcamp.com/track/song",
    ):
        _FakeYDL.instances = []
        _FakeYDL.download_calls = 0
        data = fetch_audio_bytes(url)
        assert data == b"fake-audio"
        for instance in _FakeYDL.instances:
            assert "remote_components" not in instance.opts
            assert "cookiefile" not in instance.opts
            assert "cookiesfrombrowser" not in instance.opts


def test_youtube_auth_challenge_surfaces_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _AuthFailYDL(_FakeYDL):
        def download(self, urls: list[str]) -> None:
            del urls
            from yt_dlp.utils import DownloadError

            raise DownloadError(
                "ERROR: [youtube] abcdefghijk: Sign in to confirm you’re not a bot"
            )

    monkeypatch.setattr("yt_dlp.YoutubeDL", _AuthFailYDL)

    with pytest.raises(ValueError) as excinfo:
        fetch_audio_bytes("https://www.youtube.com/watch?v=abcdefghijk")

    message = str(excinfo.value).lower()
    assert "anonymous" in message
    assert "cookie" in message
    assert "--cookies" in message or "cookies-from-browser" in message
    assert "youtube" in message


def test_youtube_fetch_forwards_cookiefile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yt_dlp.YoutubeDL", _FakeYDL)
    cookies = YtdlpCookies.from_cookiefile("/tmp/cookies.txt")

    data = fetch_audio_bytes(
        "https://www.youtube.com/watch?v=abcdefghijk",
        cookies=cookies,
    )

    assert data == b"fake-audio"
    opts = _FakeYDL.instances[0].opts
    assert opts["cookiefile"] == "/tmp/cookies.txt"
    assert "cookiesfrombrowser" not in opts
    assert opts.get("remote_components") == ["ejs:github"]


def test_youtube_fetch_forwards_cookies_from_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cookies = YtdlpCookies.from_browser("firefox")
    monkeypatch.setattr("yt_dlp.YoutubeDL", _FakeYDL)

    data = fetch_audio_bytes(
        "https://www.youtube.com/watch?v=abcdefghijk",
        cookies=cookies,
    )

    assert data == b"fake-audio"
    opts = _FakeYDL.instances[0].opts
    assert opts["cookiesfrombrowser"] == ("firefox", None, None, None)
    assert "cookiefile" not in opts


def test_non_youtube_fetch_ignores_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yt_dlp.YoutubeDL", _FakeYDL)
    cookies = YtdlpCookies.from_cookiefile("/tmp/cookies.txt")

    data = fetch_audio_bytes(
        "https://hearthis.at/tasmo/echochamber280/",
        cookies=cookies,
    )

    assert data == b"fake-audio"
    assert "cookiefile" not in _FakeYDL.instances[0].opts


def test_youtube_auth_challenge_with_cookies_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _AuthFailYDL(_FakeYDL):
        def download(self, urls: list[str]) -> None:
            del urls
            from yt_dlp.utils import DownloadError

            raise DownloadError(
                "ERROR: [youtube] abcdefghijk: Sign in to confirm you’re not a bot"
            )

    monkeypatch.setattr("yt_dlp.YoutubeDL", _AuthFailYDL)

    with pytest.raises(ValueError) as excinfo:
        fetch_audio_bytes(
            "https://www.youtube.com/watch?v=abcdefghijk",
            cookies=YtdlpCookies.from_cookiefile("/tmp/cookies.txt"),
        )

    message = str(excinfo.value).lower()
    assert "still blocked" in message
    assert "does not use" not in message
