"""SubprocessPlayer stop hygiene: process group, lock, no orphan after stop."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from tunebag.player import SubprocessPlayer


@pytest.mark.skipif(os.name == "nt", reason="process groups are Unix-specific")
def test_stop_kills_process_group(tmp_path: Path) -> None:
    audio = tmp_path / "silent.bin"
    audio.write_bytes(b"x")
    player = SubprocessPlayer()
    # Long-lived child so stop must signal; sleep is the process-group leader.
    with patch(
        "tunebag.player._player_command",
        return_value=["sleep", "30"],
    ):
        player.play(audio)
    assert player.is_alive()
    pid = player._proc.pid  # noqa: SLF001 — assert process group teardown
    assert pid is not None
    player.stop()
    assert player.is_alive() is False
    # Child (and group) must be gone; wait briefly for kernel reaping.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"child pid={pid} still alive after stop")


@pytest.mark.skipif(os.name == "nt", reason="process groups are Unix-specific")
def test_play_replaces_prior_child(tmp_path: Path) -> None:
    audio = tmp_path / "silent.bin"
    audio.write_bytes(b"x")
    player = SubprocessPlayer()
    with patch(
        "tunebag.player._player_command",
        return_value=["sleep", "30"],
    ):
        player.play(audio)
        first = player._proc.pid  # noqa: SLF001
        player.play(audio)
        second = player._proc.pid  # noqa: SLF001
    assert first is not None and second is not None
    assert first != second
    try:
        os.kill(first, 0)
        still_alive = True
    except ProcessLookupError:
        still_alive = False
    assert still_alive is False
    player.stop()
