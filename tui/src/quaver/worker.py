"""Background worker thread that drains the queue through the Engine."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from textual.message import Message

from qobuz_downloader.domain import Complete, Outcome, Quality, Track
from qobuz_downloader.engine import Engine
from qobuz_downloader.engine._source import ByteResponse, ByteSource
from qobuz_downloader.naming import Naming
from qobuz_downloader.queue import SqliteQueue

MAX_CONSECUTIVE_FAILURES = 5
PROGRESS_INTERVAL = 0.2  # seconds between progress updates
POLL_INTERVAL = 0.5  # seconds between queue polls while idle

_UNSET = object()


@dataclass(slots=True)
class WorkerEvent:
    kind: str  # current | progress | complete | failed | paused | idle | abort | stopped
    track: Track | None = None
    text: str = ""
    done: int = 0
    total: int | None = None
    outcome: Outcome | None = None


class WorkerEventMessage(Message):
    def __init__(self, event: WorkerEvent) -> None:
        super().__init__()
        self.event = event


class ProgressSource(ByteSource):
    """Wraps a byte source, counting streamed bytes and honouring cancellation.

    The report callback runs in the worker thread. Raising KeyboardInterrupt
    aborts the current attempt while keeping the .part file, so the Engine's
    range-resume picks up where it stopped. The Engine only catches Exception,
    so the interrupt surfaces cleanly to the worker loop.
    """

    def __init__(self, inner: ByteSource) -> None:
        self._inner = inner
        self._report: Callable[[int, int | None], None] = lambda done, total: None

    def begin(self, report: Callable[[int, int | None], None]) -> None:
        self._report = report

    def stream(self, url: str, start: int) -> ByteResponse:
        response = self._inner.stream(url, start)
        total = start + response.length if response.length is not None else None
        return ByteResponse(
            status=response.status,
            length=response.length,
            chunks=self._chunks(response.chunks, total),
        )

    def _chunks(self, chunks: Iterator[bytes], total: int | None) -> Iterator[bytes]:
        done = 0
        self._report(done, total)
        for chunk in chunks:
            done += len(chunk)
            self._report(done, total)
            yield chunk
        self._report(done, total)


class DownloadWorker(threading.Thread):
    """Owns a SqliteQueue connection and downloads pending tracks one at a time.

    All UI notification happens through app.post_message, which is thread-safe.
    """

    def __init__(
        self,
        app,
        qobuz,
        base_source: ByteSource,
        db_path: Path,
        naming: Naming,
        lyrics,  # LyricsSource | None
        quality: Quality,
        is_held=None,  # Callable[[str], bool]
    ) -> None:
        super().__init__(daemon=True, name="quaver-worker")
        self._app = app
        self._qobuz = qobuz
        self._progress = ProgressSource(base_source)
        self._db_path = db_path
        self._naming = naming
        self._lyrics = lyrics
        self._preferred = quality
        self._engine = Engine(qobuz, naming, source=self._progress, lyrics=lyrics)
        self._wake = threading.Event()
        self._stop_requested = threading.Event()
        self._cancel_current = threading.Event()
        self._busy = False
        self._is_held = is_held or (lambda track_id: False)

    def kick(self) -> None:
        self._wake.set()

    def set_quality(self, quality: Quality) -> None:
        self._preferred = quality

    def reconfigure(self, naming: Naming | object = _UNSET, lyrics: object = _UNSET) -> None:
        if naming is not _UNSET:
            self._naming = naming
        if lyrics is not _UNSET:
            self._lyrics = lyrics
        self._engine = Engine(self._qobuz, self._naming, source=self._progress, lyrics=self._lyrics)

    def pause(self) -> None:
        self._cancel_current.set()

    def resume(self) -> None:
        self._cancel_current.clear()
        self._wake.set()

    def stop(self) -> None:
        self._stop_requested.set()
        # interrupt an in-flight download so join() does not hang on a live
        # HTTP read (the .part file keeps its bytes for byte-resume)
        self._cancel_current.set()
        self._wake.set()

    def is_paused(self) -> bool:
        return self._cancel_current.is_set() and not self._stop_requested.is_set()

    def run(self) -> None:
        queue = SqliteQueue(self._db_path)
        consecutive = 0
        try:
            while not self._stop_requested.is_set():
                if self._cancel_current.is_set():
                    self._emit(WorkerEvent("paused"))
                    while not self._stop_requested.is_set() and self._cancel_current.is_set():
                        if self._wake.wait(POLL_INTERVAL):
                            self._wake.clear()
                    continue
                tracks = queue.pending(limit=200)
                track = pick_next(tracks, self._is_held)
                if track is None:
                    if tracks:
                        # Everything pending is on hold.
                        if self._busy:
                            self._busy = False
                            self._emit(WorkerEvent("idle", text="all tracks on hold"))
                    else:
                        if self._busy:
                            self._busy = False
                            self._emit(WorkerEvent("idle"))
                    if self._wake.wait(POLL_INTERVAL):
                        self._wake.clear()
                    continue
                self._emit(WorkerEvent("current", track=track))
                try:
                    outcome = self._download(track)
                except KeyboardInterrupt:
                    continue
                if isinstance(outcome, Complete):
                    queue.complete(track)
                    consecutive = 0
                    self._emit(WorkerEvent("complete", track=track, outcome=outcome))
                else:
                    queue.fail(track, outcome.reason)
                    consecutive += 1
                    self._emit(
                        WorkerEvent("failed", track=track, text=outcome.reason, outcome=outcome)
                    )
                    if consecutive >= MAX_CONSECUTIVE_FAILURES:
                        remaining = len(queue.pending())
                        self._emit(
                            WorkerEvent("abort", text=f"{remaining} track(s) still pending")
                        )
                        consecutive = 0
                        self._wake.clear()
                        while not self._stop_requested.is_set() and not self._wake.wait(
                            POLL_INTERVAL
                        ):
                            pass
                        self._wake.clear()
        finally:
            queue.close()
            self._emit(WorkerEvent("stopped"))

    def _download(self, track: Track) -> Outcome:
        last = [0.0]

        def report(done: int, total: int | None) -> None:
            if self._cancel_current.is_set():
                raise KeyboardInterrupt
            now = time.monotonic()
            if (total is not None and done >= total) or now - last[0] >= PROGRESS_INTERVAL:
                last[0] = now
                self._emit(WorkerEvent("progress", track=track, done=done, total=total))

        self._progress.begin(report)
        return self._engine.download(track, self._preferred)

    def _emit(self, event: WorkerEvent) -> None:
        self._app.post_message(WorkerEventMessage(event))


def pick_next(tracks: list[Track], is_held) -> Track | None:
    """First track that is not on hold, or None when everything is held."""
    for track in tracks:
        if not is_held(track.id):
            return track
    return None
