"""Persistent per-track hold (pause) store in a sidecar SQLite table."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class Holds:
    """Tracks held (paused) by the user, stored next to the queue DB.

    Read from the worker thread and written from the UI thread, so the
    connection opts out of sqlite's same-thread check and serializes access.
    """

    def __init__(self, db_path: Path) -> None:
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS tui_holds (id TEXT PRIMARY KEY)"
            )
            self._db.commit()

    def all(self) -> set[str]:
        with self._lock:
            if self._db is None:
                return set()
            try:
                return {row[0] for row in self._db.execute("SELECT id FROM tui_holds")}
            except sqlite3.ProgrammingError:
                return set()  # closed during logout; empty is the safe answer

    def add(self, track_id: str) -> None:
        with self._lock:
            with self._db:
                self._db.execute(
                    "INSERT OR IGNORE INTO tui_holds (id) VALUES (?)", (track_id,)
                )

    def remove(self, track_id: str) -> None:
        with self._lock:
            with self._db:
                self._db.execute("DELETE FROM tui_holds WHERE id = ?", (track_id,))

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None
