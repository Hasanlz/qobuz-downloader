from abc import ABC, abstractmethod

import httpx

from qobuz_downloader.domain import Track


class LyricsSource(ABC):
    @abstractmethod
    def lrc(self, track: Track) -> str | None: ...


class LrcLib(LyricsSource):
    def __init__(self, http: httpx.Client | None = None, attempts: int = 2) -> None:
        self._http = http or httpx.Client(
            base_url="https://lrclib.net",
            headers={"User-Agent": "qobuz-downloader/0.1 (https://github.com/Hasanlz/qobuz-downloader)"},
            timeout=30.0,
        )
        self._attempts = attempts

    def lrc(self, track: Track) -> str | None:
        last_error: Exception | None = None
        for attempt in range(self._attempts):
            try:
                text = self._get(
                    {
                        "artist_name": track.artist,
                        "track_name": track.title,
                        "album_name": track.album,
                        "duration": track.duration_seconds,
                    }
                )
                if text:
                    return text
                response = self._http.get(
                    "/api/search",
                    params={"track_name": track.title, "artist_name": track.artist},
                )
                if response.status_code != 200:
                    return None
                for candidate in response.json():
                    if candidate.get("syncedLyrics") and _duration_ok(track, candidate):
                        return candidate["syncedLyrics"]
                # both endpoints answered: a definitive miss, no retry
                return None
            except httpx.HTTPError as error:
                last_error = error
        raise RuntimeError(f"lrclib unreachable after {self._attempts} attempts: {last_error}")

    def _get(self, params: dict) -> str | None:
        response = self._http.get("/api/get", params=params)
        if response.status_code == 200:
            return response.json().get("syncedLyrics")
        return None


def _duration_ok(track: Track, candidate: dict) -> bool:
    duration = candidate.get("duration")
    if track.duration_seconds is None or duration is None:
        return True
    return abs(duration - track.duration_seconds) <= 5
