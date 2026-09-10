import httpx

from qobuz_downloader.domain import Track
from qobuz_downloader.lyrics import LrcLib

TRACK = Track(
    id="t1",
    title="Rehab",
    artist="Amy Winehouse",
    album="Back To Black",
    duration_seconds=215,
)


def lrc_lib(handler):
    return LrcLib(
        http=httpx.Client(
            base_url="https://lrclib.net",
            transport=httpx.MockTransport(handler),
        )
    )


SYNCED = "[00:01.24] They tried to make me go to rehab"


def test_get_returns_synced_lyrics():
    def handler(request):
        return httpx.Response(
            200,
            json={"syncedLyrics": SYNCED, "plainLyrics": "plain"},
        )

    assert lrc_lib(handler).lrc(TRACK) == SYNCED


def test_falls_back_to_search_with_duration_filter():
    def handler(request):
        if request.url.path == "/api/get":
            return httpx.Response(404)
        assert request.url.path == "/api/search"
        return httpx.Response(
            200,
            json=[
                {"syncedLyrics": None, "duration": 215},
                {"syncedLyrics": SYNCED, "duration": 218},
                {"syncedLyrics": SYNCED, "duration": 400},
            ],
        )

    assert lrc_lib(handler).lrc(TRACK) == SYNCED


def test_returns_none_when_no_synced_candidates():
    def handler(request):
        if request.url.path == "/api/get":
            return httpx.Response(404)
        return httpx.Response(200, json=[{"syncedLyrics": None, "duration": 215}])

    assert lrc_lib(handler).lrc(TRACK) is None


def test_track_without_duration_accepts_any_candidate():
    track = Track(id="t2", title="Rehab", artist="Amy Winehouse", album="B")

    def handler(request):
        if request.url.path == "/api/get":
            return httpx.Response(404)
        return httpx.Response(
            200, json=[{"syncedLyrics": SYNCED, "duration": 999}]
        )

    assert lrc_lib(handler).lrc(track) == SYNCED


def test_retries_transient_network_errors():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("reset")
        return httpx.Response(200, json={"syncedLyrics": SYNCED, "plainLyrics": "plain"})

    assert lrc_lib(handler).lrc(TRACK) == SYNCED
    assert calls["n"] == 2
