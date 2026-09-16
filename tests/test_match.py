import json
from dataclasses import replace

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


def test_remastered_title_matches_plain_qobuz_title():
    """'Hey You - 2011 Remastered Version' must match Qobuz's 'Hey You'.

    The old title gate scored the full strings against each other, so
    release suffixes Spotify appends pushed famous tracks below the
    threshold and they were never queued.
    """
    qobuz_track = Track(
        id="q1",
        title="Hey You",
        artist="Pink Floyd",
        album="The Wall (Remastered 2011 Version)",
        duration_seconds=279,
    )
    client = embed_client(
        {
            "/track/": {
                "id": "s1",
                "name": "Hey You - 2011 Remastered Version",
                "artists": [{"name": "Pink Floyd"}],
                "duration": 278706,
            }
        }
    )
    qobuz = FakeQobuz(tracks_by_query={"Pink Floyd Hey You": [qobuz_track]})
    matcher = make_matcher(qobuz, client)

    result = matcher.match("https://open.spotify.com/track/s1")

    assert isinstance(result, Matched)
    assert result.tracks[0].id == "q1"


def test_remastered_title_retries_search_with_cleaned_query():
    """When the noisy title finds nothing, search again with it stripped.

    'Money - 2011 Remastered Version' makes Qobuz return Wall tracks that
    aren't Money; the cleaned query 'Money' finds the real one.
    """
    wall_track = Track(
        id="q8",
        title="Comfortably Numb",
        artist="Pink Floyd",
        album="The Wall",
        duration_seconds=382,
    )
    money_track = Track(
        id="q9",
        title="Money",
        artist="Pink Floyd",
        album="The Dark Side of the Moon",
        duration_seconds=382,
    )
    client = embed_client(
        {
            "/track/": {
                "id": "s1",
                "name": "Money - 2011 Remastered Version",
                "artists": [{"name": "Pink Floyd"}],
                "duration": 406000,
            }
        }
    )
    qobuz = FakeQobuz(
        tracks_by_query={
            # noisy query returns the wrong Wall track only
            "Pink Floyd Money - 2011 Remastered Version": [wall_track],
            "Pink Floyd Money": [money_track],
        }
    )
    matcher = make_matcher(qobuz, client)

    result = matcher.match("https://open.spotify.com/track/s1")

    assert isinstance(result, Matched)
    assert result.tracks[0].id == "q9"


def test_remastered_in_parentheses_matches_plain_title():
    client = embed_client(
        {
            "/track/": {
                "id": "s1",
                "name": "One (Remastered)",
                "artists": [{"name": "Metallica"}],
                "duration": 444000,
            }
        }
    )
    qobuz_track = Track(
        id="q1",
        title="One",
        artist="Metallica",
        album="...And Justice for All",
        duration_seconds=444,
    )
    qobuz = FakeQobuz(tracks_by_query={"Metallica One": [qobuz_track]})
    matcher = make_matcher(qobuz, client)

    result = matcher.match("https://open.spotify.com/track/s1")

    assert isinstance(result, Matched)
    assert result.tracks[0].id == "q1"


def test_foreign_script_title_does_not_match_other_foreign_titles():
    """Two different Persian titles must not look identical.

    The old _normalize kept only [a-z0-9], so any non-Latin title became an
    empty string, and empty-vs-empty scored as a 100% match. That is how
    'خاکستر' got queued as a completely different song.
    """
    wrong = Track(
        id="q2",
        title="حبيبة الكل",
        artist="Yusor Hamed",
        album="حبيبة الكل",
        duration_seconds=147,
    )
    client = embed_client(
        {
            "/track/": {
                "id": "s1",
                "name": "خاکستر",
                "artists": [{"name": "Hamed Mohammadi"}],
                "duration": 284000,
            }
        }
    )
    qobuz = FakeQobuz(tracks_by_query={"Hamed Mohammadi خاکستر": [wrong]})
    matcher = make_matcher(qobuz, client)

    result = matcher.match("https://open.spotify.com/track/s1")

    assert isinstance(result, Unmatched)


def test_foreign_script_title_matches_identical_title():
    right = Track(
        id="q3",
        title="خاکستر",
        artist="Hamed Mohammadi",
        album="خاکستر",
        duration_seconds=284,
    )
    client = embed_client(
        {
            "/track/": {
                "id": "s1",
                "name": "خاکستر",
                "artists": [{"name": "Hamed Mohammadi"}],
                "duration": 284000,
            }
        }
    )
    qobuz = FakeQobuz(tracks_by_query={"Hamed Mohammadi خاکستر": [right]})
    matcher = make_matcher(qobuz, client)

    result = matcher.match("https://open.spotify.com/track/s1")

    assert isinstance(result, Matched)
    assert result.tracks[0].id == "q3"


def test_soundtrack_attribution_is_stripped_from_title():
    client = embed_client(
        {
            "/track/": {
                "id": "s1",
                "name": 'I Know You - From The "Fifty Shades Of Grey" Soundtrack',
                "artists": [{"name": "Skylar Grey"}],
                "duration": 225000,
            }
        }
    )
    qobuz_track = Track(
        id="q1",
        title="I Know You",
        artist="Skylar Grey",
        album="Fifty Shades of Grey",
        duration_seconds=225,
    )
    qobuz = FakeQobuz(tracks_by_query={"Skylar Grey I Know You": [qobuz_track]})
    matcher = make_matcher(qobuz, client)

    result = matcher.match("https://open.spotify.com/track/s1")

    assert isinstance(result, Matched)
    assert result.tracks[0].id == "q1"


def test_track_found_via_album_when_search_misses():
    """Track search can surface only covers; the album holds the original.

    'Under Your Scars' on Qobuz: search returns covers/live versions, but
    the studio track sits on the album 'When Legends Rise'. Playlist
    payloads carry the album name, so the fallback can use it.
    """
    studio = Track(
        id="q1",
        title="Under Your Scars",
        artist="Godsmack",
        album="When Legends Rise",
        track_number=6,
        duration_seconds=231,
    )
    qobuz = FakeQobuz(tracks_by_query={"Godsmack Under Your Scars": []})
    qobuz.albums_by_query = {
        "Godsmack When Legends Rise": [
            Album(id="qa1", title="When Legends Rise", artist="Godsmack", tracks_count=11)
        ]
    }
    qobuz.tracks_by_album = {"qa1": [studio]}
    matcher = LiveSpotify(qobuz, api=EmbedSpotify(http=embed_client({})))

    wanted = Track(
        id="spotify:s1",
        title="Under Your Scars",
        artist="Godsmack",
        album="When Legends Rise",
        duration_seconds=231,
    )

    best = matcher._best_track(wanted)

    assert best is not None
    assert best.id == "q1"


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


class FlakySearchQobuz(FakeQobuz):
    """Raises on one poison query, like Qobuz's search backend does."""

    def __init__(self, failing_query, **kwargs):
        super().__init__(**kwargs)
        self.failing_query = failing_query

    def search_tracks(self, query, limit):
        if query == self.failing_query:
            raise httpx.HTTPStatusError(
                "400 Bad Request",
                request=httpx.Request("GET", "https://www.qobuz.com/api.json/0.2/track/search"),
                response=httpx.Response(400),
            )
        return super().search_tracks(query, limit)


def test_playlist_survives_search_error_on_one_track():
    client = embed_client(
        {
            "/playlist/": {
                "name": "Mix",
                "trackList": [
                    {
                        "uri": "spotify:track:s1",
                        "title": "Heartless",
                        "subtitle": "Kanye West",
                        "duration": 200000,
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
    qobuz = FlakySearchQobuz(
        "Kanye West Heartless",
        tracks_by_query={"The Weeknd Blinding Lights": [QOBUZ_TRACK]},
    )
    matcher = make_matcher(qobuz, client)

    result = matcher.match("https://open.spotify.com/playlist/p1")

    assert isinstance(result, Matched)
    assert [t.id for t in result.tracks] == ["q1"]
    assert len(result.unmatched) == 1
    assert result.unmatched[0].title == "Heartless"
    # ...and the miss is marked retryable, not as a clean catalog miss
    assert "search error" in result.unmatched[0].reason


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


class SelectivelyFailingQobuz(FakeQobuz):
    """Every search for the poison artist fails; others resolve."""

    def __init__(self, poison_artist, **kwargs):
        super().__init__(**kwargs)
        self.poison_artist = poison_artist

    def search_tracks(self, query, limit):
        if query.startswith(self.poison_artist):
            raise RuntimeError(
                "track/search failed after 3 attempts (last HTTP 400): Algolia down"
            )
        return super().search_tracks(query, limit)

    def search_albums(self, query, limit):
        if query.startswith(self.poison_artist):
            raise RuntimeError(
                "album/search failed after 3 attempts (last HTTP 400): Algolia down"
            )
        return super().search_albums(query, limit)


def test_persistent_search_error_is_reported_not_a_clean_miss():
    """A backend outage must read as retryable, not as 'not on Qobuz'.

    The original run turned a transient Algolia 400 into "no Qobuz +
    Deezer match", which is indistinguishable from a real catalog miss
    and so was never retried. The reason must say "search error".
    """
    client = embed_client(
        {
            "/playlist/": {
                "name": "Mix",
                "trackList": [
                    {
                        "uri": "spotify:track:s1",
                        "title": "My Heart Is Broken",
                        "subtitle": "Evanescence",
                        "duration": 200000,
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
    qobuz = SelectivelyFailingQobuz(
        "Evanescence",
        tracks_by_query={"The Weeknd Blinding Lights": [QOBUZ_TRACK]},
    )
    matcher = make_matcher(qobuz, client)

    result = matcher.match("https://open.spotify.com/playlist/p1")

    assert isinstance(result, Matched)
    assert [t.id for t in result.tracks] == ["q1"]
    assert len(result.unmatched) == 1
    assert "search error" in result.unmatched[0].reason


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


class FakeTidalSource:
    """Source-shaped stand-in for the catalog's tidal entry."""

    name = "tidal"

    def __init__(self, candidates):
        self._candidates = list(candidates)

    def search_tracks(self, query, limit):
        return list(self._candidates)

    def qualities(self, track):
        from qobuz_downloader.domain import Quality

        return [Quality.LOSSY, Quality.CD]

    def stream(self, track, quality):
        raise NotImplementedError

    def cover_url(self, track):
        return None


TIDAL_TRACK = Track(
    id="t1",
    title="Ashfall",
    artist="Hamed Mohammadi",
    album="Ashfall",
    track_number=1,
    duration_seconds=200,
)


def make_catalog_matcher(qobuz, client, sources):
    from qobuz_downloader.match._catalog import Catalog
    from qobuz_downloader.source import QobuzSource

    matcher = make_matcher(qobuz, client)
    matcher._catalog = Catalog([QobuzSource(qobuz), *sources])
    return matcher


def test_tidal_fallback_rescues_qobuz_missing_playlist_track():
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
                        "title": "Ashfall",
                        "subtitle": "Hamed Mohammadi",
                        "duration": 200000,
                    },
                ],
            }
        }
    )
    qobuz = FakeQobuz(tracks_by_query={"The Weeknd Blinding Lights": [QOBUZ_TRACK]})
    matcher = make_catalog_matcher(
        qobuz,
        client,
        [FakeTidalSource([replace(TIDAL_TRACK, id="t9")])],
    )

    result = matcher.match("https://open.spotify.com/playlist/p1")

    assert isinstance(result, Matched)
    assert [t.id for t in result.tracks] == ["q1", "tidal:t9"]
    assert result.unmatched == []


def test_tidal_fallback_track_keeps_playlist_position():
    client = embed_client(
        {
            "/playlist/": {
                "name": "Mix",
                "trackList": [
                    {
                        "uri": "spotify:track:s2",
                        "title": "Ashfall",
                        "subtitle": "Hamed Mohammadi",
                        "duration": 200000,
                    },
                ],
            }
        }
    )
    qobuz = FakeQobuz()
    matcher = make_catalog_matcher(
        qobuz, client, [FakeTidalSource([replace(TIDAL_TRACK, id="t9")])]
    )

    result = matcher.match("https://open.spotify.com/playlist/p1")

    assert isinstance(result, Matched)
    assert result.tracks[0].track_number == 1
    assert result.tracks[0].id == "tidal:t9"


def test_no_fallback_source_match_leaves_track_unmatched():
    client = embed_client(
        {
            "/playlist/": {
                "name": "Mix",
                "trackList": [
                    {
                        "uri": "spotify:track:s2",
                        "title": "Ashfall",
                        "subtitle": "Hamed Mohammadi",
                        "duration": 200000,
                    },
                ],
            }
        }
    )
    qobuz = FakeQobuz()
    matcher = make_catalog_matcher(qobuz, client, [FakeTidalSource([])])

    result = matcher.match("https://open.spotify.com/playlist/p1")

    assert isinstance(result, Unmatched)
    assert "none of 1 tracks matched" in result.reason


def test_qobuz_outage_falls_through_to_tidal():
    """Qobuz's search backend being down must not lose a Tidal track."""
    client = embed_client(
        {
            "/playlist/": {
                "name": "Mix",
                "trackList": [
                    {
                        "uri": "spotify:track:s2",
                        "title": "Ashfall",
                        "subtitle": "Hamed Mohammadi",
                        "duration": 200000,
                    },
                ],
            }
        }
    )
    qobuz = SelectivelyFailingQobuz("Hamed Mohammadi")
    matcher = make_catalog_matcher(
        qobuz, client, [FakeTidalSource([replace(TIDAL_TRACK, id="t9")])]
    )

    result = matcher.match("https://open.spotify.com/playlist/p1")

    assert isinstance(result, Matched)
    assert [t.id for t in result.tracks] == ["tidal:t9"]
    assert result.unmatched == []


def test_qobuz_outage_with_no_fallback_reports_search_error():
    """Nothing carries it and Qobuz errored: retryable, not a clean miss."""
    client = embed_client(
        {
            "/playlist/": {
                "name": "Mix",
                "trackList": [
                    {
                        "uri": "spotify:track:s1",
                        "title": "Ashfall",
                        "subtitle": "Hamed Mohammadi",
                        "duration": 200000,
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
    qobuz = SelectivelyFailingQobuz(
        "Hamed Mohammadi",
        tracks_by_query={"The Weeknd Blinding Lights": [QOBUZ_TRACK]},
    )
    matcher = make_catalog_matcher(qobuz, client, [FakeTidalSource([])])

    result = matcher.match("https://open.spotify.com/playlist/p1")

    assert isinstance(result, Matched)
    assert [t.id for t in result.tracks] == ["q1"]
    assert len(result.unmatched) == 1
    assert "search error" in result.unmatched[0].reason
