import pytest

from qobuz_downloader import collect
from qobuz_downloader.domain import Track


class FakeNative:
    def __init__(self, name, tracks, login=True):
        self.name = name
        self._tracks = tracks
        self.calls = []

    def has_login(self):
        return True

    def native_tracks(self, kind, native_id):
        self.calls.append((kind, native_id))
        return list(self._tracks)


def candidate():
    return Track(id="42", title="Song", artist="Artist", album="Album")


# -- URL routing --------------------------------------------------------


def test_tidal_urls_are_native():
    for url in (
        "https://tidal.com/track/233554206",
        "https://listen.tidal.com/album/180042924",
        "https://www.tidal.com/browse/playlist/3f2d9c1a",
    ):
        assert collect.is_native(url), url


def test_deezer_urls_are_native():
    for url in (
        "https://www.deezer.com/track/417538262",
        "https://deezer.com/us/album/142250372",
        "https://link.deezer.com/playlist/1257694562",
    ):
        assert collect.is_native(url), url


def test_qobuz_and_spotify_are_not_native():
    assert not collect.is_native("https://play.qobuz.com/album/0060254746222")
    assert not collect.is_native("https://open.spotify.com/track/abc")


# -- native_tracks ------------------------------------------------------


def test_tidal_track_link_qualifies_ids():
    tidal = FakeNative("tidal", [candidate()])
    tracks = collect.native_tracks(
        "https://tidal.com/track/42", tidal=tidal, deezer=None
    )
    assert tidal.calls == [("track", "42")]
    assert [t.id for t in tracks] == ["tidal:42"]


def test_deezer_playlist_link_qualifies_ids():
    deezer = FakeNative("deezer", [candidate()])
    tracks = collect.native_tracks(
        "https://www.deezer.com/playlist/99", tidal=None, deezer=deezer
    )
    assert deezer.calls == [("playlist", "99")]
    assert [t.id for t in tracks] == ["deezer:42"]


def test_native_link_without_credentials_is_refused():
    with pytest.raises(ValueError, match="Tidal login"):
        collect.native_tracks("https://tidal.com/track/1", tidal=None, deezer=None)
    with pytest.raises(ValueError, match="DEEZER_ARL"):
        collect.native_tracks("https://www.deezer.com/track/1", tidal=None, deezer=None)
