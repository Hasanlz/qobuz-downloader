import httpx
import pytest

from qobuz_downloader.domain import Album, Matched, Quality, Track, Unmatched
from qobuz_downloader.match import LiveSpotify
from qobuz_downloader.match._spotify import Spotify
from qobuz_downloader.match._spotify_urls import parse_spotify
from qobuz_downloader.qobuz import Qobuz


class FakeQobuz(Qobuz):
    def __init__(self, tracks_by_query=None, albums_by_query=None, tracks_by_album=None):
        self.tracks_by_query = tracks_by_query or {}
        self.albums_by_query = albums_by_query or {}
        self.tracks_by_album = tracks_by_album or {}

    def item(self, url):
        raise NotImplementedError

    def tracks(self, item):
        return list(self.tracks_by_album.get(item.id, []))

    def qualities(self, track):
        raise NotImplementedError

    def stream(self, track, quality):
        raise NotImplementedError

    def search_tracks(self, query, limit):
        return list(self.tracks_by_query.get(query, []))[:limit]

    def search_albums(self, query, limit):
        return list(self.albums_by_query.get(query, []))[:limit]


QOBUZ_TRACK = Track(
    id="q1",
    title="Blinding Lights",
    artist="The Weeknd",
    album="After Hours",
    track_number=1,
    duration_seconds=200,
)


def spotify_api(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def make_matcher(qobuz, client):
    api = Spotify("cid", "secret", http=client)
    return LiveSpotify(qobuz, "cid", "secret", api=api)


def test_parse_spotify_urls():
    assert parse_spotify("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT") == (
        "track",
        "4cOdK2wGLETKBW3PvgPWqT",
    )
    assert parse_spotify(
        "https://open.spotify.com/intl-de/album/4yP0hdKOZPNshHUOjyrwCP"
    ) == ("album", "4yP0hdKOZPNshHUOjyrwCP")
    assert parse_spotify(
        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
    ) == ("playlist", "37i9dQZF1DXcBWIGoYBM5M")


def test_parse_spotify_rejects_other_hosts():
    with pytest.raises(ValueError):
        parse_spotify("https://play.qobuz.com/album/qxjbxh1dc3xyb")


def test_track_exact_match():
    def handler(request):
        if "accounts.spotify.com" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(
            200,
            json={
                "id": "s1",
                "name": "Blinding Lights",
                "artists": [{"name": "The Weeknd"}],
                "album": {"name": "After Hours"},
                "duration_ms": 200000,
            },
        )

    qobuz = FakeQobuz(tracks_by_query={"The Weeknd Blinding Lights": [QOBUZ_TRACK]})
    matcher = make_matcher(qobuz, spotify_api(handler))

    result = matcher.match("https://open.spotify.com/track/s1")

    assert isinstance(result, Matched)
    assert result.tracks == [QOBUZ_TRACK]
    assert result.unmatched == []


def test_track_without_candidate_is_unmatched():
    def handler(request):
        if "accounts.spotify.com" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(
            200,
            json={
                "id": "s2",
                "name": "Obscure B-Side",
                "artists": [{"name": "Nobody"}],
                "album": {"name": "Nowhere"},
                "duration_ms": 100000,
            },
        )

    qobuz = FakeQobuz(tracks_by_query={"Nobody Obscure B-Side": []})
    matcher = make_matcher(qobuz, spotify_api(handler))

    result = matcher.match("https://open.spotify.com/track/s2")

    assert isinstance(result, Unmatched)
    assert "Nobody - Obscure B-Side" in result.reason


def test_track_with_dissimilar_title_is_unmatched():
    def handler(request):
        if "accounts.spotify.com" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(
            200,
            json={
                "id": "s3",
                "name": "Completely Different Song",
                "artists": [{"name": "The Weeknd"}],
                "album": {"name": "After Hours"},
                "duration_ms": 200000,
            },
        )

    qobuz = FakeQobuz(
        tracks_by_query={
            "The Weeknd Completely Different Song": [
                Track(
                    id="q9",
                    title="Blinding Lights",
                    artist="The Weeknd",
                    album="After Hours",
                    duration_seconds=200,
                )
            ]
        }
    )
    matcher = make_matcher(qobuz, spotify_api(handler))

    result = matcher.match("https://open.spotify.com/track/s3")

    assert isinstance(result, Unmatched)


def test_album_match_expands_to_tracks():
    qobuz_album = Album(
        id="qa1", title="After Hours", artist="The Weeknd", tracks_count=14
    )
    album_tracks = [QOBUZ_TRACK]

    def handler(request):
        if "accounts.spotify.com" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(
            200,
            json={
                "id": "sa1",
                "name": "After Hours",
                "artists": [{"name": "The Weeknd"}],
                "total_tracks": 14,
            },
        )

    qobuz = FakeQobuz(
        albums_by_query={"The Weeknd After Hours": [qobuz_album]},
        tracks_by_album={"qa1": album_tracks},
    )
    matcher = make_matcher(qobuz, spotify_api(handler))

    result = matcher.match("https://open.spotify.com/album/sa1")

    assert isinstance(result, Matched)
    assert result.tracks == album_tracks


def test_playlist_matches_track_by_track(tmp_path):
    def handler(request):
        if "accounts.spotify.com" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "track": {
                            "id": "s1",
                            "name": "Blinding Lights",
                            "artists": [{"name": "The Weeknd"}],
                            "album": {"name": "After Hours"},
                            "duration_ms": 200000,
                        }
                    },
                    {
                        "track": {
                            "id": "s2",
                            "name": "Unheard Noise",
                            "artists": [{"name": "Ghost Artist"}],
                            "album": {"name": "Void"},
                            "duration_ms": 90000,
                        }
                    },
                ]
            },
        )

    qobuz = FakeQobuz(tracks_by_query={"The Weeknd Blinding Lights": [QOBUZ_TRACK]})
    matcher = make_matcher(qobuz, spotify_api(handler))

    result = matcher.match("https://open.spotify.com/playlist/p1")

    assert isinstance(result, Matched)
    assert [t.id for t in result.tracks] == ["q1"]
    assert len(result.unmatched) == 1
    assert result.unmatched[0].title == "Unheard Noise"


def test_playlist_with_no_matches_is_unmatched():
    def handler(request):
        if "accounts.spotify.com" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(200, json={"items": []})

    matcher = make_matcher(FakeQobuz(), spotify_api(handler))

    result = matcher.match("https://open.spotify.com/playlist/empty")

    assert isinstance(result, Unmatched)
    assert "0 tracks" in result.reason
