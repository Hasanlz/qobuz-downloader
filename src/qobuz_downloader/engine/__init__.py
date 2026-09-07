import time
from collections.abc import Sequence
from pathlib import Path

from mutagen import MutagenError
from mutagen.flac import FLAC

from qobuz_downloader.domain import Complete, Failed, Outcome, Quality, Stream, Track
from qobuz_downloader.engine._source import ByteSource, HttpByteSource
from qobuz_downloader.naming import Naming
from qobuz_downloader.qobuz import Qobuz

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
    ) -> None:
        self._qobuz = qobuz
        self._naming = naming
        self._source: ByteSource = source or HttpByteSource()
        self._retry_delays = tuple(retry_delays)

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
        for delay in (0.0, *self._retry_delays):
            if delay:
                time.sleep(delay)
            try:
                stream = self._attempt(track, requested, partial)
                self._validate(partial)
                partial.replace(path)
                return Complete(
                    path=path,
                    quality=stream.quality,
                    fell_back=stream.quality < preferred,
                    sampling_rate=stream.sampling_rate,
                    bit_depth=stream.bit_depth,
                )
            except Exception as error:
                last_error = str(error) or type(error).__name__
        return Failed(reason=last_error)

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
