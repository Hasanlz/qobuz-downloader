import json

import httpx
import pytest

from qobuz_downloader.domain import Album, Matched, Track, Unmatched
from qobuz_downloader.match import LiveSpotify
from qobuz_downloader.match._spotify import EmbedSpotify
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

    def cover_url(self, track):
        return None


QOBUZ_TRACK = Track(
    id="q1",
    title="Blinding Lights",
    artist="The Weeknd",
    album="After Hours",
    track_number=1,
    duration_seconds=200,
)


def embed_html(entity):
    payload = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}</script></html>"
    )


def embed_client(routes):
    def handler(request):
        for fragment, entity in routes.items():
            if fragment in str(request.url):
                return httpx.Response(200, text=embed_html(entity))
        return httpx.Response(404, text="not found")

    return httpx.Client(transport=httpx.MockTransport(handler))


def make_matcher(qobuz, client):
    return LiveSpotify(qobuz, api=EmbedSpotify(http=client))


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
    client = embed_client(
        {
            "/track/": {
                "id": "s1",
                "name": "Blinding Lights",
                "artists": [{"name": "The Weeknd"}],
                "duration": 200000,
            }
        }
    )
    qobuz = FakeQobuz(tracks_by_query={"The Weeknd Blinding Lights": [QOBUZ_TRACK]})
    matcher = make_matcher(qobuz, client)

    result = matcher.match("https://open.spotify.com/track/s1")

    assert isinstance(result, Matched)
    assert result.tracks == [QOBUZ_TRACK]
    assert result.unmatched == []


def test_track_without_candidate_is_unmatched():
    client = embed_client(
        {
            "/track/": {
                "id": "s2",
                "name": "Obscure B-Side",
                "artists": [{"name": "Nobody"}],
                "duration": 100000,
            }
        }
    )
    qobuz = FakeQobuz(tracks_by_query={"Nobody Obscure B-Side": []})
    matcher = make_matcher(qobuz, client)

    result = matcher.match("https://open.spotify.com/track/s2")

    assert isinstance(result, Unmatched)
    assert "Nobody - Obscure B-Side" in result.reason


def test_track_with_dissimilar_title_is_unmatched():
    client = embed_client(
        {
            "/track/": {
                "id": "s3",
                "name": "Completely Different Song",
                "artists": [{"name": "The Weeknd"}],
                "duration": 200000,
            }
        }
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
    matcher = make_matcher(qobuz, client)

    result = matcher.match("https://open.spotify.com/track/s3")

    assert isinstance(result, Unmatched)


def test_album_match_expands_to_tracks():
    qobuz_album = Album(
        id="qa1", title="After Hours", artist="The Weeknd", tracks_count=2
    )
    album_tracks = [QOBUZ_TRACK]
    client = embed_client(
        {
            "/album/": {
                "name": "After Hours",
                "artists": [],
                "trackList": [
                    {
                        "uri": "spotify:track:t1",
                        "title": "Alone Again",
                        "subtitle": "The Weeknd",
                        "duration": 250000,
                    },
                    {
                        "uri": "spotify:track:t2",
                        "title": "Blinding Lights",
                        "subtitle": "The Weeknd",
                        "duration": 200000,
                    },
                ],
            }
        }
    )
    qobuz = FakeQobuz(
        albums_by_query={"The Weeknd After Hours": [qobuz_album]},
        tracks_by_album={"qa1": album_tracks},
    )
    matcher = make_matcher(qobuz, client)

    result = matcher.match("https://open.spotify.com/album/sa1")

    assert isinstance(result, Matched)
    assert [t.id for t in result.tracks] == ["q1"]
    assert [t.collection for t in result.tracks] == ["After Hours"]


def test_playlist_matches_track_by_track():
    client = embed_client(
        {
            "/playlist/": {
                "name": "Mix",
                "trackList": [
                    {
                        "uri": "spotify:track:s1",
                        "title": "Blinding Lights",
                        "subtitle": "The Weeknd",
                        "duration": 200000,
                    },
                    {
                        "uri": "spotify:track:s2",
                        "title": "Unheard Noise",
                        "subtitle": "Ghost Artist",
                        "duration": 90000,
                    },
                ],
            }
        }
    )
    qobuz = FakeQobuz(tracks_by_query={"The Weeknd Blinding Lights": [QOBUZ_TRACK]})
    matcher = make_matcher(qobuz, client)

    result = matcher.match("https://open.spotify.com/playlist/p1")

    assert isinstance(result, Matched)
    assert [t.id for t in result.tracks] == ["q1"]
    assert len(result.unmatched) == 1
    assert result.unmatched[0].title == "Unheard Noise"


def test_playlist_numbers_tracks_by_position():
    client = embed_client(
        {
            "/playlist/": {
                "name": "Mix",
                "trackList": [
                    {
                        "uri": "spotify:track:s1",
                        "title": "Blinding Lights",
                        "subtitle": "The Weeknd",
                        "duration": 200000,
                    },
                    {
                        "uri": "spotify:track:s2",
                        "title": "Another Hit",
                        "subtitle": "The Weeknd",
                        "duration": 210000,
                    },
                ],
            }
        }
    )
    qobuz = FakeQobuz(
        tracks_by_query={
            "The Weeknd Blinding Lights": [
                Track(
                    id="q1",
                    title="Blinding Lights",
                    artist="The Weeknd",
                    album="After Hours",
                    track_number=1,
                    duration_seconds=200,
                )
            ],
            "The Weeknd Another Hit": [
                Track(
                    id="q2",
                    title="Another Hit",
                    artist="The Weeknd",
                    album="Starboy",
                    track_number=7,
                    duration_seconds=210,
                )
            ],
        }
    )
    matcher = make_matcher(qobuz, client)

    result = matcher.match("https://open.spotify.com/playlist/p1")

    assert isinstance(result, Matched)
    assert [t.track_number for t in result.tracks] == [1, 2]
    assert [t.collection for t in result.tracks] == ["Mix", "Mix"]
    assert [t.track_total for t in result.tracks] == [2, 2]
    # album names stay untouched
    assert [t.album for t in result.tracks] == ["After Hours", "Starboy"]


def test_playlist_track_total_counts_unmatched_tracks_too():
    client = embed_client(
        {
            "/playlist/": {
                "name": "Mix",
                "trackList": [
                    {
                        "uri": "spotify:track:s1",
                        "title": "Blinding Lights",
                        "subtitle": "The Weeknd",
                        "duration": 200000,
                    },
                    {
                        "uri": "spotify:track:s2",
                        "title": "Unheard Noise",
                        "subtitle": "Ghost Artist",
                        "duration": 90000,
                    },
                ],
            }
        }
    )
    qobuz = FakeQobuz(tracks_by_query={"The Weeknd Blinding Lights": [QOBUZ_TRACK]})
    matcher = make_matcher(qobuz, client)

    result = matcher.match("https://open.spotify.com/playlist/p1")

    assert isinstance(result, Matched)
    # total is the playlist size, not the matched count
    assert [t.track_total for t in result.tracks] == [2]


def test_playlist_unmatched_track_does_not_shift_positions():
    client = embed_client(
        {
            "/playlist/": {
                "name": "Mix",
                "trackList": [
                    {
                        "uri": "spotify:track:s1",
                        "title": "Obscure One",
                        "subtitle": "Nobody",
                        "duration": 100000,
                    },
                    {
                        "uri": "spotify:track:s2",
                        "title": "Blinding Lights",
                        "subtitle": "The Weeknd",
                        "duration": 200000,
                    },
                ],
            }
        }
    )
    qobuz = FakeQobuz(tracks_by_query={"The Weeknd Blinding Lights": [QOBUZ_TRACK]})
    matcher = make_matcher(qobuz, client)

    result = matcher.match("https://open.spotify.com/playlist/p1")

    assert isinstance(result, Matched)
    assert [t.track_number for t in result.tracks] == [2]


def test_playlist_with_no_matches_is_unmatched():
    client = embed_client({"/playlist/": {"name": "Empty", "trackList": []}})
    matcher = make_matcher(FakeQobuz(), client)

    result = matcher.match("https://open.spotify.com/playlist/empty")

    assert isinstance(result, Unmatched)
    assert "0 tracks" in result.reason


def test_public_spotify_extracts_playlist_tracks():
    from qobuz_downloader.match._public import PublicSpotify

    class FakePublic:
        @staticmethod
        def playlist_info(playlist_id):
            yield {
                "items": [
                    {
                        "itemV2": {
                            "data": {
                                "__typename": "Track",
                                "uri": "spotify:track:aaa1111111111111111111",
                                "name": "Billie Jean",
                                "trackDuration": {"totalMilliseconds": 293802},
                                "artists": {
                                    "items": [
                                        {
                                            "profile": {
                                                "name": "Michael Jackson"
                                            }
                                        }
                                    ]
                                },
                                "albumOfTrack": {"name": "Thriller"},
                            }
                        }
                    },
                    {"itemV2": {"data": {"__typename": "Intro", "uri": "x"}}},
                ]
            }

    adapter = PublicSpotify.__new__(PublicSpotify)
    adapter._public = FakePublic

    tracks = adapter.playlist_tracks("p1")

    assert len(tracks) == 1
    assert tracks[0]["name"] == "Billie Jean"
    assert tracks[0]["artists"] == [{"name": "Michael Jackson"}]
    assert tracks[0]["duration_ms"] == 293802


def test_embed_spotify_maps_track_payload():
    client = embed_client(
        {
            "/track/": {
                "id": "s1",
                "name": "Blinding Lights",
                "artists": [{"name": "The Weeknd"}],
                "duration": 200000,
            }
        }
    )
    embed = EmbedSpotify(http=client)

    payload = embed.track("s1")

    assert payload["id"] == "s1"
    assert payload["name"] == "Blinding Lights"
    assert payload["duration_ms"] == 200000
    assert payload["artists"] == [{"name": "The Weeknd"}]


def test_embed_spotify_takes_album_artist_from_first_track():
    client = embed_client(
        {
            "/album/": {
                "name": "After Hours",
                "artists": [],
                "trackList": [
                    {
                        "uri": "spotify:track:t1",
                        "title": "Alone Again",
                        "subtitle": "The Weeknd",
                        "duration": 250000,
                    }
                ],
            }
        }
    )
    embed = EmbedSpotify(http=client)

    payload = embed.album("sa1")

    assert payload["name"] == "After Hours"
    assert payload["artists"] == [{"name": "The Weeknd"}]
    assert payload["total_tracks"] == 1


def test_embed_spotify_raises_on_missing_entity():
    payload = {"props": {"pageProps": {"status": 404, "state": None}}}
    html = (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}</script></html>"
    )
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html))
    )
    embed = EmbedSpotify(http=client)

    with pytest.raises(RuntimeError):
        embed.track("missing")


def test_embed_spotify_playlist_name():
    client = embed_client(
        {"/playlist/": {"name": "Today's Top Hits", "trackList": []}}
    )
    embed = EmbedSpotify(http=client)

    assert embed.playlist_name("p1") == "Today's Top Hits"


def test_playlist_with_no_matches_is_unmatched_keeps_position_stamping():
    client = embed_client(
        {
            "/playlist/": {
                "name": "Named Mix",
                "trackList": [
                    {
                        "uri": "spotify:track:s1",
                        "title": "Blinding Lights",
                        "subtitle": "The Weeknd",
                        "duration": 200000,
                    },
                    {
                        "uri": "spotify:track:s2",
                        "title": "Obscure One",
                        "subtitle": "Nobody",
                        "duration": 100000,
                    },
                ],
            }
        }
    )
    qobuz = FakeQobuz(tracks_by_query={"The Weeknd Blinding Lights": [QOBUZ_TRACK]})
    matcher = make_matcher(qobuz, client)

    result = matcher.match("https://open.spotify.com/playlist/p1")

    assert isinstance(result, Matched)
    assert result.tracks[0].collection == "Named Mix"
