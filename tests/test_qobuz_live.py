import httpx
import pytest

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


class _RecordingTransport:
    """MockTransport that records each attempt and yields scripted replies."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.attempts = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        reply = self._replies[min(self.attempts - 1, len(self._replies) - 1)]
        return reply


def make_flaky_qobuz(replies):
    transport = _RecordingTransport(replies)
    qobuz = LiveQobuz(sleep=lambda _: None)
    qobuz._http = httpx.Client(transport=httpx.MockTransport(transport))
    return qobuz, transport


def test_call_retries_transient_http_error():
    """A 400 from Qobuz's degraded search backend is retried, not fatal.

    The run that dropped tracks turned a transient
    "Impossible to connect, please check your Algolia Application Id"
    400 into a permanent "no match".
    """
    qobuz, transport = make_flaky_qobuz(
        [
            httpx.Response(400, json={"error": "Impossible to connect"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    assert qobuz._call("track/search", query="Kanye West Heartless") == {"ok": True}
    assert transport.attempts == 2


def test_call_retries_server_error():
    qobuz, transport = make_flaky_qobuz(
        [
            httpx.Response(503, json={}),
            httpx.Response(502, json={}),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    assert qobuz._call("album/search", query="x") == {"ok": True}
    assert transport.attempts == 3


def test_call_does_not_retry_client_error():
    """A genuinely bad request (404) is a real answer, not a blip."""
    qobuz, transport = make_flaky_qobuz([httpx.Response(404, json={})])

    with pytest.raises(RuntimeError, match="404"):
        qobuz._call("track/get", track_id="nope")
    assert transport.attempts == 1


def test_call_raises_with_status_when_persistently_failing():
    qobuz, transport = make_flaky_qobuz(
        [httpx.Response(400, json={"error": "Algolia down"})]
    )

    with pytest.raises(RuntimeError, match="track/search"):
        qobuz._call("track/search", query="Kanye West Heartless")
    assert transport.attempts == 3


def test_call_retries_transport_error():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    qobuz = LiveQobuz(sleep=lambda _: None)
    qobuz._http = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(RuntimeError):
        qobuz._call("album/get", album_id="1")


def test_call_retries_429_then_gives_up():
    """429 is retried (throttle), still giving up after all attempts."""
    qobuz, transport = make_flaky_qobuz([httpx.Response(429, json={})])

    with pytest.raises(RuntimeError, match="429"):
        qobuz._call("track/search", query="x")
    assert transport.attempts == 3


def test_call_backs_off_between_attempts():
    """Retries spread out instead of hammering an already-degraded API."""
    sleeps = []
    qobuz = LiveQobuz(sleep=sleeps.append)
    qobuz._http = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, json={})
        )
    )

    with pytest.raises(RuntimeError):
        qobuz._call("track/search", query="x")

    assert sleeps == [0.5, 1.0]


def test_call_honours_retry_after_header():
    sleeps = []
    qobuz = LiveQobuz(sleep=sleeps.append)
    qobuz._http = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429, headers={"Retry-After": "3"}, json={})
        )
    )

    with pytest.raises(RuntimeError):
        qobuz._call("track/search", query="x")

    assert sleeps == [3.0, 3.0]
