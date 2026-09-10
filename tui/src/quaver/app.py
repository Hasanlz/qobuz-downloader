"""Qobuz Downloader TUI — a Textual front end for qobuz-downloader."""

from __future__ import annotations

import os
import signal
import sqlite3
import threading
from pathlib import Path

import httpx
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual import events
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    ProgressBar,
    RichLog,
    Select,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)

from qobuz_downloader.domain import (
    Album,
    Matched,
    Quality,
    Track,
    Unmatched,
    UnmatchedTrack,
)
import spotapi

from qobuz_downloader.engine._source import ByteSource, HttpByteSource
from qobuz_downloader.lyrics import LrcLib
from qobuz_downloader.match import make_matcher
from qobuz_downloader.naming import Naming
from qobuz_downloader.queue import AddedReport, SqliteQueue

from .holds import Holds
from .input import SafeInput
from .login import LoginFailed, LoginScreen, LoginSucceeded, credentials_from_env
from .net import normalize_proxy_env
from .player import PlayerState, detect_player
from .spectrum import Spectrum
from .settings import Settings, config_dir, load as load_settings, save as save_settings
from .worker import DownloadWorker, WorkerEvent, WorkerEventMessage

_UNSET = object()

_QUALITY_OPTIONS = [
    ("CD (16/44.1)", Quality.CD),
    ("Hi-Res 96 (24/96)", Quality.HIRES_96),
    ("Hi-Res 192 (24/192)", Quality.HIRES_192),
]
_QUALITY_KEYS = {"cd": Quality.CD, "hires96": Quality.HIRES_96, "hires": Quality.HIRES_192}
_SEEK_WIDTH = 24
_SPECTRUM_WIDTH = 24

_GLYPHS = {
    "pending": "·",
    "downloading": "⬇",
    "paused": "⏸",
    "held": "⏸",
    "complete": "✔",
    "failed": "✘",
}


def _collect(
    qobuz, matcher, url: str
) -> tuple[list[Track], list[UnmatchedTrack]]:
    if "qobuz.com" in url:
        return qobuz.tracks(qobuz.item(url)), []
    result = matcher.match(url)
    if isinstance(result, Unmatched):
        return [], [UnmatchedTrack(title=url, artist="", reason=result.reason)]
    return result.tracks, result.unmatched


def _human_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


class Notice(Message):
    def __init__(self, level: str, text: str) -> None:
        super().__init__()
        self.level = level
        self.text = text


class SearchResults(Message):
    def __init__(self, tracks: list[Track], albums: list[Album]) -> None:
        super().__init__()
        self.tracks = tracks
        self.albums = albums


class Ingested(Message):
    def __init__(self, report: AddedReport, unmatched: list[UnmatchedTrack]) -> None:
        super().__init__()
        self.report = report
        self.unmatched = unmatched


class Previewed(Message):
    def __init__(self, url: str, tracks: list[Track], unmatched: list[UnmatchedTrack]) -> None:
        super().__init__()
        self.url = url
        self.tracks = tracks
        self.unmatched = unmatched


class SettingsScreen(ModalScreen[tuple[str, str, bool] | None]):
    CSS = """
#settings-grid {
    align: center middle;
}

#settings-box {
    width: 64;
    height: auto;
    padding: 1 2;
    border: round $accent;
}

.settings-title {
    text-style: bold;
    margin-bottom: 1;
}

#settings-box Input {
    margin-bottom: 1;
}

.lyrics-row {
    height: auto;
    margin-bottom: 1;
}

.lyrics-label {
    margin-left: 1;
}

.settings-buttons {
    height: auto;
}

.settings-buttons Button {
    margin-right: 1;
}
"""
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    def compose(self) -> ComposeResult:
        yield Container(
            Vertical(
                Static("Settings", classes="settings-title"),
                Label("Directory template"),
                SafeInput(value=self._settings.dir_template, id="dir-template"),
                Label("File template"),
                SafeInput(value=self._settings.file_template, id="file-template"),
                Horizontal(
                    Switch(value=self._settings.lyrics, id="lyrics"),
                    Label("save .lrc lyrics", classes="lyrics-label"),
                    classes="lyrics-row",
                ),
                Horizontal(
                    Button("Save", variant="primary", id="save"),
                    Button("Cancel", id="cancel"),
                    classes="settings-buttons",
                ),
                id="settings-box",
            ),
            id="settings-grid",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.dismiss(
                (
                    self.query_one("#dir-template", Input).value.strip(),
                    self.query_one("#file-template", Input).value.strip(),
                    self.query_one("#lyrics", Switch).value,
                )
            )
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class MainScreen(Screen):
    BINDINGS = [
        ("ctrl+c", "app.quit", "Quit"),
        ("ctrl+q", "app.quit", "Quit"),
        ("s", "toggle_pause", "Pause/Resume"),
        ("r", "retry_failed", "Retry failed"),
        ("slash", "focus_search", "Search"),
        ("comma", "settings", "Settings"),
        ("space", "play_toggle", "Play/Pause"),
        ("d", "download_row", "Download highlighted"),
        ("h", "hold_row", "Hold/Resume track"),
        ("enter", "row_action", "Play or Hold"),
    ]
    CSS = """
#top {
    height: auto;
    padding: 0 1;
}

#url {
    width: 1fr;
}

#quality {
    width: 30;
}

#tabs {
    height: 1fr;
}

#search {
    margin: 0 1;
}

#results {
    height: 1fr;
}

#status {
    height: 3;
    padding: 0 1;
}

#now {
    width: 1fr;
    color: $text-muted;
    padding-right: 1;
}

#progress {
    width: 36;
}

#counts {
    width: auto;
    color: $text-muted;
    padding-left: 1;
}

#player {
    height: 3;
    padding: 0 1;
}

#now-playing {
    width: 1fr;
    color: $success;
    padding-right: 1;
}

#player-time {
    width: 14;
    color: $text-muted;
    align: center middle;
}

#seek {
    width: 26;
    color: $text-muted;
    align: center middle;
}

#spectrum {
    width: 26;
    color: $success;
    align: center middle;
}

#player-backend {
    width: auto;
    color: $text-muted;
    padding-left: 1;
}

#searching {
    display: none;
    height: 3;
}
"""

    def __init__(
        self,
        qobuz,
        matcher,
        base_source: ByteSource,
        db_path: Path,
        root: Path,
        naming: Naming,
        lyrics,  # LyricsSource | None
        quality: Quality,
        settings: Settings,
        player=None,
    ) -> None:
        super().__init__()
        self._qobuz = qobuz
        self._matcher = matcher
        self._base_source = base_source
        self._db_path = db_path
        self._root = root
        self._naming = naming
        self._lyrics = lyrics
        self._preferred_quality = quality
        self._settings = settings
        self._searching = 0
        self._preview_cache: list[Track] = []
        self._current_id: str | None = None
        self._results: dict[str, Track | Album] = {}
        self._cols: tuple = ()
        self._queue_table: DataTable | None = None
        self._holds = Holds(db_path)
        self._player = player if player is not None else detect_player()
        self._spectrum = Spectrum()
        self._highlight_track: Track | None = None
        self._playing_id: str | None = None
        self._state: dict[str, str] = {}
        self._row_ids: set[str] = set()
        self._worker: DownloadWorker | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top"):
            yield SafeInput(
                placeholder="Paste a Qobuz or Spotify URL — Find previews it, Download queues it",
                id="url",
            )
            yield Button("Find", id="find")
            yield Button("Download", id="add", variant="primary")
            yield Select(
                _QUALITY_OPTIONS,
                value=self._preferred_quality,
                allow_blank=False,
                id="quality",
            )
            yield Button("Pause", id="pause")
            yield Button("Retry failed", id="retry")
            yield Button("Settings", id="settings")
            yield Button("Log out", id="logout")
        with TabbedContent(id="tabs"):
            with TabPane("Queue", id="queue-pane"):
                yield DataTable(id="queue", cursor_type="row")
            with TabPane("Search", id="search-pane"):
                with Vertical():
                    yield SafeInput(placeholder="Search tracks and albums on Qobuz", id="search")
                    yield LoadingIndicator(id="searching")
                    yield DataTable(id="results", cursor_type="row")
            with TabPane("Log", id="log-pane"):
                yield RichLog(id="log", markup=True, max_lines=2000)
        with Horizontal(id="player"):
            yield Button("▶", id="play-toggle", variant="success")
            yield Static("", id="now-playing")
            yield Static("", id="player-time")
            yield Static("", id="seek")
            yield Static("", id="spectrum")
            yield Button("Vol -", id="vol-down")
            yield Button("Vol +", id="vol-up")
            yield Static("", id="player-backend")
        with Horizontal(id="status"):
            yield Static("", id="now")
            yield ProgressBar(show_eta=False, id="progress")
            yield Static("", id="counts")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#queue", DataTable)
        table.zebra_stripes = True
        self._cols = table.add_columns("Status", "Artist", "Title", "Album", "Progress", "Note")
        self._queue_table = table
        results = self.query_one("#results", DataTable)
        results.zebra_stripes = True
        results.add_columns("Type", "Name", "Artist", "Detail")
        self._load_queue()
        self._worker = DownloadWorker(
            self.app,
            self._qobuz,
            self._base_source,
            self._db_path,
            self._naming,
            self._lyrics,
            self._preferred_quality,
            is_held=lambda track_id: track_id in self._holds.all(),
        )
        self._worker.start()
        self._update_counts()
        backend = getattr(self._player, "state", None) and self._player.state.backend
        self.query_one("#player-backend", Static).update(backend or "no player (install mpv)")
        self.log_line(f"downloads land in {self._root}")

    def shutdown(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker.join(timeout=2.0)
        self._player.close()
        self._holds.close()

    # --- queue table -------------------------------------------------------

    def _load_queue(self) -> None:
        assert self._queue_table is not None
        db = sqlite3.connect(self._db_path)
        try:
            rows = db.execute(
                "SELECT id, title, artist, album, status, reason FROM tracks ORDER BY rowid"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        finally:
            db.close()
        held = self._holds.all()
        for track_id, title, artist, album, status, reason in rows:
            state = status.lower()
            if state == "pending" and track_id in held:
                state = "held"
            self._row_ids.add(track_id)
            self._queue_table.add_row(
                _GLYPHS.get(state, "?"), artist, title, album, "", reason or "", key=track_id
            )
            self._state[track_id] = state

    def _upsert_row(self, track: Track, state: str, note: str = "") -> None:
        assert self._queue_table is not None
        self._state[track.id] = state
        values = (_GLYPHS.get(state, "?"), track.artist, track.title, track.album, "", note)
        if track.id in self._row_ids:
            for column_key, value in zip(self._cols, values):
                self._queue_table.update_cell(track.id, column_key, value)
        else:
            self._row_ids.add(track.id)
            self._queue_table.add_row(*values, key=track.id)

    def _set_cell(self, track_id: str, index: int, value: str) -> None:
        assert self._queue_table is not None
        try:
            self._queue_table.update_cell(track_id, self._cols[index], value)
        except Exception:
            pass  # row went away between events

    def _alive(self) -> bool:
        """False once the screen is being torn down; late worker events arrive then."""
        return self.is_mounted

    def _widget(self, selector: str, expect_type):
        """query_one that tolerates teardown: returns None once widgets are gone."""
        if not self._alive():
            return None
        try:
            return self.query_one(selector, expect_type)
        except NoMatches:
            return None

    def _update_counts(self) -> None:
        counts = self._widget("#counts", Static)
        if counts is None:
            return
        done = sum(1 for state in self._state.values() if state == "complete")
        failed = sum(1 for state in self._state.values() if state == "failed")
        pending = len(self._state) - done - failed
        counts.update(f"queued {pending}  ·  done {done}  ·  failed {failed}")

    @staticmethod
    def _spec(outcome) -> str:
        assert outcome is not None
        if outcome.sampling_rate:
            spec = f"{outcome.bit_depth}/{outcome.sampling_rate:g} kHz"
        else:
            spec = outcome.quality.name.lower()
        return spec + (" · fell back" if outcome.fell_back else "")

    def log_line(self, text: str, error: bool = False) -> None:
        log = self._widget("#log", RichLog)
        if log is None:
            return
        log.write(f"[red]{text}[/red]" if error else text)

    # --- worker events -----------------------------------------------------

    def handle_event(self, event: WorkerEvent) -> None:
        kind = event.kind
        track = event.track
        if kind == "current":
            assert track is not None
            self._current_id = track.id
            self._upsert_row(track, "downloading")
            self._set_paused(False)
            now = self._widget("#now", Static)
            if now is not None:
                now.update(f"{track.artist} — {track.title}")
            progress = self._widget("#progress", ProgressBar)
            if progress is not None:
                progress.update(progress=0, total=None)
        elif kind == "progress":
            assert track is not None
            if track.id == self._current_id:
                total = event.total
                if total:
                    progress = self._widget("#progress", ProgressBar)
                    if progress is not None:
                        progress.update(total=total, progress=event.done)
                    self._set_cell(track.id, 4, f"{event.done / total:.0%}")
                else:
                    self._set_cell(track.id, 4, _human_bytes(event.done))
        elif kind == "complete":
            assert track is not None and event.outcome is not None
            spec = self._spec(event.outcome)
            self._upsert_row(track, "complete", note=spec)
            self._set_cell(track.id, 4, "")
            self.log_line(f"done: {track.artist} — {track.title} ({spec})")
        elif kind == "failed":
            assert track is not None
            self._upsert_row(track, "failed", note=event.text)
            self.log_line(f"failed: {track.artist} — {track.title} ({event.text})", error=True)
        elif kind == "paused":
            self._set_paused(True)
            if self._current_id:
                self._state[self._current_id] = "paused"
                self._set_cell(self._current_id, 0, _GLYPHS["paused"])
            self.log_line("paused — the current download will resume where it stopped")
        elif kind == "idle":
            now = self._widget("#now", Static)
            if now is not None:
                now.update("idle")
            self._set_paused(False)
        elif kind == "abort":
            now = self._widget("#now", Static)
            if now is not None:
                now.update(f"aborted after 5 consecutive failures — {event.text}")
            self.notify(
                "Download aborted after 5 consecutive failures — press s to resume",
                severity="error",
            )
            self.log_line("aborted after 5 consecutive failures", error=True)
        if kind in ("complete", "failed"):
            self._update_counts()

    def _set_paused(self, paused: bool) -> None:
        button = self._widget("#pause", Button)
        if button is None:
            return
        button.label = "Resume" if paused else "Pause"

    # --- actions -----------------------------------------------------------

    def action_toggle_pause(self) -> None:
        if self._worker is None:
            return
        if self._worker.is_paused():
            self._worker.resume()
            self._set_paused(False)
            self.log_line("resumed")
        else:
            self._worker.pause()
            self._set_paused(True)

    def action_retry_failed(self) -> None:
        """Retry failed AND stuck tracks (downloading/paused rows that never settled)."""
        queue = SqliteQueue(self._db_path)
        try:
            requeued = queue.requeue_failed()
        finally:
            queue.close()
        stuck = [
            tid
            for tid, state in self._state.items()
            if state in ("downloading", "paused")
        ]
        for track_id in stuck:
            # clear any orphaned .part bookkeeping by flipping state back
            self._state[track_id] = "pending"
            self._set_cell(track_id, 0, _GLYPHS["pending"])
            self._set_cell(track_id, 4, "")
            self._set_cell(track_id, 5, "")
        total = requeued + len(stuck)
        if not total:
            self.notify("nothing to retry — no failed or stuck tracks")
            return
        self._update_counts()
        self.log_line(f"re-queued {total} track(s) for retry")
        self.notify(f"retrying {total} track(s)")
        if self._worker is not None:
            self._worker.kick()

    def action_hold_resume_row(self) -> None:
        """Enter on a queue row: play completed track, or hold/resume it."""
        assert self._queue_table is not None
        row_key = self._queue_table.cursor_row_key
        if row_key is None or row_key.value is None:
            return
        track_id = row_key.value
        state = self._state.get(track_id, "pending")
        if state == "complete":
            self._play_track(track_id)
        elif state == "held":
            self._resume_track(track_id)
        else:
            self._hold_track(track_id)

    def _remember_highlight(self, table_id: str) -> None:
        """Snapshot the highlighted row so Play works after focus moves."""
        if table_id == "results":
            table = self._widget("#results", DataTable)
        else:
            table = self._widget("#queue", DataTable)
        if table is None or table.cursor_row_key is None:
            return
        key = table.cursor_row_key.value or ""
        item = self._results.get(key)
        if isinstance(item, Track):
            self._highlight_track = item

    def _track_by_id(self, track_id: str) -> Track | None:
        db = sqlite3.connect(self._db_path)
        try:
            row = db.execute(
                "SELECT id, title, artist, album, track_number, duration_seconds,"
                " collection FROM tracks WHERE id = ?",
                (track_id,),
            ).fetchone()
        finally:
            db.close()
        if row is None:
            return None
        return Track(
            id=row[0], title=row[1], artist=row[2], album=row[3],
            track_number=row[4], duration_seconds=row[5],
            collection=row[6] if len(row) > 6 else None,
        )

    def _local_file_for(self, track: Track) -> Path | None:
        from qobuz_downloader.domain import Quality as Q
        for quality, ext in ((Q.HIRES_192, ".flac"), (Q.HIRES_96, ".flac"), (Q.CD, ".flac")):
            candidate = self._naming.path_for(track, extension=ext)
            if candidate.exists():
                return candidate
        return None

    def _stream_url_for(self, track: Track) -> str | None:
        try:
            stream = self._qobuz.stream(track, Quality.CD)
        except (ValueError, RuntimeError, httpx.HTTPError, spotapi.ParentException) as error:
            return None
        return stream.url

    def _start_playback(self, source: str | Path, track: Track) -> None:
        self._player.play(source, f"♪ {track.artist} — {track.title}")
        self._playing_id = track.id
        self._spectrum.start(str(source))
        toggle = self._widget("#play-toggle", Button)
        if toggle is not None:
            toggle.label = "⏸"
        self.log_line(f"playing: {track.artist} — {track.title}")

    def _play_track(self, track_id: str) -> None:
        track = self._track_by_id(track_id)
        if track is None:
            return
        self._play_track_obj(track)

    def _play_track_obj(self, track: Track) -> None:
        """Play a downloaded file when present; otherwise stream without downloading."""
        local = self._local_file_for(track)
        if local is not None:
            self._start_playback(local, track)
            return
        url = self._stream_url_for(track)
        if url is None:
            self.notify(
                "not downloaded yet and streaming unavailable — download it first",
                severity="warning",
            )
            return
        self._start_playback(url, track)
        self.notify(f"streaming (not downloaded): {track.artist} — {track.title}")

    def _hold_track(self, track_id: str) -> None:
        self._holds.add(track_id)
        track = self._track_by_id(track_id)
        if track is not None:
            self._upsert_row(track, "held")
        self.notify(f"held: {track.title if track else track_id}")
        if self._current_id == track_id and self._worker is not None and not self._worker.is_paused():
            # cancel the in-flight attempt; it will be skipped on the next pick
            self._worker.pause()
            self._worker.resume()

    def _resume_track(self, track_id: str) -> None:
        self._holds.remove(track_id)
        track = self._track_by_id(track_id)
        if track is not None:
            self._upsert_row(track, "pending")
        self.notify(f"resumed: {track.title if track else track_id}")
        if self._worker is not None:
            self._worker.kick()


    def _refresh_player(self) -> None:
        state = self._player.poll()
        toggle = self._widget("#play-toggle", Button)
        now_playing = self._widget("#now-playing", Static)
        player_time = self._widget("#player-time", Static)
        seek = self._widget("#seek", Static)
        spectrum_widget = self._widget("#spectrum", Static)
        if toggle is not None:
            toggle.label = "⏸" if state.loaded and not state.paused else "▶"
        if now_playing is not None:
            now_playing.update(state.label)
        if player_time is not None and state.loaded:
            pos = int(state.position)
            dur = int(state.duration) if state.duration else None
            if dur:
                player_time.update(f"{pos // 60}:{pos % 60:02d} / {dur // 60}:{dur % 60:02d}")
            else:
                player_time.update(f"{pos // 60}:{pos % 60:02d}")
        if seek is not None:
            if state.loaded and state.duration:
                frac = max(0.0, min(1.0, state.position / state.duration))
                filled = int(frac * _SEEK_WIDTH)
                bar = "━" * filled + "╸" + "━" * (_SEEK_WIDTH - filled - 1) if filled < _SEEK_WIDTH else "━" * _SEEK_WIDTH
                seek.update(f"[cyan]{bar}[/cyan]")
            else:
                seek.update("")
        if spectrum_widget is not None:
            if state.loaded and not state.paused:
                spectrum_widget.update(f"[green]{self._spectrum.bars(_SPECTRUM_WIDTH)}[/green]")
            elif not state.loaded:
                spectrum_widget.update("")
    @on(DataTable.RowSelected, "#queue")
    def queue_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_hold_resume_row()

    def action_focus_search(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "search-pane"
        self.query_one("#search", Input).focus()

    def action_settings(self) -> None:
        self.app.push_screen(SettingsScreen(self._settings), callback=self._apply_settings)

    def _apply_settings(self, value: tuple[str, str, bool] | None) -> None:
        if value is None or not self._alive():
            return
        dir_template, file_template, lyrics_on = value
        self._settings.dir_template = dir_template
        self._settings.file_template = file_template
        self._settings.lyrics = lyrics_on
        save_settings(self._settings)
        if self._worker is not None:
            self._worker.reconfigure(
                naming=Naming(dir_template, file_template, root=self._root),
                lyrics=LrcLib() if lyrics_on else None,
            )
        self.log_line("settings saved")

    def action_play_toggle(self) -> None:
        """space/▶: pause or resume what's playing; play the highlighted track otherwise."""
        state = self._player.poll()
        if state.loaded:
            self._player.toggle()
            return
        track = self._highlight_track
        if track is None:
            self.notify(
                "nothing playing — highlight a track (Find a URL or search) and press space"
            )
            return
        self._play_track_obj(track)

    def action_hold_row(self) -> None:
        assert self._queue_table is not None
        row_key = self._queue_table.cursor_row_key
        if row_key is None or row_key.value is None:
            return
        track_id = row_key.value
        if self._state.get(track_id) == "held":
            self._resume_track(track_id)
        else:
            self._hold_track(track_id)

    def action_download_row(self) -> None:
        """d: queue the highlighted preview/search track for download."""
        if self._highlight_track is None:
            self.notify("no track highlighted")
            return
        self.ingest([self._highlight_track], [])

    def on_data_table_cell_highlighted(
        self, event: DataTable.CellHighlighted
    ) -> None:
        if not self._alive():
            return
        key = event.row_key.value or ""
        self._remember_highlight("results" if key.startswith(("preview:", "track:", "album:")) else "queue")

    def action_row_action(self) -> None:
        self.action_hold_resume_row()

    # --- buttons and inputs -------------------------------------------------

    @on(Button.Pressed, "#add")
    def add_pressed(self) -> None:
        self.submit_url()

    @on(Button.Pressed, "#pause")
    def pause_pressed(self) -> None:
        self.action_toggle_pause()

    @on(Button.Pressed, "#retry")
    def retry_pressed(self) -> None:
        self.action_retry_failed()

    @on(Button.Pressed, "#settings")
    def settings_pressed(self) -> None:
        self.action_settings()

    @on(Button.Pressed, "#logout")
    def logout_pressed(self) -> None:
        self.app.logout()

    @on(Button.Pressed, "#play-toggle")
    def play_toggle_pressed(self) -> None:
        # Button click steals focus from the table; restore it so the
        # highlight survives and space keeps working.
        self.action_play_toggle()
        table = self._widget("#results", DataTable)
        if table is None:
            table = self._widget("#queue", DataTable)
        if table is not None:
            table.focus()

    @on(Button.Pressed, "#vol-down")
    def vol_down_pressed(self) -> None:
        self._player.volume(-5)

    @on(Button.Pressed, "#vol-up")
    def vol_up_pressed(self) -> None:
        self._player.volume(5)

    @on(Button.Pressed, "#find")
    def find_pressed(self) -> None:
        self.preview_url()

    @on(Input.Submitted, "#url")
    def url_submitted(self, event: Input.Submitted) -> None:
        self.submit_url(event.input)

    def preview_url(self, input_widget: Input | None = None) -> None:
        widget = input_widget or self.query_one("#url", Input)
        url = widget.value.strip()
        if not url:
            return
        widget.value = ""
        spinner = self.query_one("#searching", LoadingIndicator)
        spinner.display = True
        self.query_one("#tabs", TabbedContent).active = "search-pane"
        self.preview_matches(url)

    def submit_url(self, input_widget: Input | None = None) -> None:
        widget = input_widget or self.query_one("#url", Input)
        url = widget.value.strip()
        if not url:
            return
        widget.value = ""
        self.collect_url(url)

    @work(thread=True, group="collect", exclusive=True)
    def collect_url(self, url: str) -> None:
        try:
            tracks, unmatched = _collect(self._qobuz, self._matcher, url)
        except (ValueError, RuntimeError, httpx.HTTPError, spotapi.ParentException) as error:
            self.post_message(Notice("error", f"could not queue {url}: {error}"))
            return
        self.ingest(tracks, unmatched)

    @work(thread=True, group="preview", exclusive=True)
    def preview_matches(self, url: str) -> None:
        try:
            tracks, unmatched = _collect(self._qobuz, self._matcher, url)
        except (ValueError, RuntimeError, httpx.HTTPError, spotapi.ParentException) as error:
            self.post_message(Previewed(url, [], [UnmatchedTrack(title=url, artist="", reason=str(error) or type(error).__name__)]))
            return
        self.post_message(Previewed(url, tracks, unmatched))

    @on(Previewed)
    def previewed(self, event: Previewed) -> None:
        if not self._alive():
            return
        self.query_one("#searching", LoadingIndicator).display = False
        table = self.query_one("#results", DataTable)
        table.clear()
        self._results.clear()
        self._preview_cache: list[Track] = []
        for track in event.tracks:
            key = f"preview:{track.id}"
            self._results[key] = track
            self._preview_cache.append(track)
            table.add_row(
                "Match" if "spotify" in event.url.lower() else "Track",
                track.title,
                track.artist,
                track.album,
                key=key,
            )
        for miss in event.unmatched:
            who = f"{miss.artist} — {miss.title}" if miss.artist else miss.title
            self.log_line(f"unmatched: {who} ({miss.reason})", error=True)
        count = len(event.tracks)
        if count:
            first = event.tracks[0]
            self.notify(
                f"found {count} track(s) from {event.url.split('/')[-1][:24]}"
                f" — Enter plays, d downloads"
            )
        else:
            self.notify("nothing found for that URL", severity="warning")
        self.query_one("#tabs", TabbedContent).active = "search-pane"

    @on(DataTable.RowSelected, "#results")
    def result_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        if key is None:
            return
        if key.startswith("preview:"):
            # Enter on a found track: play it without downloading.
            item = self._results.get(key)
            if isinstance(item, Track):
                self._highlight_track = item
                self._play_track_obj(item)
            return
        if key not in self._results:
            return
        self.expand_result(key)

    def ingest(self, tracks: list[Track], unmatched: list[UnmatchedTrack]) -> None:
        """Runs in a worker thread: writes through its own queue connection."""
        queue = SqliteQueue(self._db_path)
        try:
            report = queue.add(tracks)
        finally:
            queue.close()
        self.post_message(Ingested(report, unmatched))

    @on(Ingested)
    def ingested(self, event: Ingested) -> None:
        if not self._alive():
            return
        for track in event.report.added:
            self._upsert_row(track, "pending")
        for track in event.report.skipped:
            self.log_line(f"skipped (already queued): {track.artist} — {track.title}")
        for miss in event.unmatched:
            who = f"{miss.artist} — {miss.title}" if miss.artist else miss.title
            self.log_line(f"unmatched: {who} ({miss.reason})", error=True)
            self.notify(f"unmatched: {who}", severity="warning")
        if event.report.added:
            count = len(event.report.added)
            first = event.report.added[0]
            self.log_line(f"queued {count} track(s)")
            if count == 1:
                self.notify(f"queued: {first.artist} — {first.title}")
            else:
                self.notify(
                    f"queued {count} track(s), starting with {first.artist} — {first.title}"
                )
            self._update_counts()
            if self._worker is not None:
                self._worker.kick()

    # --- search --------------------------------------------------------------

    @on(Input.Submitted, "#search")
    def search_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if query:
            spinner = self.query_one("#searching", LoadingIndicator)
            spinner.display = True
            self.query_one("#tabs", TabbedContent).active = "search-pane"
            self.run_search(query)

    @work(thread=True, group="search", exclusive=True)
    def run_search(self, query: str) -> None:
        try:
            tracks = self._qobuz.search_tracks(query, 50)
            albums = self._qobuz.search_albums(query, 25)
        except (ValueError, RuntimeError, httpx.HTTPError, spotapi.ParentException) as error:
            self.post_message(Notice("error", f"search failed: {error}"))
            return
        self.post_message(SearchResults(tracks, albums))

    @on(SearchResults)
    def search_results(self, event: SearchResults) -> None:
        if not self._alive():
            return
        self.query_one("#searching", LoadingIndicator).display = False
        table = self.query_one("#results", DataTable)
        table.clear()
        self._results.clear()
        for track in event.tracks:
            key = f"track:{track.id}"
            self._results[key] = track
            table.add_row("Track", track.title, track.artist, track.album, key=key)
        for album in event.albums:
            key = f"album:{album.id}"
            self._results[key] = album
            detail = f"{album.tracks_count} tracks" if album.tracks_count is not None else "album"
            table.add_row("Album", album.title, album.artist, detail, key=key)
        if not event.tracks and not event.albums:
            self.notify("no results")
        else:
            self.log_line(
                f"search: {len(event.tracks)} track(s), {len(event.albums)} album(s)"
            )
        self.query_one("#tabs", TabbedContent).active = "search-pane"

    @work(thread=True, group="expand", exclusive=True)
    def expand_result(self, key: str) -> None:
        item = self._results.get(key)
        if isinstance(item, Track):
            self.ingest([item], [])
        elif isinstance(item, Album):
            try:
                tracks = self._qobuz.tracks(item)
            except (ValueError, RuntimeError, httpx.HTTPError, spotapi.ParentException) as error:
                self.post_message(Notice("error", f"could not fetch album: {error}"))
                return
            self.ingest(tracks, [])

    # --- quality --------------------------------------------------------------

    @on(Notice)
    def notice(self, event: Notice) -> None:
        if not self._alive():
            return
        searching = self._widget("#searching", LoadingIndicator)
        if searching is not None:
            searching.display = False
        self.log_line(event.text, error=event.level == "error")
        if event.level == "error":
            self.notify(event.text, severity="error")

    @on(Select.Changed, "#quality")
    def quality_changed(self, event: Select.Changed) -> None:
        quality = event.value
        if not isinstance(quality, Quality):
            return
        self._preferred_quality = quality
        self._settings.quality = next(
            key for key, value in _QUALITY_KEYS.items() if value == quality
        )
        save_settings(self._settings)
        if self._worker is not None:
            self._worker.set_quality(quality)
        self.log_line(f"preferred quality: {self._settings.quality}")


class QuaverApp(App):
    TITLE = "Quaver"
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+q", "quit", "Quit"),
    ]
    CSS = """
Screen {
    layout: vertical;
}
"""

    def action_help_quit(self) -> None:
        """Ctrl+C: Textual's default only shows a 'use ctrl+q' toast — actually quit."""
        self.action_quit()

    def __init__(
        self,
        settings: Settings | None = None,
        root: str | Path | None = None,
        *,
        client=None,
        db_path: Path | None = None,
        base_source: ByteSource | None = None,
        lyrics=_UNSET,
        matcher=None,
        cli_creds: dict | None = None,
        player=None,
    ) -> None:
        super().__init__()
        self._settings = settings if settings is not None else load_settings()
        self._player_override = player
        self._root_arg = root
        self._client_override = client
        self._db_override = Path(db_path) if db_path is not None else None
        self._source_override = base_source
        self._lyrics_override = lyrics
        self._matcher_override = matcher
        self._cli_creds = cli_creds
        self._main: MainScreen | None = None
        self._root: Path | None = None
        self._login_serial = 0
        self._exiting = threading.Event()
        self._debug_keys = os.environ.get("QUAVER_DEBUG_KEYS") == "1"

    def next_login_serial(self) -> int:
        self._login_serial += 1
        return self._login_serial

    async def on_event(self, event: events.Event) -> None:
        if getattr(self, "_debug_keys", False) and isinstance(
            event, (events.Key, events.Paste)
        ):
            try:
                directory = config_dir()
                directory.mkdir(parents=True, exist_ok=True)
                with open(directory / "keys.log", "a") as handle:
                    if isinstance(event, events.Key):
                        handle.write(
                            f"key={event.key!r} char={event.character!r}\n"
                        )
                    else:
                        handle.write(
                            f"paste len={len(event.text)}"
                            f" text={event.text[:60]!r}\n"
                        )
            except OSError:
                pass
        await super().on_event(event)

    def on_mount(self) -> None:
        self.set_interval(0.5, self._tick)
        normalize_proxy_env()
        signal.signal(signal.SIGTERM, self._on_sigterm)
        if self._client_override is not None:
            self.enter_main(self._client_override)
            return
        if self._cli_creds is not None:
            if self._cli_creds.get("mode") == "token":
                # from_token is pure client-side: skip the worker round-trip so the
                # first painted frame is already the main screen (no login race).
                from .login import authenticate

                self.enter_main(authenticate(**self._cli_creds))
                return
            # Email flags hit the network; run through the worker thread.
            self.auto_login(dict(self._cli_creds))
            return
        creds = credentials_from_env(self._settings)
        if creds is None:
            self.push_screen(LoginScreen(self._settings))
            return
        self.auto_login(creds)

    def _tick(self) -> None:
        if self._main is not None:
            self._main._refresh_player()

    @work(thread=True, group="login")
    def auto_login(self, creds: dict) -> None:
        """Remembered credentials: retry transient failures before giving up."""
        import time as _time

        from .login import authenticate

        serial = self.next_login_serial()
        attempts = 3
        last_error: Exception | None = None
        for attempt in range(attempts):
            if self._exiting.is_set():
                return
            try:
                client = authenticate(**creds)
                self.post_message(LoginSucceeded(client, serial=serial))
                return
            except ValueError as error:
                # bad credentials: retrying will not help
                self.post_message(LoginFailed(str(error) or type(error).__name__))
                return
            except (RuntimeError, httpx.HTTPError) as error:
                last_error = error
                if attempt < attempts - 1:
                    if self._exiting.wait(1.2):
                        return
        self.post_message(
            LoginFailed(str(last_error) or type(last_error).__name__ if last_error else "login failed")
        )

    @on(LoginFailed)
    def login_failed(self, event: LoginFailed) -> None:
        if self._main is None and not isinstance(self.screen, LoginScreen):
            self.push_screen(LoginScreen(self._settings))
            self.notify(f"login failed: {event.reason}", severity="error")

    @on(LoginSucceeded)
    def login_succeeded(self, event: LoginSucceeded) -> None:
        if self._main is not None:
            return
        if event.serial is not None and event.serial != self._login_serial:
            return  # stale: a logout happened while this login was in flight
        if isinstance(self.screen, LoginScreen):
            self.pop_screen()
        self.enter_main(event.client)
        self.call_later(self._ensure_main_visible)

    def _ensure_main_visible(self) -> None:
        """Late-arriving successful login must still replace the default screen."""
        if self._main is not None and self.screen is not self._main:
            self.switch_screen(self._main)

    def logout(self) -> None:
        """Drop the session, wipe remembered credentials, return to the login screen."""
        self.next_login_serial()  # invalidate any in-flight login
        if self._main is not None:
            self._main.shutdown()
            self._main = None
        self._settings.remember = False
        self._settings.email = ""
        self._settings.password = ""
        self._settings.token = ""
        self._settings.app_id = ""
        self._settings.app_secret = ""
        save_settings(self._settings)
        # Overlay the login screen without unmounting Main: unmounting races
        # Textual's delayed Header/Select refreshes during shutdown. The hidden
        # main screen is replaced by a fresh one after the next successful login.
        self.push_screen(LoginScreen(self._settings))
        self.notify("logged out — remembered credentials cleared")

    def enter_main(self, client) -> None:
        root = Path(self._root_arg or self._settings.download_dir).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        self._root = root
        db_path = self._db_override or root / ".queue.sqlite3"
        matcher = (
            self._matcher_override
            if self._matcher_override is not None
            else make_matcher(client)
        )
        source = (
            self._source_override
            if self._source_override is not None
            else HttpByteSource()
        )
        lyrics = (
            self._lyrics_override
            if self._lyrics_override is not _UNSET
            else (LrcLib() if self._settings.lyrics else None)
        )
        quality = _QUALITY_KEYS.get(self._settings.quality, Quality.HIRES_192)
        naming = Naming(self._settings.dir_template, self._settings.file_template, root=root)
        self._main = MainScreen(
            client, matcher, source, db_path, root, naming, lyrics, quality,
            self._settings, player=self._player_override,
        )
        self.push_screen(self._main)

    async def action_quit(self) -> None:
        self._cleanup()
        self.exit()

    def _cleanup(self) -> None:
        self._exiting.set()
        if self._main is not None:
            self._main.shutdown()
            self._main = None

    def _on_sigterm(self, signum, frame) -> None:
        self.exit()

    def on_unmount(self) -> None:
        """Safety net for exit paths that bypass action_quit (SIGINT, crash)."""
        try:
            self._cleanup()
        except Exception:
            pass

    @on(WorkerEventMessage)
    def worker_event(self, event: WorkerEventMessage) -> None:
        if self._main is not None:
            self._main.handle_event(event.event)
