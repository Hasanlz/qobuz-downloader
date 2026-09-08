import difflib
import logging
import re
import unicodedata
from dataclasses import replace

from qobuz_downloader.domain import (
    Album,
    MatchResult,
    Matched,
    Track,
    Unmatched,
    UnmatchedTrack,
)
from qobuz_downloader.match._interface import Matcher
from qobuz_downloader.match._spotify import EmbedSpotify, Spotify, SpotifyMetadata
from qobuz_downloader.match._spotify_urls import parse_spotify
from qobuz_downloader.qobuz import Qobuz

log = logging.getLogger(__name__)

_THRESHOLD = 0.6
_DURATION_EXACT = 2
_DURATION_CLOSE = 5


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", stripped).strip()


def _similarity(left: str, right: str) -> float:
    return difflib.SequenceMatcher(None, _normalize(left), _normalize(right)).ratio()


def _duration_score(left: int | None, right: int | None) -> float:
    if left is None or right is None:
        return 0.5
    difference = abs(left - right)
    if difference <= _DURATION_EXACT:
        return 1.0
    if difference <= _DURATION_CLOSE:
        return 0.6
    return 0.0


def _score_track(spotify: Track, candidate: Track) -> float:
    title = _similarity(spotify.title, candidate.title)
    if title < 0.5:
        return 0.0
    return (
        title * 0.6
        + _similarity(spotify.artist, candidate.artist) * 0.25
        + _duration_score(spotify.duration_seconds, candidate.duration_seconds) * 0.15
    )


def _spotify_track(payload: dict) -> Track:
    return Track(
        id=f"spotify:{payload['id']}",
        title=payload.get("name", ""),
        artist=payload.get("artists", [{}])[0].get("name", ""),
        album=payload.get("album", {}).get("name", ""),
        duration_seconds=payload.get("duration_ms", 0) // 1000,
    )


class LiveSpotify(Matcher):
    def __init__(
        self,
        qobuz: Qobuz,
        client_id: str = "",
        client_secret: str = "",
        api: SpotifyMetadata | None = None,
    ) -> None:
        self._qobuz = qobuz
        self._api = api or EmbedSpotify()

    def match(self, url: str, limit: int | None = None) -> MatchResult:
        kind, spotify_id = parse_spotify(url)
        if kind == "track":
            return self._match_track_url(spotify_id)
        if kind == "album":
            return self._match_album_url(spotify_id)
        return self._match_playlist(spotify_id, limit)

    def _match_track_url(self, spotify_id: str) -> MatchResult:
        spotify_track = _spotify_track(self._api.track(spotify_id))
        candidate = self._best_track(spotify_track)
        if candidate is None:
            return Unmatched(
                url=spotify_id,
                reason=f"no Qobuz match for {spotify_track.artist} - {spotify_track.title}",
            )
        return Matched([candidate])

    def _match_album_url(self, spotify_id: str) -> MatchResult:
        payload = self._api.album(spotify_id)
        spotify_album = Album(
            id=f"spotify:{payload['id']}",
            title=payload.get("name", ""),
            artist=payload.get("artists", [{}])[0].get("name", ""),
            tracks_count=payload.get("total_tracks"),
        )
        candidate = self._best_album(spotify_album)
        if candidate is None:
            return Unmatched(
                url=spotify_id,
                reason=f"no Qobuz match for album {spotify_album.artist} - {spotify_album.title}",
            )
        # the matched Qobuz album is the collection; its own track numbers apply
        return Matched(
            [
                replace(track, collection=candidate.title)
                for track in self._qobuz.tracks(candidate)
            ]
        )

    def _match_playlist(self, spotify_id: str, limit: int | None = None) -> MatchResult:
        matched: list[Track] = []
        unmatched: list[UnmatchedTrack] = []
        name = self._api.playlist_name(spotify_id)
        log.info("matching playlist %s (%s) against Qobuz", spotify_id, name or "unnamed")
        for position, payload in enumerate(
            self._api.playlist_tracks(spotify_id, limit), start=1
        ):
            spotify_track = _spotify_track(payload)
            log.info("[%d] %s - %s", position, spotify_track.artist, spotify_track.title)
            candidate = self._best_track(spotify_track)
            if candidate is None:
                log.warning("    no Qobuz match")
                unmatched.append(
                    UnmatchedTrack(
                        title=spotify_track.title,
                        artist=spotify_track.artist,
                        reason="no Qobuz match",
                    )
                )
            else:
                log.info("    -> %s - %s", candidate.artist, candidate.title)
                # playlist position, not the album track number
                matched.append(
                    replace(candidate, track_number=position, collection=name)
                )
        if not matched:
            total = len(matched) + len(unmatched)
            return Unmatched(
                url=spotify_id,
                reason=f"none of {total} tracks matched on Qobuz",
            )
        return Matched(matched, unmatched)

    def _best_track(self, spotify_track: Track) -> Track | None:
        query = f"{spotify_track.artist} {spotify_track.title}"
        best: Track | None = None
        best_score = 0.0
        for candidate in self._qobuz.search_tracks(query, limit=20):
            score = _score_track(spotify_track, candidate)
            if score > best_score:
                best, best_score = candidate, score
        return best if best_score >= _THRESHOLD else None

    def _best_album(self, spotify_album: Album) -> Album | None:
        query = f"{spotify_album.artist} {spotify_album.title}"
        best: Album | None = None
        best_score = 0.0
        for candidate in self._qobuz.search_albums(query, limit=20):
            score = _similarity(spotify_album.title, candidate.title) * 0.6 + _similarity(
                spotify_album.artist, candidate.artist
            ) * 0.4
            if (
                spotify_album.tracks_count is not None
                and candidate.tracks_count == spotify_album.tracks_count
            ):
                score += 0.05
            if score > best_score:
                best, best_score = candidate, score
        return best if best_score >= _THRESHOLD else None
