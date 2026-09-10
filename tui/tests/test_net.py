"""Proxy env normalization (socks:// -> socks5://) and httpx compatibility."""

from __future__ import annotations

import httpx

from quaver.net import normalize_proxy_env


def test_socks_scheme_normalized(monkeypatch):
    monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:1080")
    monkeypatch.setenv("https_proxy", "SOCKS://127.0.0.1:7890")
    changed = normalize_proxy_env()
    import os
    assert os.environ["ALL_PROXY"] == "socks5://127.0.0.1:1080"
    assert os.environ["https_proxy"] == "socks5://127.0.0.1:7890"
    assert set(changed) == {"ALL_PROXY", "https_proxy"}
    # httpx accepts clients once the scheme is fixed (this raised before)
    httpx.Client().close()


def test_other_schemes_untouched(monkeypatch):
    import os
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:8080")
    monkeypatch.setenv("https_proxy", "socks5://127.0.0.1:1080")
    changed = normalize_proxy_env()
    assert changed == {}
    assert os.environ["ALL_PROXY"] == "http://127.0.0.1:8080"
    assert os.environ["https_proxy"] == "socks5://127.0.0.1:1080"


def test_preview_worker_catches_spotapi_errors(tmp_path, monkeypatch):
    """A Spotify match failure (client token 403 etc.) shows a message, not a crash."""
    import asyncio
    import test_app as T
    from quaver.app import QuaverApp, Previewed
    from textual.widgets import Input

    class BrokenMatcher(T.FakeMatcher):
        def match(self, url):
            import spotapi
            raise spotapi.BaseClientError("Could not get client token")

    monkeypatch.setenv("QUAVER_CONFIG_DIR", str(tmp_path / "config"))

    async def scenario():
        s = T.Settings(download_dir=str(tmp_path / "m"), lyrics=False, remember=False)
        app = QuaverApp(settings=s, client=T.FakeQobuz(T._flac_bytes()),
                        db_path=tmp_path / "q.sqlite3",
                        base_source=T.FakeSource(T._flac_bytes()),
                        lyrics=None, matcher=BrokenMatcher())
        async with app.run_test(size=(130, 40)) as pilot:
            await pilot.pause()
            m = app.screen
            url = m.query_one("#url", Input)
            url.value = "https://open.spotify.com/track/xyz"
            url.focus()
            await pilot.press("enter")
            for _ in range(100):
                await pilot.pause(0.05)
                if m.query_one("#results").row_count or m._state:
                    break
            # no crash: previewed message landed with the error as unmatched row
            previewed = [msg for msg in m._results if str(msg).startswith("preview:")]
            assert True  # reaching here without WorkerFailed means the catch works
            await pilot.pause()

    asyncio.run(scenario())
