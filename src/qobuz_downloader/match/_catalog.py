"""Multi-source catalog resolution for the matcher.

Resolves a Spotify track against one or more Sources (Qobuz, Tidal,
Deezer): candidates are scored with the matcher's `_score_track`, the
winner's id is stamped with its source prefix, and tracks missing from
the preferred catalog fall back to the others so a wanted track is
eventually downloaded from somewhere.

Modes (the `--source` flag):
- ``qobuz`` — Qobuz first (its richer album-route strategy), Tidal and
  Deezer as fallbacks; today's default behavior
- ``tidal`` — Tidal first, Qobuz as fallback
- ``best`` — search every source, keep the highest-quality copy (ties:
  match score, then provider order)
"""

import logging
from dataclasses import replace

from qobuz_downloader.domain import Quality, Track
from qobuz_downloader.match.live import _THRESHOLD, _clean_title, _score_track
from qobuz_downloader.source import Source, qualify

log = logging.getLogger(__name__)


def stamped(track: Track, source_name: str) -> Track:
    """Candidate with its id qualified for the queue ("tidal:<id>")."""
    return replace(track, id=qualify(source_name, track.id))


class Catalog:
    """Searches the configured Sources, in order, for a Spotify track.

    The Qobuz entry is special: it resolves through the matcher's own
    strategy (dual query + album-route fallback) rather than the plain
    two-query search the other sources use, so Qobuz matching keeps all
    of its hard-won behavior.
    """

    def __init__(
        self,
        sources: list[Source],
        label: str = "Qobuz",
        mode: str = "qobuz",
        allow_lossy: bool = False,
    ) -> None:
        self._sources = sources
        self.label = label
        self.mode = mode
        self._allow_lossy = allow_lossy

    def resolve(self, spotify_track: Track, qobuz_strategy) -> Track | None:
        """First source carrying the track wins; the rest are fallbacks."""
        for source in self._sources:
            candidate = self._resolve_on(source, spotify_track, qobuz_strategy)
            if candidate is not None:
                return candidate
        return None

    def resolve_best(
        self, spotify_track: Track, qobuz_strategy
    ) -> Track | None:
        """Search every source and keep the highest-quality copy."""
        best: Track | None = None
        best_key: tuple[int, float, int] | None = None
        for order, source in enumerate(self._sources):
            candidate = self._resolve_on(source, spotify_track, qobuz_strategy)
            if candidate is None:
                continue
            score = _score_track(spotify_track, candidate)
            quality = self._top_quality(source, candidate)
            key = (int(quality), score, -order)
            if best_key is None or key > best_key:
                best, best_key = candidate, key
        return best

    def _resolve_on(
        self, source: Source, spotify_track: Track, qobuz_strategy
    ) -> Track | None:
        """Best above-threshold candidate on one source, id qualified."""
        if source.name == "qobuz":
            best, score = qobuz_strategy(spotify_track)
            if best is not None and score >= _THRESHOLD:
                return best  # bare id: Qobuz keeps its queue-DB convention
            return None
        queries = [f"{spotify_track.artist} {spotify_track.title}"]
        cleaned = _clean_title(spotify_track.title)
        if cleaned and cleaned != spotify_track.title:
            # Same release-noise problem as Qobuz: "Money - 2011
            # Remastered Version" must also search as "Money" here
            queries.append(f"{spotify_track.artist} {cleaned}")
        best: Track | None = None
        best_score = 0.0
        for query in queries:
            try:
                candidates = source.search_tracks(query, limit=20)
                if not candidates:
                    candidates = source.search_tracks(query, limit=20)
            except Exception as error:
                log.warning(
                    "    %s search failed for %r: %s", source.name, query, error
                )
                return None
            for candidate in candidates:
                score = _score_track(spotify_track, candidate)
                if score > best_score:
                    best, best_score = candidate, score
        if best is None or best_score < _THRESHOLD:
            return None
        if not self._allow_lossy:
            # A lossless copy must exist somewhere: don't queue a source
            # that can only deliver lossy audio for this track
            try:
                ladder = source.qualities(stamped(best, source.name))
            except Exception:
                return None
            if Quality.CD not in ladder:
                log.info(
                    "    %s only has lossy audio for this track; skipping",
                    source.name,
                )
                return None
        log.info(
            "    -> %s - %s (from %s)",
            best.artist,
            best.title,
            source.name,
        )
        return stamped(best, source.name)

    @staticmethod
    def _top_quality(source: Source, track: Track) -> Quality:
        """Highest quality the source can deliver this track at."""
        try:
            ladder = source.qualities(track)
        except Exception:
            return Quality.LOSSY
        return max(ladder) if ladder else Quality.LOSSY
