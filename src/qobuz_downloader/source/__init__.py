from qobuz_downloader.source._base import Source, parse, qualify
from qobuz_downloader.source._qobuz import QobuzSource

__all__ = ["Source", "QobuzSource", "parse", "qualify"]


def registry(*adapters) -> dict[str, Source]:
    """Available download platforms keyed by source name."""
    return {adapter.name: adapter for adapter in adapters}

