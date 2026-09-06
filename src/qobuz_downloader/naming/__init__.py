import re
from dataclasses import dataclass
from pathlib import Path

from qobuz_downloader.domain import Track

_ILLEGAL = re.compile(r'[<>:"|?*\x00-\x1f\\/]')


def _clean(value: str) -> str:
    cleaned = _ILLEGAL.sub("_", value)
    return re.sub(r"\s+", " ", cleaned).rstrip(" .")


@dataclass(frozen=True, slots=True)
class Naming:
    directory_template: str
    filename_template: str
    root: Path = Path(".")

    def path_for(self, track: Track, extension: str = ".flac") -> Path:
        values = {
            "artist": _clean(track.artist),
            "album": _clean(track.album),
            "title": _clean(track.title),
            "tracknumber": (
                f"{track.track_number:02d}" if track.track_number is not None else ""
            ),
        }
        try:
            directory = self.directory_template.format_map(values)
            filename = self.filename_template.format_map(values)
        except KeyError as error:
            raise ValueError(f"unknown placeholder: {error}") from error
        if "/" in filename or "\\" in filename:
            raise ValueError("filename_template must not contain path separators")
        parts = [part for part in directory.split("/") if part]
        name = re.sub(r"\s+", " ", filename).strip(" -").strip()
        return self.root / Path(*parts) / f"{name}{extension}"
