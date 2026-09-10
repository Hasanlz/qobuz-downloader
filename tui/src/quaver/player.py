"""Audio playback for downloaded tracks.

Prefers mpv (rich IPC control), falls back to ffplay (pause via SIGSTOP/SIGCONT,
no seek/volume), and degrades to a silent stub when neither exists.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PlayerState:
    loaded: bool = False
    paused: bool = False
    position: float = 0.0
    duration: float | None = None
    label: str = ""
    backend: str = ""


class NullPlayer:
    """No playable backend available."""

    def __init__(self) -> None:
        self.state = PlayerState()

    def play(self, source: str | Path, label: str) -> None:
        self.state.label = label

    def toggle(self) -> bool | None:
        return None

    def stop(self) -> None:
        pass

    def volume(self, delta: int) -> None:
        pass

    def poll(self) -> PlayerState:
        return self.state

    def close(self) -> None:
        pass


class MpvPlayer:
    """mpv driven over its JSON IPC socket."""

    def __init__(self) -> None:
        self._sock_path = os.path.join(
            tempfile.gettempdir(), f"quaver-mpv-{os.getpid()}.sock"
        )
        self._proc: subprocess.Popen | None = None
        self.state = PlayerState(backend="mpv")
        self._start_mpv()

    def _start_mpv(self) -> None:
        self._proc = subprocess.Popen(
            [
                "mpv",
                "--no-video",
                "--idle=yes",
                "--keep-open=no",
                f"--input-ipc-server={self._sock_path}",
                "--msg-level=all=no",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(50):
            if os.path.exists(self._sock_path):
                return
            time.sleep(0.1)

    def _command(self, command: list) -> dict | None:
        if not os.path.exists(self._sock_path):
            return None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                sock.connect(self._sock_path)
                sock.sendall((json.dumps({"command": command}) + "\n").encode())
                data = sock.recv(4096).decode()
            return json.loads(data.splitlines()[0]) if data else None
        except (OSError, json.JSONDecodeError):
            return None

    def play(self, source: str | Path, label: str) -> None:
        self._command(["loadfile", str(source), "replace"])
        self.state.loaded = True
        self.state.paused = False
        self.state.label = label
        self.state.position = 0.0
        self.state.duration = None

    def toggle(self) -> bool | None:
        if not self.state.loaded:
            return None
        self._command(["cycle", "pause"])
        self.state.paused = not self.state.paused
        return self.state.paused

    def stop(self) -> None:
        self._command(["stop"])
        self.state.loaded = False
        self.state.paused = False
        self.state.label = ""
        self.state.position = 0.0
        self.state.duration = None

    def volume(self, delta: int) -> None:
        self._command(["add", "volume", delta])

    def poll(self) -> PlayerState:
        if self.state.loaded:
            reply = self._command(["get_property", "time-pos"])
            if reply and not reply.get("error"):
                self.state.position = float(reply.get("data") or 0.0)
            reply = self._command(["get_property", "duration"])
            if reply and not reply.get("error") and reply.get("data") is not None:
                self.state.duration = float(reply["data"])
            reply = self._command(["get_property", "idle-active"])
            if reply and reply.get("data"):
                # file finished
                self.state.loaded = False
                self.state.label = ""
                self.state.position = 0.0
        return self.state

    def close(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                pass
        if os.path.exists(self._sock_path):
            try:
                os.unlink(self._sock_path)
            except OSError:
                pass


class FfplayPlayer:
    """ffplay fallback: pause via SIGSTOP/SIGCONT, stop via SIGTERM."""

    def __init__(self) -> None:
        self.state = PlayerState(backend="ffplay")
        self._proc: subprocess.Popen | None = None
        self._started_at: float = 0.0
        self._paused_elapsed: float = 0.0
        self._paused_since: float | None = None

    def play(self, source: str | Path, label: str) -> None:
        self.stop()
        self._proc = subprocess.Popen(
            [
                "ffplay",
                "-nodisp",
                "-autoexit",
                "-loglevel", "quiet",
                str(source),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.state = PlayerState(
            loaded=True, paused=False, label=label, backend="ffplay"
        )
        self._started_at = time.monotonic()
        self._paused_elapsed = 0.0
        self._paused_since = None

    def toggle(self) -> bool | None:
        if self._proc is None or self._proc.poll() is not None:
            return None
        if self.state.paused:
            os.killpg(os.getpgid(self._proc.pid), signal.SIGCONT)
            self._paused_elapsed += time.monotonic() - (self._paused_since or 0)
            self._paused_since = None
            self.state.paused = False
        else:
            os.killpg(os.getpgid(self._proc.pid), signal.SIGSTOP)
            self._paused_since = time.monotonic()
            self.state.paused = True
        return self.state.paused

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGCONT)
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError, ProcessLookupError):
                pass
        self._proc = None
        self.state = PlayerState(backend="ffplay")

    def volume(self, delta: int) -> None:
        pass  # ffplay has no runtime volume control

    def poll(self) -> PlayerState:
        if self._proc is not None and self._proc.poll() is not None:
            self.state = PlayerState(backend="ffplay")
            self._proc = None
        elif self.state.loaded:
            self.state.position = self._paused_elapsed if self.state.paused else (
                self._paused_elapsed + time.monotonic() - self._started_at
            )
        return self.state

    def close(self) -> None:
        self.stop()


def detect_player() -> NullPlayer | MpvPlayer | FfplayPlayer:
    if shutil.which("mpv"):
        try:
            return MpvPlayer()
        except OSError:
            pass
    if shutil.which("ffplay"):
        return FfplayPlayer()
    return NullPlayer()
