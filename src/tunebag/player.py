"""Local audio player supervised by the device agent.

The browser is a remote control: closing it must not stop playback. Prefer
ffplay (seekable), then afplay on macOS.
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Protocol

_logger = logging.getLogger(__name__)

# Prefer a fast stop path: SIGTERM briefly, then SIGKILL. Never leave an
# unreaped child when wait times out after kill.
_STOP_TERM_TIMEOUT = 0.4
_STOP_KILL_TIMEOUT = 0.5


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
    """Play a local file with ffplay or afplay.

    Owns a single child process group under a lock so concurrent play/stop
    cannot orphan a prior ffplay. Registered with atexit so agent death does
    not leave audio running.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        atexit.register(self.stop)

    def play(self, path: Path, *, start_seconds: float = 0) -> None:
        with self._lock:
            self._stop_locked()
            if not path.is_file():
                raise FileNotFoundError(f"audio file missing: {path}")
            cmd = _player_command(path, start_seconds=start_seconds)
            kwargs: dict[str, object] = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if os.name != "nt":
                # New session ⇒ pid is process-group leader; stop can killpg.
                kwargs["start_new_session"] = True
            self._proc = subprocess.Popen(cmd, **kwargs)  # type: ignore[arg-type]

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def is_alive(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def _stop_locked(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        if proc.poll() is not None:
            return
        t0 = time.monotonic()
        self._signal_group(proc, signal.SIGTERM)
        try:
            proc.wait(timeout=_STOP_TERM_TIMEOUT)
        except subprocess.TimeoutExpired:
            self._signal_group(proc, signal.SIGKILL)
            try:
                proc.wait(timeout=_STOP_KILL_TIMEOUT)
            except subprocess.TimeoutExpired:
                _logger.warning(
                    "audio child pid=%s did not exit after SIGKILL (%.0fms)",
                    proc.pid,
                    (time.monotonic() - t0) * 1000,
                )
                return
        elapsed_ms = (time.monotonic() - t0) * 1000
        if elapsed_ms >= 50:
            _logger.info("audio stop took %.0fms (pid=%s)", elapsed_ms, proc.pid)

    @staticmethod
    def _signal_group(proc: subprocess.Popen[bytes], sig: signal.Signals) -> None:
        try:
            if os.name != "nt" and proc.pid is not None:
                os.killpg(proc.pid, sig)
            elif sig is signal.SIGTERM:
                proc.terminate()
            else:
                proc.kill()
        except ProcessLookupError:
            return
        except OSError as exc:
            _logger.debug("signal %s to pid=%s failed: %s", sig, proc.pid, exc)


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
