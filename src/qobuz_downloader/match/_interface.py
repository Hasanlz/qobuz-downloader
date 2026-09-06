from abc import ABC, abstractmethod

from qobuz_downloader.domain import MatchResult


class Matcher(ABC):
    @abstractmethod
    def match(self, url: str) -> MatchResult: ...
