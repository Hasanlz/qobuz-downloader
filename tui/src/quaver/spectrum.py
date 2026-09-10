"""Audio-reactive spectrum for the player bar.

Runs a parallel ffmpeg decode of the same source and samples RMS loudness
(lavfi.astats), so the bars genuinely react to the music rather than faking it.
"""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import threading
from collections import deque

_RMS_RE = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(-?[\d.]+|-inf)")
_BLOCKS = "▁▂▃▄▅▆▇█"
_MIN_DB = -45.0
_MAX_DB = -5.0


class Spectrum:
    """Rolling RMS history rendered as block characters."""

    def __init__(self, history: int = 48) -> None:
        self._values: deque[float] = deque(maxlen=history)
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._source = ""

    def start(self, source: str) -> None:
        """Begin sampling loudness for a file or stream URL."""
        self.stop()
        if not shutil.which("ffmpeg"):
            return
        self._source = source
        self._stop.clear()
        with self._lock:
            self._values.clear()
        self._proc = subprocess.Popen(
            [
                "ffmpeg", "-hide_banner", "-nostats",
                "-i", source,
                "-af", "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
                "-f", "null", "-",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        self._thread = threading.Thread(target=self._read, daemon=True, name="quaver-spectrum")
        self._thread.start()

    def _read(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        for line in self._proc.stderr:
            if self._stop.is_set():
                break
            match = _RMS_RE.search(line)
            if match is None:
                continue
            raw = match.group(1)
            try:
                db = -120.0 if raw == "-inf" else float(raw)
            except ValueError:
                continue
            with self._lock:
                self._values.append(db)

    def stop(self) -> None:
        self._stop.set()
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.kill()
            except OSError:
                pass
        self._proc = None

    def close(self) -> None:
        self.stop()

    def bars(self, width: int) -> str:
        """Render the most recent `width` loudness samples as blocks."""
        with self._lock:
            recent = list(self._values)[-width:]
        out = []
        for db in recent:
            level = (db - _MIN_DB) / (_MAX_DB - _MIN_DB)
            level = max(0.0, min(1.0, level))
            index = int(level * (len(_BLOCKS) - 1) + 0.5)
            out.append(_BLOCKS[index])
        pad = _BLOCKS[0] * (width - len(out))
        return "".join(out) + pad

    def level(self) -> float:
        """Latest normalized loudness, 0..1."""
        with self._lock:
            if not self._values:
                return 0.0
            db = self._values[-1]
        level = (db - _MIN_DB) / (_MAX_DB - _MIN_DB)
        return max(0.0, min(1.0, level))
