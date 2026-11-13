"""Local audio player supervised by the device agent.

The browser is a remote control: closing it must not stop playback. Prefer
ffplay (seekable), then afplay on macOS.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Protocol


class AudioPlayer(Protocol):
    def play(self, path: Path, *, start_seconds: float = 0) -> None: ...

    def stop(self) -> None: ...

    def is_alive(self) -> bool: ...


class NullPlayer:
    """No-op player for tests (tracks play/stop without audio)."""

    def __init__(self) -> None:
        self._alive = False

    def play(self, path: Path, *, start_seconds: float = 0) -> None:
        self._alive = True

    def stop(self) -> None:
        self._alive = False

    def is_alive(self) -> bool:
        return self._alive


class SubprocessPlayer:
    """Play a local file with ffplay or afplay."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen[bytes] | None = None

    def play(self, path: Path, *, start_seconds: float = 0) -> None:
        self.stop()
        if not path.is_file():
            raise FileNotFoundError(f"audio file missing: {path}")
        cmd = _player_command(path, start_seconds=start_seconds)
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None


def default_player() -> AudioPlayer:
    if shutil.which("ffplay") or shutil.which("afplay"):
        return SubprocessPlayer()
    return NullPlayer()


def _player_command(path: Path, *, start_seconds: float) -> list[str]:
    if shutil.which("ffplay"):
        cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error"]
        if start_seconds > 0:
            cmd.extend(["-ss", str(start_seconds)])
        cmd.append(str(path))
        return cmd
    if shutil.which("afplay"):
        # afplay has no seek; resume from start on macOS fallback.
        return ["afplay", str(path)]
    raise RuntimeError("no local audio player found (install ffplay or afplay)")
