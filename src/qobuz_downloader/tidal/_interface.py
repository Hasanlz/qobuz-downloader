from abc import ABC, abstractmethod

from qobuz_downloader.domain import Stream, Track


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
