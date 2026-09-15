from abc import ABC, abstractmethod

from qobuz_downloader.domain import Quality, Stream, Track


class Deezer(ABC):
    @abstractmethod
    def search_tracks(self, query: str, limit: int) -> list[Track]:
        """Search Deezer's catalog (public api.deezer.com, no auth)."""

    @abstractmethod
    def qualities(self, deezer_track_id: str) -> list[Quality]:
        """The Quality ladder a Deezer track offers (gw-light metadata)."""

    @abstractmethod
    def stream(self, track: Track, quality: Quality) -> Stream:
        """Resolve a Deezer track to a downloadable (decrypting) stream."""

    @abstractmethod
    def cover_url(self, deezer_track_id: str) -> str | None:
        """Cover art url for a Deezer track."""

    @abstractmethod
    def has_login(self) -> bool:
        """A usable ARL cookie is configured."""

    @abstractmethod
    def ensure_login(self) -> None:
        """Have a usable session (ARL present); never interactive."""
