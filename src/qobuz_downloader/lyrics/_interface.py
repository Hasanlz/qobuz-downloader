from abc import ABC, abstractmethod

from qobuz_downloader.domain import Track


class LyricsSource(ABC):
    @abstractmethod
    def lrc(self, track: Track) -> str | None: ...
