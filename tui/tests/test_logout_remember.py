"""remember-me default, auto-login skip, logout clearing (UI level)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from textual.widgets import Switch

from quaver.app import MainScreen, QuaverApp
from quaver.login import LoginScreen
from quaver.settings import Settings, load as load_settings, save

import test_app as T


def test_remember_switch_defaults_on(tmp_path, monkeypatch):
    monkeypatch.setenv("QUAVER_CONFIG_DIR", str(tmp_path / "config"))

    async def scenario():
        app = QuaverApp(settings=Settings(download_dir=str(tmp_path / "m")))
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause()
            switch = app.screen.query_one("#remember", Switch)
            assert switch.value is True
            app.exit()

    asyncio.run(scenario())


def test_logout_button_returns_to_login(tmp_path, monkeypatch):
    monkeypatch.setenv("QUAVER_CONFIG_DIR", str(tmp_path / "config"))

    async def scenario():
        settings = Settings(download_dir=str(tmp_path / "m"), remember=True,
                            token="tok", app_id="aid", app_secret="sec")
        app = QuaverApp(settings=settings)
        async with app.run_test(size=(150, 40)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            await pilot.pause()
            # click the real button
            await pilot.click("#logout")
            await pilot.pause()
            assert isinstance(app.screen, LoginScreen)
            reloaded = load_settings()
            assert reloaded.token == "" and reloaded.remember is False
            await pilot.pause()

    asyncio.run(scenario())
