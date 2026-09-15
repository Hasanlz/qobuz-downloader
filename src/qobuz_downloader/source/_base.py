import logging

from qobuz_downloader.domain import Quality, Stream, Track

log = logging.getLogger(__name__)

QOBUZ = "qobuz"


def parse(track_id: str) -> tuple[str, str]:
    """Split a queued Track id into (source name, native id).

    Bare ids (no colon) are Qobuz tracks from queues created before
    other sources existed; ids from those sources are prefixed
    ("tidal:233554206", "deezer:123456").
    """
    source, _, native = track_id.rpartition(":")
    return (source or QOBUZ, native) if native else (QOBUZ, track_id)


def qualify(source: str, native_id: str) -> str:
    """Build a queued Track id for a source-prefixed track.

    Qobuz keeps bare ids so existing queue databases stay valid.
    """
    return native_id if source == QOBUZ else f"{source}:{native_id}"


class Source:
    """The surface every download platform implements.

    Qobuz's existing interface already satisfies this shape; other
    platforms implement it directly. Callers treat Tracks as opaque ids
    parsed with `parse`.
    """

    name = "qobuz"

    def search_tracks(self, query: str, limit: int) -> list[Track]:
        raise NotImplementedError

    def qualities(self, track: Track) -> list[Quality]:
        raise NotImplementedError

    def stream(self, track: Track, quality: Quality) -> Stream:
        raise NotImplementedError

    def cover_url(self, track: Track) -> str | None:
        raise NotImplementedError
