import hashlib
import json

import httpx
import pytest
from Crypto.Cipher import Blowfish

from qobuz_downloader.deezer import LiveDeezer
from qobuz_downloader.deezer.live import _BF_IV, _BF_SECRET, _bf_key
from qobuz_downloader.domain import Quality, Track

ARL = "test-arl-cookie"

# a fake "FLAC": header + padding, encrypted in stripes
PLAIN_HEADER = b"fLaC-rest-of-the-file"


def _bf_encrypt(key: bytes, data: bytes, index: int) -> bytes:
    if index % 3 == 0 and len(data) == 2048:
        return Blowfish.new(key, Blowfish.MODE_CBC, _BF_IV).encrypt(data)
    return data


def _encrypted_media(sng_id: str, payload: bytes) -> bytes:
    key = _bf_key(sng_id)
    padded = payload + b"\x00" * (-len(payload) % 2048)
    return b"".join(
        _bf_encrypt(key, padded[i : i + 2048], i // 2048)
        for i in range(0, len(padded), 2048)
    )


def make_deezer(routes, media_bytes=None, sng_id="417538262"):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "gw-light.php" in url and "getUserData" in url:
            return httpx.Response(
                200,
                json={
                    "results": {
                        "checkForm": "api-token",
                        "USER": {
                            "OPTIONS": {
                                "license_token": "license-token",
                                "web_sound_quality": {
                                    "low": True,
                                    "high": True,
                                    "lossless": True,
                                },
                            }
                        },
                    }
                },
            )
        if "gw-light.php" in url and "song.getData" in url:
            return httpx.Response(
                200,
                json={
                    "results": {
                        "SNG_ID": sng_id,
                        "SNG_TITLE": "Dare You",
                        "FILESIZE_FLAC": 1000,
                        "FILESIZE_MP3_320": 500,
                        "TRACK_TOKEN": "track-token",
                        "ALB_PICTURE": "abc123",
                    }
                },
            )
        if "media.deezer.com/v1/get_url" in url:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "media": [
                                {
                                    "format": "FLAC",
                                    "cipher": {"type": "BF_CBC_STRIPE"},
                                    "sources": [
                                        {
                                            "url": "https://cdnt-stream.dzcdn.net/media/1/x",
                                            "filesize": len(media_bytes or b""),
                                        }
                                    ],
                                }
                            ]
                        }
                    ]
                },
            )
        if "cdnt-stream" in url:
            return httpx.Response(200, content=media_bytes or b"")
        if "api.deezer.com" in url and "/search" in url:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": 417538262,
                            "title": "Dare You",
                            "artist": {"name": "Leprous"},
                            "album": {"title": "Tall Poppy Syndrome"},
                            "duration": 405,
                        }
                    ]
                },
            )
        return httpx.Response(404, text="no route for " + url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return LiveDeezer(arl=ARL, http=client)


TRACK = Track(
    id="deezer:417538262",
    title="Dare You",
    artist="Leprous",
    album="Tall Poppy Syndrome",
    duration_seconds=405,
)


def test_has_login_reflects_arl():
    assert LiveDeezer(arl=ARL).has_login()
    assert not LiveDeezer().has_login()


def test_missing_arl_raises_clear_error():
    deezer = LiveDeezer()
    with pytest.raises(RuntimeError, match="DEEZER_ARL"):
        deezer.ensure_login()


def test_search_tracks_public_api():
    deezer = make_deezer({})
    candidates = deezer.search_tracks("Leprous Dare You", 5)
    assert candidates[0].id == "417538262"
    assert candidates[0].artist == "Leprous"
    assert candidates[0].duration_seconds == 405


def test_qualities_ladder_requires_flac_and_account_rights():
    deezer = make_deezer({})
    assert deezer.qualities("417538262") == [Quality.LOSSY, Quality.CD]


def test_qualities_lossy_only_when_account_lacks_lossless():
    def handler(request):
        if "getUserData" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "results": {
                        "checkForm": "t",
                        "USER": {
                            "OPTIONS": {
                                "license_token": "l",
                                "web_sound_quality": {"high": True},
                            }
                        },
                    }
                },
            )
        return httpx.Response(404)

    class SongDataDeezer(LiveDeezer):
        def _song_data(self, deezer_track_id):
            return {"SNG_ID": "1", "FILESIZE_FLAC": 9, "FILESIZE_MP3_320": 9}

    lossy_only = SongDataDeezer(
        arl=ARL, http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    lossy_only.ensure_login()  # lossless right missing -> only MP3_320 allowed
    assert lossy_only.qualities("417538262") == [Quality.LOSSY]


def test_cover_url_from_album_picture():
    deezer = make_deezer({})
    url = deezer.cover_url("417538262")
    assert url == (
        "https://e-cdns-images.dzcdn.net/images/cover/abc123/1000x1000-000000-80-0-0.jpg"
    )


def test_stream_returns_decrypting_source():
    # payload is block-aligned (as real media is): 3 full blocks
    media = _encrypted_media("417538262", PLAIN_HEADER + b"\x11" * 6123)
    deezer = make_deezer({}, media_bytes=media)
    stream = deezer.stream(TRACK, Quality.CD)
    assert stream.byte_source is not None
    response = stream.byte_source.stream(stream.url, 0)
    data = b"".join(response.chunks)
    assert data == PLAIN_HEADER + b"\x11" * 6123


def test_stream_range_restart_is_clean():
    media = _encrypted_media("417538262", PLAIN_HEADER + b"\x22" * 6123)
    deezer = make_deezer({}, media_bytes=media)
    stream = deezer.stream(TRACK, Quality.CD)
    # a resume attempt must not corrupt: the source answers 200 (no
    # range honored) and the engine restarts from scratch
    response = stream.byte_source.stream(stream.url, 2048)
    assert response.status == 200
    data = b"".join(response.chunks)
    assert data == PLAIN_HEADER + b"\x22" * 6123  # full plaintext, from 0


def test_stream_rejects_unlicensed_format():
    class SongStub(LiveDeezer):
        def _song_data(self, deezer_track_id):
            return {
                "SNG_ID": "1",
                "FILESIZE_MP3_320": 500,
                "TRACK_TOKEN": "t",
            }

    deezer = SongStub(arl=ARL, http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    deezer._allowed = set()  # account with no streaming rights
    deezer._license_token = "l"
    with pytest.raises(RuntimeError, match="cannot stream"):
        deezer.stream(TRACK, Quality.CD)


def test_stream_falls_back_to_320_when_flac_not_licensed():
    requested_formats = []

    def handler(request):
        if "media.deezer.com/v1/get_url" in str(request.url):
            requested_formats.append(request.read())
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "media": [
                                {
                                    "format": "MP3_320",
                                    "cipher": {"type": "BF_CBC_STRIPE"},
                                    "sources": [
                                        {"url": "https://cdnt-stream.dzcdn.net/media/1/x"}
                                    ],
                                }
                            ]
                        }
                    ]
                },
            )
        if "cdnt-stream" in str(request.url):
            return httpx.Response(200, content=b"")
        return httpx.Response(404)

    class SongStub(LiveDeezer):
        def _song_data(self, deezer_track_id):
            return {"SNG_ID": "1", "FILESIZE_MP3_320": 500, "TRACK_TOKEN": "t"}

    deezer = SongStub(arl=ARL, http=httpx.Client(transport=httpx.MockTransport(handler)))
    deezer._allowed = {"MP3_320"}  # no lossless right on the account
    deezer._license_token = "l"
    stream = deezer.stream(TRACK, Quality.CD)
    assert stream.byte_source is not None
    assert b"MP3_320" in requested_formats[0] and b"FLAC" not in requested_formats[0]


def test_bf_key_matches_deemix_derivation():
    # classic derivation: md5(sng_id) hex bytes xor secret
    sng_id = "417538262"
    md5_hex = hashlib.md5(sng_id.encode()).hexdigest().encode()
    expected = bytes(md5_hex[i] ^ md5_hex[i + 16] ^ _BF_SECRET[i] for i in range(16))
    assert _bf_key(sng_id) == expected


def test_get_url_error_surfaces():
    def handler(request):
        if "media.deezer.com/v1/get_url" in str(request.url):
            return httpx.Response(
                200,
                json={"data": [{"errors": [{"code": 2002, "message": "geo"}]}]},
            )
        return httpx.Response(404)

    class SongStub(LiveDeezer):
        def _song_data(self, deezer_track_id):
            return {"SNG_ID": "1", "FILESIZE_FLAC": 9, "TRACK_TOKEN": "t"}

    deezer = SongStub(arl=ARL, http=httpx.Client(transport=httpx.MockTransport(handler)))
    deezer._allowed = {"FLAC", "MP3_320"}
    deezer._license_token = "l"
    with pytest.raises(RuntimeError, match="geo"):
        deezer.stream(TRACK, Quality.CD)


# -- native URLs --------------------------------------------------------


def _public_client(handler):
    return LiveDeezer(arl=ARL, http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_native_track_link():
    def handler(request):
        assert request.url.path == "/track/417538262"
        return httpx.Response(
            200,
            json={
                "id": 417538262,
                "title": "Dare You",
                "artist": {"name": "Leprous"},
                "album": {"title": "Tall Poppy Syndrome"},
                "duration": 405,
            },
        )

    tracks = _public_client(handler).native_tracks("track", "417538262")
    assert [(t.id, t.title) for t in tracks] == [("417538262", "Dare You")]


def test_native_album_link_sets_collection():
    def handler(request):
        if request.url.path == "/album/99":
            return httpx.Response(
                200,
                json={
                    "id": 99,
                    "title": "Album",
                    "nb_tracks": 2,
                    "tracks": {
                        "data": [
                            {"id": 1, "title": "One", "artist": {"name": "A"},
                             "album": {"title": "Album"}, "duration": 60,
                             "track_position": 1},
                            {"id": 2, "title": "Two", "artist": {"name": "A"},
                             "album": {"title": "Album"}, "duration": 60,
                             "track_position": 2},
                        ],
                        "total": 2,
                    },
                },
            )
        return httpx.Response(404)

    tracks = _public_client(handler).native_tracks("album", "99")
    assert [t.track_number for t in tracks] == [1, 2]
    assert [t.collection for t in tracks] == ["Album", "Album"]


def test_native_playlist_pages_until_total():
    def handler(request):
        if request.url.path == "/playlist/77":
            return httpx.Response(
                200,
                json={
                    "id": 77,
                    "title": "Mix",
                    "tracks": {
                        "data": [
                            {"id": 1, "title": "One", "artist": {"name": "A"},
                             "album": {"title": "X"}, "duration": 60}
                        ],
                        "total": 2,
                    },
                },
            )
        if request.url.path == "/playlist/77/tracks":
            assert request.url.params["index"] == "1"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": 2, "title": "Two", "artist": {"name": "A"},
                         "album": {"title": "X"}, "duration": 60}
                    ]
                },
            )
        return httpx.Response(404)

    tracks = _public_client(handler).native_tracks("playlist", "77")
    assert [t.track_number for t in tracks] == [1, 2]
    assert [t.collection for t in tracks] == ["Mix", "Mix"]
