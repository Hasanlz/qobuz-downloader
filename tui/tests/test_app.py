"""End-to-end tests for the TUI driven through Textual's Pilot with fakes."""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import struct
import time
from pathlib import Path
from textual.widgets import DataTable, Input, Label, RadioButton, Select

from qobuz_downloader.domain import (
    Album,
    Matched,
    Quality,
    Stream,
    Track,
    UnmatchedTrack,
)
from qobuz_downloader.engine._source import ByteResponse, ByteSource
from qobuz_downloader.match import Matcher

from quaver.app import MainScreen, QuaverApp
from quaver.login import LoginScreen
from quaver.settings import Settings

TRACK1 = Track(id="t1", title="Song One", artist="Artist", album="Album", track_number=1)
TRACK2 = Track(id="t2", title="Song Two", artist="Artist", album="Album", track_number=2)
TRACK3 = Track(id="t3", title="Lossy Only", artist="Artist", album="Album")
TRACK4 = Track(id="t4", title="Song Four", artist="Artist", album="Album", track_number=4)


def _flac_bytes(size: int = 4096) -> bytes:
    header = b"fLaC" + bytes([0x80, 0x00, 0x00, 0x22])
    streaminfo = struct.pack(">HH", 4096, 4096) + b"\x00" * 6
    packed = (44100 << 44) | (1 << 41) | (15 << 36) | 44100
    streaminfo += packed.to_bytes(8, "big") + b"\x00" * 16
    data = header + streaminfo
    return data + b"\x00" * max(0, size - len(data))


class FakeQobuz:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.stream_calls = 0

    def item(self, url: str) -> Album:
        return Album(id="a1", title="Album", artist="Artist")

    def tracks(self, item) -> list[Track]:
        return [TRACK1, TRACK2, TRACK3]

    def qualities(self, track: Track) -> list[Quality]:
        if track.id == "t3":
            return [Quality.LOSSY]
        return [Quality.LOSSY, Quality.CD, Quality.HIRES_96, Quality.HIRES_192]

    def stream(self, track: Track, quality: Quality) -> Stream:
        self.stream_calls += 1
        return Stream(
            url=f"https://cdn.test/{track.id}/{self.stream_calls}",
            quality=quality,
            sampling_rate=44.1,
            bit_depth=16,
        )

    def search_tracks(self, query: str, limit: int) -> list[Track]:
        return [TRACK1][:limit]

    def search_albums(self, query: str, limit: int) -> list[Album]:
        return [Album(id="a1", title="Album", artist="Artist", tracks_count=3)][:limit]


class FakeSource(ByteSource):
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def stream(self, url: str, start: int) -> ByteResponse:
        data = self._payload[start:]
        return ByteResponse(
            status=206 if start else 200, length=len(data), chunks=iter([data])
        )


class FakeMatcher(Matcher):
    def match(self, url: str):
        return Matched(
            tracks=[TRACK4],
            unmatched=[UnmatchedTrack(title="Ghost Track", artist="", reason="no candidate")],
        )


def make_app(root: Path, db_path: Path) -> QuaverApp:
    settings = Settings(download_dir=str(root), lyrics=False, remember=False)
    return QuaverApp(
        settings=settings,
        client=FakeQobuz(_flac_bytes()),
        db_path=db_path,
        base_source=FakeSource(_flac_bytes()),
        lyrics=None,
        matcher=FakeMatcher(),
    )


def db_states(db_path: Path) -> dict[str, str]:
    db = sqlite3.connect(db_path)
    try:
        return {row[0]: row[1] for row in db.execute("SELECT id, status FROM tracks")}
    finally:
        db.close()


async def wait_for(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met before timeout")


def test_full_download_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv("QUAVER_CONFIG_DIR", str(tmp_path / "config"))
    root = tmp_path / "music"
    db_path = tmp_path / "queue.sqlite3"

    async def scenario():
        app = make_app(root, db_path)
        async with app.run_test(size=(130, 40)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            main = app.screen
            assert isinstance(main, MainScreen)
            assert main._queue_table is not None
            assert main._queue_table.row_count == 0

            # Queue an album URL: t1/t2 download, t3 fails (lossy only).
            url_input = main.query_one("#url", Input)
            url_input.value = "https://www.qobuz.com/us-en/album/artist/album/abc"
            url_input.focus()
            await pilot.press("enter")
            await wait_for(lambda: main._queue_table.row_count == 3)
            await wait_for(
                lambda: db_states(db_path)
                == {"t1": "COMPLETE", "t2": "COMPLETE", "t3": "FAILED"}
            )
            await wait_for(
                lambda: main._state.get("t1") == "complete"
                and main._state.get("t2") == "complete"
                and main._state.get("t3") == "failed"
            )
            assert main._state == {"t1": "complete", "t2": "complete", "t3": "failed"}

            track_file = root / "Artist" / "Album" / "01 - Song One.flac"
            assert track_file.read_bytes().startswith(b"fLaC")

            # Pause, then retry the failed track: it must sit in PENDING while paused.
            main.action_toggle_pause()
            assert main._worker is not None
            assert main._worker.is_paused()
            app.set_focus(None)
            await pilot.press("r")
            await wait_for(lambda: db_states(db_path).get("t3") == "PENDING")

            # Resume: the retried track fails again (still lossy-only).
            main.action_toggle_pause()
            await wait_for(lambda: db_states(db_path).get("t3") == "FAILED")

            # Queue a Spotify URL while paused: nothing may download.
            main.action_toggle_pause()
            assert main._worker.is_paused()
            url_input.value = "https://open.spotify.com/playlist/xyz"
            url_input.focus()
            await pilot.press("enter")
            await wait_for(lambda: main._queue_table.row_count == 4)
            await asyncio.sleep(0.7)
            assert db_states(db_path).get("t4") == "PENDING"

            # Resume: t4 completes.
            main.action_toggle_pause()
            await wait_for(lambda: db_states(db_path).get("t4") == "COMPLETE")
            assert (root / "Artist" / "Album" / "04 - Song Four.flac").exists()

            # Search returns both a track and an album row.
            search_input = main.query_one("#search", Input)
            search_input.value = "artist"
            search_input.focus()
            await pilot.press("enter")
            results = main.query_one("#results", DataTable)
            await wait_for(lambda: results.row_count == 2)

            # Selecting the track result is a no-op for the queue (already complete).
            results.focus()
            await pilot.press("enter")
            await asyncio.sleep(0.5)
            assert db_states(db_path)["t1"] == "COMPLETE"

            # Quality switch reaches the worker.
            main.query_one("#quality", Select).value = Quality.CD
            await pilot.pause()
            assert main._worker._preferred is Quality.CD

            app.exit()

    asyncio.run(scenario())


def test_login_screen_flows(tmp_path, monkeypatch):
    monkeypatch.setenv("QUAVER_CONFIG_DIR", str(tmp_path / "config"))
    for var in (
        "QOBUZ_USER_AUTH_TOKEN",
        "QOBUZ_APP_ID",
        "QOBUZ_APP_SECRET",
        "QOBUZ_EMAIL",
        "QOBUZ_PASSWORD",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(download_dir=str(tmp_path / "music"), remember=False)

    async def scenario():
        app = QuaverApp(settings=settings)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, LoginScreen)

            # RadioSet is focused at mount; Tab walks into the form.
            assert screen.focused is not None
            await pilot.press("tab")
            assert screen.focused is not None

            # Empty submission reports a local validation error, no network.
            await pilot.click("#login")
            error = screen.query_one("#error", Label)
            await wait_for(lambda: bool(str(error.render())))
            assert "email" in str(error.render())

            # Selecting Auth token immediately focuses the first token field.
            await pilot.click("#mode-token")
            await pilot.pause()
            assert screen.query_one("#mode-token", RadioButton).value
            assert screen.query_one("#token-row").display
            assert screen.focused is screen.query_one("#app-id", Input)

            # Down arrow walks the revealed token fields in order.
            await pilot.press("down")
            assert screen.focused is screen.query_one("#app-secret", Input)
            await pilot.press("down")
            assert screen.focused is screen.query_one("#token", Input)
            await pilot.press("down")
            assert screen.focused is screen.query_one("#dir", Input)
            await pilot.press("up")
            assert screen.focused is screen.query_one("#token", Input)

            app.exit()

    asyncio.run(scenario())


def test_build_cli_creds():
    from quaver.cli import build_cli_creds

    args = argparse.Namespace(
        token="tok", app_id="aid", app_secret="sec", email=None, password=None
    )
    assert build_cli_creds(args) == {
        "mode": "token",
        "app_id": "aid",
        "app_secret": "sec",
        "token": "tok",
    }
    args = argparse.Namespace(
        token=None, app_id=None, app_secret=None, email="e@x.io", password="pw"
    )
    assert build_cli_creds(args) == {
        "mode": "email",
        "email": "e@x.io",
        "password": "pw",
    }
    args = argparse.Namespace(
        token=None, app_id=None, app_secret=None, email=None, password=None
    )
    assert build_cli_creds(args) is None


def test_cli_token_flags_skip_login(tmp_path, monkeypatch):
    monkeypatch.setenv("QUAVER_CONFIG_DIR", str(tmp_path / "config"))
    for var in (
        "QOBUZ_USER_AUTH_TOKEN",
        "QOBUZ_APP_ID",
        "QOBUZ_APP_SECRET",
        "QOBUZ_EMAIL",
        "QOBUZ_PASSWORD",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(download_dir=str(tmp_path / "music"), remember=False)

    async def scenario():
        # from_token is client-side: no network, lands on the main screen.
        app = QuaverApp(
            settings=settings,
            cli_creds={
                "mode": "token",
                "app_id": "aid",
                "app_secret": "sec",
                "token": "tok",
            },
        )
        async with app.run_test(size=(130, 40)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            await pilot.pause()
            app.exit()

    asyncio.run(scenario())


def test_find_button_previews_without_queueing(tmp_path, monkeypatch):
    """Find on a URL shows matches in Search tab but must not queue anything."""
    monkeypatch.setenv("QUAVER_CONFIG_DIR", str(tmp_path / "config"))
    root = tmp_path / "music"
    db_path = tmp_path / "queue.sqlite3"
    app = make_app(root, db_path)

    async def scenario():
        async with app.run_test(size=(130, 45)) as pilot:
            await pilot.pause()
            main = app.screen
            url_input = main.query_one("#url", Input)
            url_input.value = "https://open.spotify.com/track/6R5yT5bLnjn7Mbuo74rD35"
            url_input.focus()
            await pilot.click("#find")
            results = main.query_one("#results", DataTable)
            await wait_for(lambda: results.row_count > 0)
            # nothing queued: db empty, queue table empty
            assert db_states(db_path) == {}
            assert main._queue_table.row_count == 0
            # preview rows are tagged Match
            row = results.get_row_at(0)
            assert row[0] == "Match"
            # Download button still queues
            url_input.value = "https://open.spotify.com/track/6R5yT5bLnjn7Mbuo74rD35"
            url_input.focus()
            await pilot.click("#add")
            await wait_for(lambda: main._queue_table.row_count == 1)
            await wait_for(lambda: db_states(db_path).get("t4") is not None)
            app.exit()

    asyncio.run(scenario())
