from abc import ABC, abstractmethod

from qobuz_downloader.domain import Album, Item, Quality, Stream, Track


class Qobuz(ABC):
    @abstractmethod
    def item(self, url: str) -> Item: ...

    @abstractmethod
    def tracks(self, item: Item) -> list[Track]: ...

    @abstractmethod
    def qualities(self, track: Track) -> list[Quality]: ...

    @abstractmethod
    def stream(self, track: Track, quality: Quality) -> Stream: ...

    @abstractmethod
    def search_tracks(self, query: str, limit: int) -> list[Track]: ...

    @abstractmethod
    def search_albums(self, query: str, limit: int) -> list[Album]: ...
