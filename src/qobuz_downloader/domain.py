from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path


class Quality(IntEnum):
    LOSSY = 0
    CD = 1
    HIRES_96 = 2
    HIRES_192 = 3


@dataclass(frozen=True, slots=True)
class Track:
    id: str
    title: str
    artist: str
    album: str
    track_number: int | None = None
    duration_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class Album:
    id: str
    title: str
    artist: str
    tracks_count: int | None = None


@dataclass(frozen=True, slots=True)
class Artist:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Playlist:
    id: str
    title: str


type Item = Track | Album | Artist | Playlist


@dataclass(frozen=True, slots=True)
class Stream:
    url: str
    quality: Quality
    sampling_rate: float | None = None
    bit_depth: int | None = None


@dataclass(frozen=True, slots=True)
class Complete:
    path: Path
    quality: Quality
    fell_back: bool
    sampling_rate: float | None = None
    bit_depth: int | None = None
    lyrics_saved: bool = False


@dataclass(frozen=True, slots=True)
class Failed:
    reason: str


type Outcome = Complete | Failed


@dataclass(frozen=True, slots=True)
class UnmatchedTrack:
    title: str
    artist: str
    reason: str


@dataclass(frozen=True, slots=True)
class Matched:
    tracks: list[Track]
    unmatched: list[UnmatchedTrack] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Unmatched:
    url: str
    reason: str


type MatchResult = Matched | Unmatched
