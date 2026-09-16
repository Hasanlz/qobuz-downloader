"""Cross-platform player backends: mpv (IPC), ffplay (signals), silent stub.

POSIX gives full control (SIGSTOP/SIGCONT pause, mpv JSON IPC over a unix
socket). Windows gets playback + terminate (no process suspend); mpv IPC there
goes over the named pipe mpv creates.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

WINDOWS = os.name == "nt"


def detach_kwargs() -> dict:
    """Popen kwargs that detach the child from the terminal's Ctrl+C."""
    if WINDOWS:
        # DETACHED_PROCESS: no console; CREATE_NEW_PROCESS_GROUP: ^C immune
        return {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
        }
    return {"start_new_session": True}


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

    supports_pause = False

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
    """mpv driven over its JSON IPC channel (unix socket or Windows named pipe)."""

    supports_pause = True

    def __init__(self) -> None:
        name = f"quaver-mpv-{os.getpid()}"
        if WINDOWS:
            self._target = rf"\\.\pipe\{name}"
        else:
            self._target = os.path.join(tempfile.gettempdir(), f"{name}.sock")
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
                f"--input-ipc-server={self._target}",
                "--msg-level=all=no",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **detach_kwargs(),
        )
        for _ in range(50):
            if self._target_available():
                return
            time.sleep(0.1)

    def _target_available(self) -> bool:
        if WINDOWS:
            try:
                handle = os.open(self._target, os.O_RDWR)
            except OSError:
                return False
            os.close(handle)
            return True
        return os.path.exists(self._target)

    def _command(self, command: list) -> dict | None:
        payload = (json.dumps({"command": command}) + "\n").encode()
        try:
            if WINDOWS:
                handle = os.open(self._target, os.O_RDWR)
                os.write(handle, payload)
                try:
                    data = os.read(handle, 4096)
                except OSError:
                    data = b""
                os.close(handle)
            else:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(0.5)
                    sock.connect(self._target)
                    sock.sendall(payload)
                    data = sock.recv(4096)
            line = data.decode(errors="replace").splitlines()
            return json.loads(line[0]) if line else None
        except (OSError, json.JSONDecodeError, IndexError):
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
        if not WINDOWS:
            try:
                os.unlink(self._target)
            except OSError:
                pass


class FfplayPlayer:
    """ffplay fallback: POSIX pause via SIGSTOP/SIGCONT; Windows play/stop."""

    supports_pause = not WINDOWS

    def __init__(self) -> None:
        self.state = PlayerState(backend="ffplay")
        self._proc: subprocess.Popen | None = None
        self._started_at: float = 0.0
        self._paused_elapsed: float = 0.0
        self._paused_since: float | None = None
        self._ffprobe: str | None = None

    def play(self, source: str | Path, label: str) -> None:
        self.stop()
        try:
            self._proc = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(source)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **detach_kwargs(),
            )
        except OSError:
            self._proc = None
            return
        self.state = PlayerState(
            loaded=True, paused=False, label=label, backend="ffplay"
        )
        self._started_at = time.monotonic()
        self._paused_elapsed = 0.0
        self._paused_since = None
        self._probe_duration_async(str(source))

    def _probe_duration_async(self, source: str) -> None:
        def worker() -> None:
            probe = self._find_ffprobe()
            if not probe:
                return
            try:
                result = subprocess.run(
                    [
                        probe, "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1",
                        source,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=25,
                    **detach_kwargs(),
                )
                seconds = float(result.stdout.strip())
            except (OSError, ValueError, subprocess.SubprocessError):
                return
            if seconds > 0 and self.state.loaded and self.state.duration is None:
                self.state.duration = seconds

        threading.Thread(target=worker, daemon=True, name="quaver-ffprobe").start()

    def _find_ffprobe(self) -> str | None:
        if self._ffprobe is not None:
            return self._ffprobe or None
        ffplay = shutil.which("ffplay")
        found = ""
        if ffplay:
            candidate = Path(ffplay).with_name(
                "ffprobe.exe" if WINDOWS else "ffprobe"
            )
            if candidate.exists():
                found = str(candidate)
        self._ffprobe = found
        return found or None

    def toggle(self) -> bool | None:
        if self._proc is None or self._proc.poll() is not None or WINDOWS:
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
                if not WINDOWS:
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
