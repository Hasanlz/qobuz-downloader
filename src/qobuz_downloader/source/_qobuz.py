from qobuz_downloader.source import Source, parse, qualify

__all__ = ["Source", "parse", "qualify", "QobuzSource"]


class QobuzSource(Source):
    """The Qobuz client seen through the Source surface.

    The engine talks to this adapter; the wrapped `Qobuz` interface stays
    the module boundary the matcher and TUI already use.
    """

    name = "qobuz"

    def __init__(self, qobuz) -> None:
        self._qobuz = qobuz

    def search_tracks(self, query: str, limit: int):
        return self._qobuz.search_tracks(query, limit)

    def qualities(self, track):
        return self._qobuz.qualities(track)

    def stream(self, track, quality):
        return self._qobuz.stream(track, quality)

    def cover_url(self, track):
        return self._qobuz.cover_url(track)
