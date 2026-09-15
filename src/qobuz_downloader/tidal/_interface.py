from abc import ABC, abstractmethod

from qobuz_downloader.domain import Quality, Stream, Track


class Tidal(ABC):
    @abstractmethod
    def hires_match_for(self, track: Track) -> str | None:
        """Return the Tidal track id of a HiRes FLAC match, or None."""

    @abstractmethod
    def stream(self, tidal_track_id: str) -> Stream:
        """Resolve a Tidal track id to a downloadable stream."""

    @abstractmethod
    def ensure_login(self) -> None:
        """Have a valid access token, logging in interactively if needed."""

    @abstractmethod
    def has_login(self) -> bool:
        """A usable (cached) login exists, without the interactive flow."""

    @abstractmethod
    def search_tracks(self, query: str, limit: int) -> list[Track]:
        """Search Tidal's catalog (partner token, no login needed)."""

    @abstractmethod
    def qualities(self, tidal_track_id: str) -> list[Quality]:
        """The Quality ladder a Tidal track offers (tags, no login)."""

    @abstractmethod
    def cover_url(self, tidal_track_id: str) -> str | None:
        """Cover art url for a Tidal track."""
