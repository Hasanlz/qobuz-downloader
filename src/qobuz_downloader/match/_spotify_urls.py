import re
from urllib.parse import urlparse

_HOST = re.compile(
    r"^https?://(?:open|play)\.spotify\.com(?:/intl-[a-z]{2})?/", re.IGNORECASE
)
_KINDS = ("track", "album", "playlist")


def parse_spotify(url: str) -> tuple[str, str]:
    if not _HOST.match(url):
        raise ValueError(f"not a Spotify URL: {url}")
    segments = [segment for segment in urlparse(url).path.split("/") if segment]
    kind = None
    rest: list[str] = []
    for index, segment in enumerate(segments):
        if segment in _KINDS:
            kind = segment
            rest = segments[index + 1 :]
            break
    if kind is None:
        raise ValueError(f"unsupported Spotify URL: {url}")
    if not rest:
        raise ValueError(f"Spotify URL is missing an id: {url}")
    spotify_id = rest[0]
    if not spotify_id.isalnum():
        raise ValueError(f"invalid Spotify id in URL: {url}")
    return kind, spotify_id
