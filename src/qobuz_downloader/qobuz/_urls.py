import re
from urllib.parse import urlparse

_HOST = re.compile(r"^https?://(?:play|open|www)\.qobuz\.com", re.IGNORECASE)
_KINDS = ("album", "track", "artist", "playlist")


def parse(url: str) -> tuple[str, str]:
    if not _HOST.match(url):
        raise ValueError(f"not a Qobuz URL: {url}")
    segments = [segment for segment in urlparse(url).path.split("/") if segment]
    kind = None
    rest: list[str] = []
    for index, segment in enumerate(segments):
        if segment in _KINDS:
            kind = segment
            rest = segments[index + 1 :]
            break
        if segment == "interpreter":
            kind = "artist"
            rest = segments[index + 1 :]
            break
    if kind is None:
        raise ValueError(f"unsupported Qobuz URL: {url}")
    if not rest:
        raise ValueError(f"Qobuz URL is missing an id: {url}")
    item_id = rest[-1] if len(rest) > 1 else rest[0].split("-")[-1]
    return kind, item_id
