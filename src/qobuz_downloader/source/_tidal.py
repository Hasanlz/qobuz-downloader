from qobuz_downloader.source import Source, parse

__all__ = ["TidalSource"]


class TidalSource(Source):
    """The Tidal client seen through the Source surface.

    Queued tidal tracks carry `tidal:<id>` ids; this adapter strips the
    prefix before calling the wrapped client, which speaks native ids.
    """

    name = "tidal"

    def __init__(self, tidal) -> None:
        self._tidal = tidal

    def search_tracks(self, query: str, limit: int):
        return self._tidal.search_tracks(query, limit)

    def qualities(self, track):
        _, native_id = parse(track.id)
        return self._tidal.qualities(native_id)

    def stream(self, track, quality):
        _, native_id = parse(track.id)
        return self._tidal.stream(native_id)

    def cover_url(self, track):
        _, native_id = parse(track.id)
        return self._tidal.cover_url(native_id)
