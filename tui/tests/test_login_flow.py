"""Tests: remember-me auto-login, logout clearing, remember default."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from quaver.app import QuaverApp, MainScreen
from quaver.login import LoginScreen
from quaver.settings import Settings, load as load_settings

import test_app as T

fails: list[str] = []


def check(name, condition, detail=""):
    print(("PASS: " if condition else "FAIL: ") + name + ("" if condition else f" — {detail[-200:]}"))
    if not condition:
        fails.append(name)


def test_remember_me_default_on():
    check("remember defaults to on", Settings().remember is True)


def test_remembered_credentials_skip_login(tmp_path, monkeypatch):
    monkeypatch.setenv("QUAVER_CONFIG_DIR", str(tmp_path / "config"))
    for var in ("QOBUZ_USER_AUTH_TOKEN", "QOBUZ_APP_ID", "QOBUZ_APP_SECRET", "QOBUZ_EMAIL", "QOBUZ_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    # saved session (what Log in with remember-me writes)
    from quaver.settings import save
    settings = Settings(download_dir=str(tmp_path / "music"), remember=True,
                        token="tok", app_id="aid", app_secret="sec")
    save(settings)

    async def scenario():
        app = QuaverApp(settings=load_settings())
        async with app.run_test(size=(100, 30)) as pilot:
            for _ in range(40):
                await pilot.pause(0.05)
                if isinstance(app.screen, MainScreen):
                    break
            check("remembered token lands on main screen", isinstance(app.screen, MainScreen),
                  type(app.screen).__name__)
            await pilot.pause()
    asyncio.run(scenario())
    assert not fails, fails


def test_logout_clears_credentials_and_shows_login(tmp_path, monkeypatch):
    monkeypatch.setenv("QUAVER_CONFIG_DIR", str(tmp_path / "config"))
    settings = Settings(download_dir=str(tmp_path / "music"), remember=True,
                        token="tok", app_id="aid", app_secret="sec")
    async def scenario():
        app = QuaverApp(settings=settings)
        async with app.run_test(size=(100, 30)) as pilot:
            for _ in range(40):
                await pilot.pause(0.05)
                if isinstance(app.screen, MainScreen):
                    break
            check("starts on main", isinstance(app.screen, MainScreen))
            app.logout()
            await pilot.pause()
            check("logout shows login screen", isinstance(app.screen, LoginScreen))
            reloaded = load_settings()
            check("credentials wiped", not reloaded.token and not reloaded.app_id, str(reloaded))
            check("remember off after logout", reloaded.remember is False)
            # relaunching after logout shows login, not main
            app2 = QuaverApp(settings=load_settings())
            async with app2.run_test(size=(100, 30)) as pilot2:
                await pilot2.pause()
                check("relaunch after logout asks for login", isinstance(app2.screen, LoginScreen))
            await pilot.pause()
            await pilot.pause()
    asyncio.run(scenario())
    assert not fails, fails
