"""Tests: play-without-download, play button with focus loss, seek bar, spectrum."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from textual.widgets import DataTable, Input, Static

from qobuz_downloader.domain import Stream

from quaver.player import NullPlayer, PlayerState
from quaver.spectrum import Spectrum
from quaver.app import MainScreen, QuaverApp

import test_app as T

fails: list[str] = []


def check(name, condition, detail=""):
    print(("PASS: " if condition else "FAIL: ") + name + ("" if condition else f" — {detail[-200:]}"))
    if not condition:
        fails.append(name)


class RecordingPlayer(NullPlayer):
    """Records play() calls; simulates a loaded stream."""

    def __init__(self):
        self.state = PlayerState()
        self.played = []

    def play(self, source, label):
        self.played.append((str(source), label))
        self.state = PlayerState(loaded=True, paused=False, label=label)
        self.state.duration = 30.0

    def toggle(self):
        if not self.state.loaded:
            return None
        self.state.paused = not self.state.paused
        return self.state.paused

    def stop(self):
        self.state = PlayerState()


class PlayerQobuz(T.FakeQobuz):
    def stream(self, track, quality):
        return Stream(
            url=f"https://stream.test/{track.id}", quality=quality,
            sampling_rate=44.1, bit_depth=16,
        )


def test_enter_on_preview_plays_without_downloading(tmp_path):
    root = tmp_path / "m"
    db = tmp_path / "q.sqlite3"
    player = RecordingPlayer()

    async def scenario():
        s = T.Settings(download_dir=str(root), lyrics=False, remember=False)
        app = QuaverApp(settings=s, client=PlayerQobuz(T._flac_bytes()), db_path=db,
                        base_source=T.FakeSource(T._flac_bytes()), lyrics=None,
                        matcher=T.FakeMatcher(), player=player)
        async with app.run_test(size=(130, 45)) as pilot:
            await pilot.pause()
            m = app.screen
            url = m.query_one("#url", Input)
            url.value = "https://open.spotify.com/track/6R5yT5bLnjn7Mbuo74rD35"
            url.focus()
            await pilot.click("#find")
            results = m.query_one("#results", DataTable)
            for _ in range(100):
                await pilot.pause(0.05)
                if results.row_count:
                    break
            check("preview rows shown", results.row_count == 1)

            # Enter on the preview row must PLAY, not download
            results.focus()
            await pilot.press("enter")
            await pilot.pause(0.4)
            check("enter plays without downloading", len(player.played) == 1, str(player.played))
            check("played the stream url", player.played and player.played[0][0].startswith("https://stream.test/"), str(player.played))
            check("nothing was downloaded", T.db_states(db) == {}, str(T.db_states(db)))

            # ▶ button with focus ON THE BUTTON must still play the highlighted track
            m._player.stop()
            await pilot.click("#play-toggle")
            await pilot.pause(0.4)
            check("play button uses remembered highlight", len(player.played) == 2, str(player.played))
            check("focus restored to table", isinstance(app.focused, DataTable))

            # space pauses/resumes the loaded track
            await pilot.press("space")
            await pilot.pause(0.2)
            check("space toggles pause", m._player.state.paused is True)
            await pilot.press("space")
            await pilot.pause(0.2)
            check("space resumes", m._player.state.paused is False)

            # seek bar reflects position
            m._player.state.position = 10.0
            await pilot.pause(0.7)  # tick interval 0.5s
            seek = m.query_one("#seek", Static)
            check("seek bar filled partially", "╸" in str(seek.render()), str(seek.render()))

            # d downloads the highlighted preview row
            await pilot.press("d")
            for _ in range(100):
                await pilot.pause(0.05)
                if T.db_states(db).get("t4") is not None:
                    break
            check("d downloads highlighted row", T.db_states(db).get("t4") is not None, str(T.db_states(db)))

            app.exit()

    asyncio.run(scenario())
    assert not fails, fails


def test_spectrum_bars():
    spec = Spectrum()
    check("empty spectrum renders silence", spec.bars(8) == "▁▁▁▁▁▁▁▁")
    # simulate levels
    import threading
    spec._values.append(-40.0)  # quiet
    spec._values.append(-5.0)  # peak
    bars = spec.bars(2)
    check("quiet sample is low block", bars[0] in "▁▂", bars)
    check("loud sample is high block", bars[1] in "▆▇█", bars)
    check("level peaks at one", spec.level() == 1.0, str(spec.level()))
    assert not fails, fails
