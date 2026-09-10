import difflib
import re
import unicodedata

import httpx

from qobuz_downloader.domain import Track
from qobuz_downloader.lyrics._interface import LyricsSource

_SEARCH = "https://music.163.com/api/search/get"
_LYRIC = "https://music.163.com/api/song/lyric"
_DURATION_TOLERANCE = 5


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", stripped).strip()


def _similarity(left: str, right: str) -> float:
    return difflib.SequenceMatcher(None, _normalize(left), _normalize(right)).ratio()


def _duration_score(want: int | None, got: float) -> float:
    if want is None:
        return 0.5
    difference = abs(got - want)
    if difference <= 2:
        return 1.0
    if difference <= _DURATION_TOLERANCE:
        return 0.6
    return 0.0


class NetEase(LyricsSource):
    """Lyrics from NetEase Cloud Music, used as a fallback for songs LrcLib
    doesn't carry. The anonymous search endpoint degrades to garbage results
    once a session has made a few requests, so every lookup runs on a fresh
    connection. Query strategy: artist+title first, then title only when the
    combined query drowns the right candidate in covers."""

    def __init__(self, attempts: int = 2) -> None:
        self._attempts = attempts

    def lrc(self, track: Track) -> str | None:
        last_error: Exception | None = None
        for attempt in range(self._attempts):
            http = httpx.Client(
                headers={"User-Agent": "qobuz-downloader/0.1"}, timeout=30.0
            )
            try:
                return self._lookup(http, track)
            except httpx.HTTPError as error:
                last_error = error
            finally:
                http.close()
        raise RuntimeError(f"netease unreachable after {self._attempts} attempts: {last_error}")

    def _lookup(self, http: httpx.Client, track: Track) -> str | None:
        for query in (f"{track.artist} {track.title}", track.title):
            candidate = self._best(http, track, query)
            if candidate is None:
                continue
            lyric = self._lyric(http, candidate["id"])
            if lyric:
                return lyric
        return None

    def _best(self, http: httpx.Client, track: Track, query: str) -> dict | None:
        response = http.post(_SEARCH, data={"s": query, "type": 1, "limit": 30})
        if response.status_code != 200:
            return None
        songs = response.json().get("result", {}).get("songs") or []
        best = None
        best_score = 0.0
        for song in songs:
            title = _similarity(track.title, song.get("name", ""))
            if title < 0.5:
                continue
            artists = song.get("artists") or []
            artist = _similarity(track.artist, artists[0].get("name", "")) if artists else 0.0
            duration_ms = song.get("duration") or 0
            duration = _duration_score(track.duration_seconds, duration_ms / 1000)
            score = title * 0.6 + artist * 0.25 + duration * 0.15
            if score > best_score:
                best_score = score
                best = song
        if best_score < 0.6 or best is None:
            return None
        return best

    def _lyric(self, http: httpx.Client, song_id) -> str | None:
        response = http.post(_LYRIC, data={"id": song_id, "lv": 1})
        if response.status_code != 200:
            return None
        lyric = response.json().get("lrc", {}).get("lyric")
        return lyric or None
