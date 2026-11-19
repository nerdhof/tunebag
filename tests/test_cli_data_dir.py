"""CLI default_data_dir: per --name isolation under ~/.tunebag/<name>/."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from tunebag.cli import default_data_dir, main, ytdlp_cookies_from_args


def test_default_data_dir_uses_name_under_home(monkeypatch: pytest.MonkeyPatch) -> None:
    home = Path("/tmp/fake-home")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    assert default_data_dir("phone") == home / ".tunebag" / "phone"
    assert default_data_dir("  laptop  ") == home / ".tunebag" / "laptop"


def test_default_data_dir_sanitizes_path_chars(monkeypatch: pytest.MonkeyPatch) -> None:
    home = Path("/tmp/fake-home")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    assert default_data_dir("a/b") == home / ".tunebag" / "a_b"
    assert default_data_dir("a\\b") == home / ".tunebag" / "a_b"
    assert default_data_dir("a\0b") == home / ".tunebag" / "a_b"


def test_default_data_dir_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        default_data_dir("   ")
    with pytest.raises(ValueError, match="empty"):
        default_data_dir("")


def test_serve_rejects_both_cookie_flags() -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "serve",
                "--name",
                "phone",
                "--cookies",
                "/tmp/cookies.txt",
                "--cookies-from-browser",
                "firefox",
            ]
        )


def test_ytdlp_cookies_from_args_cookiefile() -> None:
    args = argparse.Namespace(cookies="/tmp/cookies.txt", cookies_from_browser=None)
    cookies = ytdlp_cookies_from_args(args)
    assert cookies is not None
    assert cookies.cookiefile == "/tmp/cookies.txt"
    assert cookies.cookiesfrombrowser is None


def test_ytdlp_cookies_from_args_browser() -> None:
    args = argparse.Namespace(cookies=None, cookies_from_browser="firefox")
    cookies = ytdlp_cookies_from_args(args)
    assert cookies is not None
    assert cookies.cookiesfrombrowser == ("firefox", None, None, None)
    assert cookies.cookiefile is None


def test_ytdlp_cookies_from_args_none() -> None:
    args = argparse.Namespace(cookies=None, cookies_from_browser=None)
    assert ytdlp_cookies_from_args(args) is None
