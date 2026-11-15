"""CLI default_data_dir: per --name isolation under ~/.tunebag/<name>/."""

from __future__ import annotations

from pathlib import Path

import pytest

from tunebag.cli import default_data_dir


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
