"""Feature tests: per-track hold/resume, retry-stuck, player, search spinner."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

"""Feature verification v2: deterministic hold race + spinner with slow search."""
import asyncio, os, sys, tempfile, time
from pathlib import Path
from quaver.app import QuaverApp
from quaver.settings import Settings
from quaver.player import FfplayPlayer
from textual.widgets import DataTable, Input, LoadingIndicator
import test_app as T

class SlowSearchQobuz(T.FakeQobuz):
    def search_tracks(self, query, limit):
        time.sleep(0.8)
        return super().search_tracks(query, limit)
    def search_albums(self, query, limit):
        time.sleep(0.8)
        return super().search_albums(query, limit)

fails: list[str] = []
def check(n, c, d=""):
    print(("PASS: " if c else "FAIL: ") + n + ("" if c else f" — {d[-200:]}"))
    if not c: fails.append(n)

async def scenario(tmp_path):
    root = tmp_path / "m"; db = tmp_path / "q.sqlite3"
    s = Settings(download_dir=str(root), lyrics=False, remember=False)
    app = QuaverApp(settings=s, client=SlowSearchQobuz(T._flac_bytes()), db_path=db,
                   base_source=T.FakeSource(T._flac_bytes()), lyrics=None, matcher=T.FakeMatcher())
    async with app.run_test(size=(130, 45)) as pilot:
        await pilot.pause()
        m = app.screen

        # queue the album first so t1 exists for the play test
        url = m.query_one("#url", Input)
        url.value = "https://www.qobuz.com/x/y/z"; url.focus()
        await pilot.press("enter")
        for _ in range(200):
            await pilot.pause(0.05)
            if T.db_states(db).get("t3") == "FAILED": break

        # --- hold race: pause worker, queue t4, hold it, resume worker ---
        m.action_toggle_pause()  # pause worker
        url = m.query_one("#url", Input)
        url.value = "https://open.spotify.com/p/x"; url.focus()
        await pilot.press("enter")
        for _ in range(100):
            await pilot.pause(0.05)
            if "t4" in m._state: break
        check("t4 queued while paused", T.db_states(db).get("t4") == "PENDING", str(T.db_states(db)))
        m._hold_track("t4")
        await pilot.pause(0.3)
        check("t4 held", m._state.get("t4") == "held", str(m._state))
        m.action_toggle_pause()  # resume worker; t4 must be skipped
        await asyncio.sleep(1.2)
        check("held t4 skipped by worker", T.db_states(db).get("t4") == "PENDING", str(T.db_states(db)))
        now = m.query_one("#now")

        m._resume_track("t4")
        for _ in range(100):
            await pilot.pause(0.05)
            if T.db_states(db).get("t4") == "COMPLETE": break
        check("resume downloads t4", T.db_states(db).get("t4") == "COMPLETE", str(T.db_states(db)))

        # --- spinner with slow search ---
        si = m.query_one("#search", Input)
        si.value = "artist"; si.focus()
        spinner = m.query_one("#searching", LoadingIndicator)
        await pilot.press("enter")
        await pilot.pause(0.1)
        shown = spinner.display
        for _ in range(200):
            await pilot.pause(0.05)
            if not spinner.display: break
        check("spinner shown then hidden", shown and not spinner.display, f"shown={shown}")

        # --- retry stuck (crash leftover in downloading state) ---
        m._state["t1"] = "downloading"
        m.action_retry_failed()
        await pilot.pause(0.3)
        check("stuck retried", m._state.get("t1") == "pending", str(m._state))

        # --- play controls (regenerate a longer file so it does not autoexit) ---
        path = root / "Artist" / "Album" / "01 - Song One.flac"
        import subprocess as sp
        sp.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                "sine=frequency=440:duration=30", str(path)], check=True)  # real 30s audio
        m._play_track("t1")
        await pilot.pause(0.5)
        st = m._player.poll()
        check("player loads", st.loaded and "Song One" in st.label, str(st))
        m.action_play_toggle()
        await pilot.pause(0.4)
        st = m._player.poll()
        if isinstance(m._player, FfplayPlayer):
            check("pause works", st.paused, str(st))
        m._player.stop()
        app.exit()

    assert not fails, fails


def test_features(tmp_path):
    asyncio.run(scenario(tmp_path))
