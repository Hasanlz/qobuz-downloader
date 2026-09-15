"""Native URL routing for the platforms that own their own catalog.

Spotify links carry no audio and Qobuz links route through the Qobuz
client directly (as they always have); a link from a platform that IS
a catalog — Tidal, Deezer — names tracks in that catalog's own ids and
is collected without any Match. The platform must be downloadable for
that: Tidal needs its cached login, Deezer needs DEEZER_ARL — the
caller passes the credentialed client or None, and a link for a
platform without credentials is refused with a clear message instead
of queueing tracks that would only fail at download time.
"""

import re
from dataclasses import replace

from qobuz_downloader.domain import Track
from qobuz_downloader.source import qualify

_TIDAL = re.compile(
    r"https?://(?:www\.|listen\.)?tidal\.com/(?:browse/)?"
    r"(?P<kind>track|album|playlist)/(?P<id>[A-Za-z0-9-]+)",
    re.IGNORECASE,
)
_DEEZER = re.compile(
    r"https?://(?:www\.|link\.)?deezer\.com/(?:[a-z]{2}/)?"
    r"(?P<kind>track|album|playlist)/(?P<id>\d+)",
    re.IGNORECASE,
)

_NEEDS = {
    "tidal": "needs a Tidal login — run once with --tidal to sign in",
    "deezer": "needs the DEEZER_ARL environment variable set to your ARL cookie",
}


def is_native(url: str) -> bool:
    """True for Tidal/Deezer links (the hosts collected without matching)."""
    return bool(_TIDAL.match(url) or _DEEZER.match(url))


def native_tracks(
    url: str, *, tidal=None, deezer=None
) -> list[Track]:
    """Tracks behind a Tidal or Deezer URL, ids qualified for the queue.

    The wrapped client's ``native_tracks(kind, native_id)`` does the
    fetching; the returned ids get their source prefix ("tidal:233554")
    so the engine can dispatch the download. A client counts as
    available only when it can actually stream (Tidal's login cached,
    Deezer's ARL set) — otherwise the link is refused with the same
    clear message the engine would only find at download time.
    """
    for platform, pattern, client in (
        ("tidal", _TIDAL, tidal),
        ("deezer", _DEEZER, deezer),
    ):
        match = pattern.match(url)
        if not match:
            continue
        if client is None or not client.has_login():
            raise ValueError(f"{platform} URL given but {platform} {_NEEDS[platform]}")
        tracks = client.native_tracks(match["kind"], match["id"])
        return [replace(track, id=qualify(platform, track.id)) for track in tracks]
    raise ValueError(f"unsupported URL: {url}")
