from qobuz_downloader.match._interface import Matcher
from qobuz_downloader.match._spotify import EmbedSpotify
from qobuz_downloader.match.live import LiveSpotify

__all__ = ["Matcher", "LiveSpotify"]


def make_matcher(qobuz) -> Matcher:
    try:
        from qobuz_downloader.match._public import PublicSpotify

        return LiveSpotify(qobuz, api=PublicSpotify())
    except ImportError:
        return LiveSpotify(qobuz, api=EmbedSpotify())
