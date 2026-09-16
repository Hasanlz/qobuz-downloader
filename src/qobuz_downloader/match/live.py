import difflib
import logging
import re
import unicodedata
from dataclasses import replace

import httpx

from qobuz_downloader.domain import (
    Album,
    MatchResult,
    Matched,
    Track,
    Unmatched,
    UnmatchedTrack,
)
from qobuz_downloader.match._interface import Matcher
from qobuz_downloader.match._spotify import EmbedSpotify, SpotifyMetadata
from qobuz_downloader.match._spotify_urls import parse_spotify
from qobuz_downloader.qobuz import Qobuz

log = logging.getLogger(__name__)

_THRESHOLD = 0.6
_DURATION_EXACT = 2
_DURATION_CLOSE = 5

# Release noise that Spotify appends to titles but Qobuz usually doesn't
# carry: remasters, editions, versions, "from the ... soundtrack" tails,
# featuring credits. Stripped from both sides before comparing titles and
# building search queries, so "Hey You - 2011 Remastered Version" can match
# "Hey You".
_BRACKET_NOISE = re.compile(
    r"[([{][^)\]}]*"
    r"(?:remaster|reissue|deluxe|anniversar|expanded|edition|explicit"
    r"|mono|stereo|version|edit|session|reimagin|from the)"
    r"[^)\]}]*[)\]}]",
    re.IGNORECASE,
)
_TAIL_NOISE = re.compile(
    r"\s+-\s+[^-]*"
    r"(?:remaster|reissue|edition|version|edit|session|reimagin|from the)"
    r"[^-]*$",
    re.IGNORECASE,
)
_FEAT_NOISE = re.compile(
    r"[([{]\s*(?:feat|ft|featuring|with)\b[^)\]}]*[)\]}]"
    r"|\s+(?:feat|featuring)\b[^()]*$"
    r"|\s+-\s+(?:feat|ft|featuring|with)\b[^()]*$",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    latin = re.sub(r"[^a-z0-9]+", " ", stripped).strip()
    if latin:
        return latin
    # Non-Latin scripts (Persian, Arabic, CJK, ...) survive NFKD untouched;
    # keep their letters and digits so such titles stay comparable instead
    # of collapsing to an empty string that would match every other title.
    return re.sub(r"[^\w]+", " ", stripped).strip().replace("_", " ").strip()


def _clean_title(title: str) -> str:
    """Drop release noise and featuring credits from a track title."""
    cleaned = _BRACKET_NOISE.sub(" ", title)
    cleaned = _TAIL_NOISE.sub(" ", cleaned)
    cleaned = _FEAT_NOISE.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _similarity(left: str, right: str) -> float:
    a, b = _normalize(left), _normalize(right)
    if not a or not b:
        # an empty (normalized) side carries no signal: calling it a 100%
        # match — which difflib would — is how foreign-script tracks used
        # to match random candidates
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


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
    title = _similarity(_clean_title(spotify.title), _clean_title(candidate.title))
    if title < 0.5:
        return 0.0
    artist = _similarity(spotify.artist, candidate.artist)
    if artist < 0.5:
        # a shared title alone is not a match: "Ta Abad" by Az Shanbe must
        # not queue Mohsen Ebrahimzadeh's track of the same name
        return 0.0
    duration = _duration_score(
        spotify.duration_seconds, candidate.duration_seconds
    )
    if title < 0.9 and duration == 0.0:
        # same artist, similar-looking title but a clearly different
        # recording: "Touching My Soul" vs "Touching Heaven" (a 40s+ gap)
        return 0.0
    return title * 0.6 + artist * 0.25 + duration * 0.15


def _spotify_track(payload: dict) -> Track:
    return Track(
        id=f"spotify:{payload['id']}",
        title=payload.get("name", ""),
        artist=payload.get("artists", [{}])[0].get("name", ""),
        album=payload.get("album", {}).get("name", ""),
        duration_seconds=payload.get("duration_ms", 0) // 1000,
    )


def source_name_of(track_id: str) -> str:
    """Source prefix of a (possibly qualified) track id, "" for bare ids."""
    source, _, _rest = track_id.rpartition(":")
    return source


class LiveSpotify(Matcher):
    def __init__(
        self,
        qobuz: Qobuz,
        client_id: str = "",
        client_secret: str = "",
        api: SpotifyMetadata | None = None,
        catalog=None,
    ) -> None:
        self._qobuz = qobuz
        self._api = api or EmbedSpotify()
        # Optional multi-source resolver (see match._catalog); when absent
        # matching stays Qobuz-only, which is today's default behavior.
        self._catalog = catalog
        self._sources_label = getattr(catalog, "label", "Qobuz")

    def match(self, url: str) -> MatchResult:
        kind, spotify_id = parse_spotify(url)
        if kind == "track":
            return self._match_track_url(spotify_id)
        if kind == "album":
            return self._match_album_url(spotify_id)
        return self._match_playlist(spotify_id)

    def _match_track_url(self, spotify_id: str) -> MatchResult:
        spotify_track = _spotify_track(self._api.track(spotify_id))
        candidate = self._best_track(spotify_track)
        if candidate is None:
            return Unmatched(
                url=spotify_id,
                reason=f"no {self._sources_label} match for {spotify_track.artist} - {spotify_track.title}",
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
        tracks = self._qobuz.tracks(candidate)
        total = candidate.tracks_count or len(tracks)
        return Matched(
            [
                replace(track, collection=candidate.title, track_total=total)
                for track in tracks
            ]
        )

    def _match_playlist(self, spotify_id: str) -> MatchResult:
        matched: list[Track] = []
        unmatched: list[UnmatchedTrack] = []
        name = self._api.playlist_name(spotify_id)
        log.info("matching playlist %s (%s) against Qobuz", spotify_id, name or "unnamed")
        payloads = self._api.playlist_tracks(spotify_id)
        total = len(payloads)
        for position, payload in enumerate(payloads, start=1):
            spotify_track = _spotify_track(payload)
            log.info("[%d] %s - %s", position, spotify_track.artist, spotify_track.title)
            try:
                candidate = self._best_track(spotify_track)
            except (httpx.HTTPError, RuntimeError) as error:
                # A failing search for one track (Qobuz's backend 400s/hangs
                # on some queries) must not abandon the rest of the playlist:
                # report this track unmatched and keep queuing the others.
                log.warning("    search error, treated as unmatched: %s", error)
                unmatched.append(
                    UnmatchedTrack(
                        title=spotify_track.title,
                        artist=spotify_track.artist,
                        reason=f"search error: {error}",
                    )
                )
                continue
            if candidate is None:
                log.warning("    no %s match", self._sources_label)
                unmatched.append(
                    UnmatchedTrack(
                        title=spotify_track.title,
                        artist=spotify_track.artist,
                        reason=f"no {self._sources_label} match",
                    )
                )
            else:
                log.info("    -> %s - %s", candidate.artist, candidate.title)
                # playlist position, not the album track number
                matched.append(
                    replace(
                        candidate,
                        track_number=position,
                        collection=name,
                        track_total=total,
                    )
                )
        if not matched:
            total = len(matched) + len(unmatched)
            return Unmatched(
                url=spotify_id,
                reason=f"none of {total} tracks matched on {self._sources_label}",
            )
        return Matched(matched, unmatched)

    def _best_track(self, spotify_track: Track) -> Track | None:
        if self._catalog is not None:
            # Multi-source resolution: the catalog decides per-source order
            # (its `mode`), routing Qobuz through this matcher's own
            # strategy so the album-route fallback keeps working there.
            if self._catalog.mode == "best":
                return self._catalog.resolve_best(
                    spotify_track, self._best_on_qobuz
                )
            return self._catalog.resolve(spotify_track, self._best_on_qobuz)
        best, score = self._best_on_qobuz(spotify_track)
        return best if best is not None and score >= _THRESHOLD else None

    def _best_on_qobuz(self, spotify_track: Track) -> tuple[Track | None, float]:
        queries = [f"{spotify_track.artist} {spotify_track.title}"]
        cleaned = _clean_title(spotify_track.title)
        if cleaned and cleaned != spotify_track.title:
            # The full Spotify title can pollute the search: "Pink Floyd Money
            # - 2011 Remastered Version" makes Qobuz return Wall tracks that
            # aren't Money, and covers can outrank the original. Also search
            # with the release noise stripped and keep the best candidate.
            queries.append(f"{spotify_track.artist} {cleaned}")
        best: Track | None = None
        best_score = 0.0
        failure: Exception | None = None
        for query in queries:
            try:
                candidates = self._qobuz.search_tracks(query, limit=20)
                if not candidates:
                    # an empty page is usually a transient search hiccup, not a
                    # missing track — one retry before giving up on the query
                    log.warning("    empty search result for %r, retrying", query)
                    candidates = self._qobuz.search_tracks(query, limit=20)
            except (httpx.HTTPError, RuntimeError) as error:
                # Qobuz's search backend 400s/hangs on a few queries; lose
                # this source for the track, not the whole playlist. Keep the
                # error: if nothing matches below it must surface as a
                # retryable search failure, not as "not on Qobuz".
                log.warning("    qobuz search failed for %r: %s", query, error)
                failure = failure or error
                candidates = []
            for candidate in candidates:
                score = _score_track(spotify_track, candidate)
                if score > best_score:
                    best, best_score = candidate, score
        if best_score < _THRESHOLD and spotify_track.album:
            # Some studio tracks never surface in track search (only covers
            # and live versions do) but sit right on the album: match the
            # album, then score the wanted title against its tracks.
            try:
                best, best_score = self._best_from_album(spotify_track)
            except (httpx.HTTPError, RuntimeError) as error:
                log.warning("    qobuz album search failed: %s", error)
                failure = failure or error
        if best_score < _THRESHOLD and failure is not None:
            # Every route to this track failed on the backend. Reporting a
            # clean miss here is what silently dropped recoverable tracks
            # from a degraded run; raise so the caller marks it retryable.
            raise RuntimeError(
                f"search failed for {spotify_track.artist} - {spotify_track.title}: {failure}"
            ) from failure
        return best, best_score

    def _best_from_album(self, spotify_track: Track) -> tuple[Track | None, float]:
        best: Track | None = None
        best_score = 0.0
        for album in self._qobuz.search_albums(
            f"{spotify_track.artist} {spotify_track.album}", limit=5
        ):
            for candidate in self._qobuz.tracks(album):
                score = _score_track(spotify_track, candidate)
                if score > best_score:
                    best, best_score = candidate, score
        return best, best_score

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
