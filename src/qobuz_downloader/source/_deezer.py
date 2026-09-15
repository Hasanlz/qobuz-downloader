from qobuz_downloader.source import Source, parse

__all__ = ["DeezerSource"]


class DeezerSource(Source):
    """The Deezer client seen through the Source surface.

    Queued deezer tracks carry `deezer:<id>` ids; this adapter strips
    the prefix before calling the wrapped client, which speaks native
    ids.
    """

    name = "deezer"

    def __init__(self, deezer) -> None:
        self._deezer = deezer

    def search_tracks(self, query: str, limit: int):
        return self._deezer.search_tracks(query, limit)

    def qualities(self, track):
        _, native_id = parse(track.id)
        return self._deezer.qualities(native_id)

    def stream(self, track, quality):
        return self._deezer.stream(track, quality)

    def cover_url(self, track):
        _, native_id = parse(track.id)
        return self._deezer.cover_url(native_id)
