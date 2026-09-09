import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from qobuz_downloader.domain import Track


class Status(Enum):
    PENDING = auto()
    COMPLETE = auto()
    FAILED = auto()


@dataclass(frozen=True, slots=True)
class AddedReport:
    added: list[Track]
    skipped: list[Track]


class Queue(ABC):
    @abstractmethod
    def add(self, tracks: list[Track]) -> AddedReport: ...

    @abstractmethod
    def pending(self, limit: int | None = None) -> list[Track]: ...

    @abstractmethod
    def complete(self, track: Track) -> None: ...

    @abstractmethod
    def fail(self, track: Track, reason: str) -> None: ...

    @abstractmethod
    def requeue_failed(self) -> int: ...


class InMemoryQueue(Queue):
    def __init__(self) -> None:
        self._tracks: dict[str, Track] = {}
        self._status: dict[str, Status] = {}
        self._reasons: dict[str, str] = {}

    def add(self, tracks: list[Track]) -> AddedReport:
        added: list[Track] = []
        skipped: list[Track] = []
        for track in tracks:
            status = self._status.get(track.id)
            if status is Status.PENDING or status is Status.COMPLETE:
                skipped.append(track)
                continue
            self._tracks[track.id] = track
            self._status[track.id] = Status.PENDING
            added.append(track)
        return AddedReport(added=added, skipped=skipped)

    def pending(self, limit: int | None = None) -> list[Track]:
        tracks = [
            self._tracks[track_id]
            for track_id, status in self._status.items()
            if status is Status.PENDING
        ]
        return tracks if limit is None else tracks[:limit]

    def complete(self, track: Track) -> None:
        self._status[track.id] = Status.COMPLETE

    def fail(self, track: Track, reason: str) -> None:
        self._status[track.id] = Status.FAILED
        self._reasons[track.id] = reason

    def requeue_failed(self) -> int:
        failed = [
            track_id
            for track_id, status in self._status.items()
            if status is Status.FAILED
        ]
        for track_id in failed:
            self._status[track_id] = Status.PENDING
            self._reasons.pop(track_id, None)
        return len(failed)


_COLUMNS = (
    "id, title, artist, album, track_number, duration_seconds, collection, track_total"
)


class SqliteQueue(Queue):
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS tracks ("
            "id TEXT PRIMARY KEY, "
            "title TEXT NOT NULL, "
            "artist TEXT NOT NULL, "
            "album TEXT NOT NULL, "
            "track_number INTEGER, "
            "duration_seconds INTEGER, "
            "status TEXT NOT NULL, "
            "reason TEXT, "
            "collection TEXT, "
            "track_total INTEGER)"
        )
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(tracks)")}
        for name, kind in (("collection", "TEXT"), ("track_total", "INTEGER")):
            if name not in columns:
                # queue database from an older version
                self._db.execute(f"ALTER TABLE tracks ADD COLUMN {name} {kind}")
                self._db.commit()

    def add(self, tracks: list[Track]) -> AddedReport:
        added: list[Track] = []
        skipped: list[Track] = []
        with self._db:
            for track in tracks:
                row = self._db.execute(
                    "SELECT status FROM tracks WHERE id = ?", (track.id,)
                ).fetchone()
                if row and row[0] in (Status.PENDING.name, Status.COMPLETE.name):
                    skipped.append(track)
                    continue
                self._db.execute(
                    "INSERT INTO tracks (id, title, artist, album, track_number, duration_seconds, status, reason, collection, track_total)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(id) DO UPDATE SET status = excluded.status,"
                    " title = excluded.title, artist = excluded.artist,"
                    " album = excluded.album, track_number = excluded.track_number,"
                    " duration_seconds = excluded.duration_seconds,"
                    " reason = excluded.reason, collection = excluded.collection,"
                    " track_total = excluded.track_total",
                    (
                        track.id,
                        track.title,
                        track.artist,
                        track.album,
                        track.track_number,
                        track.duration_seconds,
                        Status.PENDING.name,
                        None,
                        track.collection,
                        track.track_total,
                    ),
                )
                added.append(track)
        return AddedReport(added=added, skipped=skipped)

    def pending(self, limit: int | None = None) -> list[Track]:
        query = f"SELECT {_COLUMNS} FROM tracks WHERE status = ? ORDER BY rowid"
        parameters: list = [Status.PENDING.name]
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)
        return [
            Track(
                id=row[0],
                title=row[1],
                artist=row[2],
                album=row[3],
                track_number=row[4],
                duration_seconds=row[5],
                collection=row[6],
                track_total=row[7],
            )
            for row in self._db.execute(query, parameters)
        ]

    def complete(self, track: Track) -> None:
        with self._db:
            self._db.execute(
                "UPDATE tracks SET status = ? WHERE id = ?",
                (Status.COMPLETE.name, track.id),
            )

    def fail(self, track: Track, reason: str) -> None:
        with self._db:
            self._db.execute(
                "UPDATE tracks SET status = ?, reason = ? WHERE id = ?",
                (Status.FAILED.name, reason, track.id),
            )

    def requeue_failed(self) -> int:
        with self._db:
            cursor = self._db.execute(
                "UPDATE tracks SET status = ?, reason = NULL WHERE status = ?",
                (Status.PENDING.name, Status.FAILED.name),
            )
        return cursor.rowcount

    def close(self) -> None:
        self._db.close()
