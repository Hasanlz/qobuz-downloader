import logging
import time
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from mutagen import MutagenError
from mutagen.flac import FLAC

from qobuz_downloader.domain import Complete, Failed, Outcome, Quality, Stream, Track
from qobuz_downloader.engine import _tags
from qobuz_downloader.engine._source import ByteSource, HttpByteSource
from qobuz_downloader.lyrics import LyricsSource
from qobuz_downloader.naming import Naming
from qobuz_downloader.qobuz import Qobuz
from qobuz_downloader.tidal import Tidal

log = logging.getLogger(__name__)

_EXTENSIONS = {
    Quality.LOSSY: ".mp3",
    Quality.CD: ".flac",
    Quality.HIRES_96: ".flac",
    Quality.HIRES_192: ".flac",
}


class Engine:
    def __init__(
        self,
        qobuz: Qobuz,
        naming: Naming,
        source: ByteSource | None = None,
        retry_delays: Sequence[float] = (1.0, 2.0),
        lyrics: LyricsSource | None = None,
        tidal: Tidal | None = None,
    ) -> None:
        self._qobuz = qobuz
        self._naming = naming
        self._source: ByteSource = source or HttpByteSource()
        self._retry_delays = tuple(retry_delays)
        self._lyrics = lyrics
        self._tidal = tidal

    def download(self, track: Track, preferred: Quality) -> Outcome:
        rungs = [
            quality
            for quality in self._qobuz.qualities(track)
            if preferred >= quality > Quality.LOSSY
        ]
        if not rungs:
            return Failed(reason="only lossy audio is available for this track")
        requested = rungs[-1]
        path = self._naming.path_for(track, extension=_EXTENSIONS[requested])
        partial = path.with_suffix(path.suffix + ".part")
        last_error = ""
        attempts = (0.0, *self._retry_delays)
        for attempt, delay in enumerate(attempts):
            if delay:
                time.sleep(delay)
            try:
                stream = self._attempt(track, requested, partial)
                self._validate(partial)
                partial.replace(path)
                complete = self._maybe_upgrade(
                    Complete(
                        path=path,
                        quality=stream.quality,
                        fell_back=stream.quality < preferred,
                        sampling_rate=stream.sampling_rate,
                        bit_depth=stream.bit_depth,
                        lyrics_saved=self._write_lyrics(track, path),
                    ),
                    track,
                    path,
                )
                self._apply_tags(track, path)
                return complete
            except Exception as error:
                last_error = str(error) or type(error).__name__
                remaining = len(attempts) - attempt - 1
                if remaining:
                    log.warning(
                        "retrying %s: %s (%d attempt(s) left)",
                        track.title,
                        last_error,
                        remaining,
                    )
        return Failed(reason=last_error)

    def _maybe_upgrade(self, outcome: Complete, track: Track, path: Path) -> Outcome:
        """Replace the Qobuz file with a higher-quality Tidal copy if one exists.

        Research (docs/research/2026-09-09-tidal-quality-comparison.md) found
        upgrades only ever happen when Qobuz delivered 24-bit at 44.1 or
        48 kHz — everywhere else the check is wasted API traffic. A Tidal
        failure never fails the track: the Qobuz file is already on disk.
        """
        if self._tidal is None or outcome.upgraded:
            return outcome
        if outcome.bit_depth != 24 or (outcome.sampling_rate or 0) > 48.0:
            return outcome
        try:
            tidal_id = self._tidal.hires_match_for(track)
            if tidal_id is None:
                return outcome
            stream = self._tidal.stream(tidal_id)
            part = path.with_suffix(path.suffix + ".tidal.part")
            response = self._source.stream(stream.url, 0)
            with part.open("wb") as handle:
                for chunk in response.chunks:
                    handle.write(chunk)
            if response.length is not None and part.stat().st_size != response.length:
                raise ConnectionError(
                    f"incomplete tidal download: {part.stat().st_size}"
                    f" of {response.length} bytes"
                )
            flac = FLAC(str(part))
            bit_depth = flac.info.bits_per_sample
            sampling_rate = flac.info.sample_rate / 1000.0
            higher = bit_depth > (outcome.bit_depth or 0) or (
                bit_depth == outcome.bit_depth
                and sampling_rate > (outcome.sampling_rate or 0)
            )
            if not higher:
                log.info(
                    "tidal copy is not higher (%s/%s); keeping the Qobuz file",
                    bit_depth,
                    sampling_rate,
                )
                part.unlink()
                return outcome
            part.replace(path)
            log.info(
                "replaced with Tidal copy: %d/%g (Qobuz was %s/%s)",
                bit_depth,
                sampling_rate,
                outcome.bit_depth,
                outcome.sampling_rate,
            )
            return replace(
                outcome,
                bit_depth=bit_depth,
                sampling_rate=sampling_rate,
                upgraded=True,
            )
        except Exception as error:
            path.with_suffix(path.suffix + ".tidal.part").unlink(missing_ok=True)
            log.warning("tidal upgrade skipped: %s", error)
            return outcome

    def _attempt(
        self, track: Track, requested: Quality, partial: Path
    ) -> Stream:
        stream = self._qobuz.stream(track, requested)
        start = partial.stat().st_size if partial.exists() else 0
        response = self._source.stream(stream.url, start)
        if start and response.status != 206:
            start = 0
            response = self._source.stream(stream.url, 0)
        partial.parent.mkdir(parents=True, exist_ok=True)
        mode = "ab" if start else "wb"
        with partial.open(mode) as handle:
            for chunk in response.chunks:
                handle.write(chunk)
        if response.length is not None:
            expected = start + response.length if response.status == 206 else response.length
            actual = partial.stat().st_size
            if actual != expected:
                raise ConnectionError(
                    f"incomplete download: {actual} of {expected} bytes"
                )
        return stream

    def _validate(self, partial: Path) -> None:
        try:
            FLAC(str(partial))
        except MutagenError as error:
            partial.unlink(missing_ok=True)
            raise ValueError(f"corrupt FLAC file: {error}") from error

    def _apply_tags(self, track: Track, path: Path) -> None:
        """Tag the final file; never fail a finished download over metadata."""
        try:
            _tags.apply(path, track, self._qobuz.cover_url(track), self._source)
        except Exception as error:
            log.warning("tagging skipped for %s: %s", track.title, error)

    def _write_lyrics(self, track: Track, path: Path) -> bool:
        if self._lyrics is None:
            return False
        try:
            text = self._lyrics.lrc(track)
        except Exception:
            return False
        if not text:
            return False
        path.with_suffix(".lrc").write_text(text, encoding="utf-8")
        return True
