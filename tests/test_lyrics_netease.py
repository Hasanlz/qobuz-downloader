import httpx

from qobuz_downloader.domain import Track
from qobuz_downloader.lyrics import FallbackLyrics, NetEase

TRACK = Track(
    id="t1",
    title="The Reckoning",
    artist="Within Temptation",
    album="Resist",
    duration_seconds=251,
)

SEARCH_RESULT = {
    "result": {
        "songs": [
            {
                "id": 1343443756,
                "name": "The Reckoning",
                "duration": 251000,
                "artists": [{"name": "Within Temptation"}],
            },
            {
                "id": 1,
                "name": "The Reckoning (Instrumental)",
                "duration": 251000,
                "artists": [{"name": "Within Temptation"}],
            },
        ]
    }
}

LYRIC = "[00:32.01]As cold as stone, they march in darkness\n[04:06.61]"


class _FakeResponse:
    def __init__(self, status_code, json_body):
        self.status_code = status_code
        self._json = json_body

    def json(self):
        return self._json


def netease(handler):
    return NetEase()


def test_searches_then_fetches_synced_lyric(monkeypatch):
    seen = []

    def fake_post(url, data=None):
        seen.append(url)
        if url == "https://music.163.com/api/search/get":
            assert data["s"] == "Within Temptation The Reckoning"
            return _FakeResponse(200, SEARCH_RESULT)
        assert url == "https://music.163.com/api/song/lyric"
        assert data["id"] == 1343443756
        return _FakeResponse(200, {"lrc": {"lyric": LYRIC}})

    monkeypatch.setattr(httpx.Client, "post", staticmethod(fake_post))

    assert netease(None).lrc(TRACK) == LYRIC
    assert len(seen) == 2


def test_title_only_query_used_when_combined_query_misses(monkeypatch):
    def fake_post(url, data=None):
        query = (data or {}).get("s")
        if query == "Within Temptation The Reckoning":
            return _FakeResponse(200, {"result": {"songs": []}})
        if query == "The Reckoning":
            return _FakeResponse(200, SEARCH_RESULT)
        return _FakeResponse(200, {"lrc": {"lyric": LYRIC}})

    monkeypatch.setattr(httpx.Client, "post", staticmethod(fake_post))

    assert netease(None).lrc(TRACK) == LYRIC


def test_rejects_dissimilar_candidates(monkeypatch):
    payload = {
        "result": {
            "songs": [
                {
                    "id": 2,
                    "name": "Nothing Else Matters",
                    "duration": 389000,
                    "artists": [{"name": "Metallica"}],
                }
            ]
        }
    }

    def fake_post(url, data=None):
        return _FakeResponse(200, payload)

    monkeypatch.setattr(httpx.Client, "post", staticmethod(fake_post))

    assert netease(None).lrc(TRACK) is None


def test_skips_songs_without_lyrics(monkeypatch):
    def fake_post(url, data=None):
        if url == "https://music.163.com/api/search/get":
            return _FakeResponse(200, SEARCH_RESULT)
        return _FakeResponse(200, {"lrc": {"lyric": ""}})

    monkeypatch.setattr(httpx.Client, "post", staticmethod(fake_post))

    assert netease(None).lrc(TRACK) is None


def test_fallback_tries_second_source_when_first_misses():
    calls = []

    class Stub:
        def __init__(self, text):
            self.text = text

        def lrc(self, track):
            calls.append(self.text)
            return self.text

    chain = FallbackLyrics(Stub(None), Stub("got it"), Stub("never"))

    assert chain.lrc(TRACK) == "got it"
    assert calls == [None, "got it"]


def test_fallback_survives_unreachable_source():
    class Down:
        def lrc(self, track):
            raise RuntimeError("unreachable")

    class Up:
        def lrc(self, track):
            return "recovered"

    assert FallbackLyrics(Down(), Up()).lrc(TRACK) == "recovered"
