import logging
from pathlib import Path

from mutagen.flac import FLAC, Picture

from qobuz_downloader.domain import Track
from qobuz_downloader.engine._source import ByteSource

log = logging.getLogger(__name__)


def apply(path: Path, track: Track, cover_url: str | None, source: ByteSource) -> None:
    """Write Vorbis comments and the embedded front cover into a FLAC file.

    Idempotent: tags are overwritten and stale pictures are cleared first, so
    retagging an already-tagged file never duplicates cover art.
    """
    if path.suffix != ".flac":
        return
    audio = FLAC(str(path))
    audio["title"] = track.title
    audio["artist"] = track.artist
    audio["album"] = track.album
    if track.track_number is not None:
        audio["tracknumber"] = str(track.track_number)
    if track.track_total is not None:
        audio["tracktotal"] = str(track.track_total)
    audio.clear_pictures()
    if cover_url:
        try:
            audio.add_picture(_cover(cover_url, source))
        except Exception as error:
            log.warning("cover art skipped: %s", error)
    audio.save()


def _cover(url: str, source: ByteSource) -> Picture:
    response = source.stream(url, 0)
    data = b"".join(response.chunks)
    mime = _mime(data)
    if mime is None:
        raise ValueError("cover is not a jpeg or png")
    picture = Picture()
    picture.type = 3
    picture.mime = mime
    picture.data = data
    return picture


def _mime(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    return None
