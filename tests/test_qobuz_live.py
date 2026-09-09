import httpx

from qobuz_downloader.qobuz import LiveQobuz

_TRACK_PAYLOADS = [
    {
        "id": 9001,
        "title": "Highway Star",
        "track_number": 6,
        "duration": 368,
        "album": {"id": 42, "title": "Machine Head", "artist": {"name": "Deep Purple"}},
    },
    {
        "id": 9002,
        "title": "Smoke on the Water",
        "track_number": 4,
        "duration": 342,
        "album": {"id": 42, "title": "Machine Head", "artist": {"name": "Deep Purple"}},
    },
]

_ALBUM_PAYLOAD = {
    "id": 42,
    "title": "Machine Head",
    "artist": {"name": "Deep Purple"},
    "tracks": {"items": _TRACK_PAYLOADS},
}

_PLAYLIST_PAYLOAD = {
    "id": 77,
    "name": "Classic Rock Roadtrip",
    "tracks_count": 2,
    "tracks": {"items": _TRACK_PAYLOADS},
}


def _routes(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("playlist/get"):
        return httpx.Response(200, json=_PLAYLIST_PAYLOAD)
    if request.url.path.endswith("album/get"):
        return httpx.Response(200, json=_ALBUM_PAYLOAD)
    if request.url.path.endswith("track/get"):
        return httpx.Response(200, json=_TRACK_PAYLOADS[0])
    return httpx.Response(404, json={})


def make_qobuz() -> LiveQobuz:
    qobuz = LiveQobuz()
    qobuz._http = httpx.Client(transport=httpx.MockTransport(_routes))
    return qobuz


def test_playlist_tracks_are_numbered_by_position():
    qobuz = make_qobuz()

    tracks = qobuz.tracks(qobuz.item("https://play.qobuz.com/playlist/77"))

    assert [t.track_number for t in tracks] == [1, 2]
    assert [t.album for t in tracks] == ["Machine Head", "Machine Head"]
    assert [t.track_total for t in tracks] == [2, 2]


def test_playlist_tracks_carry_playlist_name_as_collection():
    qobuz = make_qobuz()

    tracks = qobuz.tracks(qobuz.item("https://play.qobuz.com/playlist/77"))

    assert {t.collection for t in tracks} == {"Classic Rock Roadtrip"}


def test_album_tracks_keep_album_numbers():
    qobuz = make_qobuz()

    tracks = qobuz.tracks(qobuz.item("https://play.qobuz.com/album/42"))

    assert [t.track_number for t in tracks] == [6, 4]
    assert {t.collection for t in tracks} == {"Machine Head"}
    assert [t.track_total for t in tracks] == [2, 2]


def test_single_track_has_no_collection():
    qobuz = make_qobuz()

    tracks = qobuz.tracks(qobuz.item("https://open.qobuz.com/track/9001"))

    assert len(tracks) == 1
    assert tracks[0].collection is None
    assert tracks[0].track_number == 6
