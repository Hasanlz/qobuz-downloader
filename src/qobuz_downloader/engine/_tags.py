import logging
from pathlib import Path

from mutagen.flac import FLAC, Picture

from qobuz_downloader.domain import Track
from qobuz_downloader.engine._source import ByteSource

log = logging.getLogger(__name__)


def apply(path: Path, track: Track, cover_url: str | None, source: ByteSource) -> None:
    """Write tags and the embedded front cover into a FLAC or MP3 file.

    Idempotent: tags are overwritten and stale pictures are cleared first, so
    retagging an already-tagged file never duplicates cover art.
    """
    if path.suffix == ".flac":
        _apply_flac(path, track, cover_url, source)
    elif path.suffix == ".mp3":
        _apply_mp3(path, track, cover_url, source)


def _apply_flac(path, track, cover_url, source) -> None:
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


def _apply_mp3(path, track, cover_url, source) -> None:
    from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TRCK

    audio = ID3(str(path))
    audio.setall("TIT2", [TIT2(text=track.title)])
    audio.setall("TPE1", [TPE1(text=track.artist)])
    audio.setall("TALB", [TALB(text=track.album)])
    if track.track_number is not None:
        total = (
            f"{track.track_number}/{track.track_total}"
            if track.track_total is not None
            else str(track.track_number)
        )
        audio.setall("TRCK", [TRCK(text=total)])
    if cover_url:
        try:
            data = _cover_bytes(cover_url, source)
            mime = _mime(data)
            if mime is None:
                raise ValueError("cover is not a jpeg or png")
            audio.setall("APIC", [APIC(mime=mime, type=3, data=data)])
        except Exception as error:
            log.warning("cover art skipped: %s", error)
    audio.save(str(path))


def _cover(url: str, source: ByteSource) -> Picture:
    data = _cover_bytes(url, source)
    picture = Picture()
    picture.type = 3
    picture.mime = _mime(data)
    if picture.mime is None:
        raise ValueError("cover is not a jpeg or png")
    picture.data = data
    return picture


def _cover_bytes(url: str, source: ByteSource) -> bytes:
    response = source.stream(url, 0)
    return b"".join(response.chunks)


def _mime(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    return None
