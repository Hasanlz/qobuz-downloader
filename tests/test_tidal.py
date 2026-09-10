import base64
import json
import time
import urllib.parse

import httpx

from qobuz_downloader.domain import Track
from qobuz_downloader.tidal import LiveTidal

TRACK = Track(
    id="q1",
    title="Night Crawling",
    artist="Miley Cyrus",
    album="Plastic Hearts",
    duration_seconds=189,
)


def _search_payload(items):
    return {"tracks": {"items": items, "totalNumberOfItems": len(items)}}


def make_tidal(routes, cache, sleep=lambda seconds: None) -> LiveTidal:
    http = httpx.Client(transport=httpx.MockTransport(routes))
    return LiveTidal(http=http, cache=cache, sleep=sleep)


def test_hires_match_prefers_tagged_candidate(tmp_path):
    def routes(request):
        assert request.url.params["query"] == "Miley Cyrus Night Crawling"
        return httpx.Response(
            200,
            json=_search_payload(
                [
                    {
                        "id": 1,
                        "title": "Night Crawling",
                        "duration": 189,
                        "artists": [{"name": "Miley Cyrus"}],
                        "mediaMetadata": {"tags": ["LOSSLESS"]},
                    },
                    {
                        "id": 2,
                        "title": "Night Crawling (feat. Billy Idol)",
                        "duration": 189,
                        "artists": [{"name": "Miley Cyrus"}],
                        "mediaMetadata": {"tags": ["LOSSLESS", "HIRES_LOSSLESS"]},
                    },
                ]
            ),
        )

    tidal = make_tidal(routes, tmp_path / "tidal.json")

    assert tidal.hires_match_for(TRACK) == "2"


def test_hires_match_returns_none_without_hires_tag(tmp_path):
    def routes(request):
        return httpx.Response(
            200,
            json=_search_payload(
                [
                    {
                        "id": 1,
                        "title": "Night Crawling",
                        "duration": 189,
                        "artists": [{"name": "Miley Cyrus"}],
                        "mediaMetadata": {"tags": ["LOSSLESS"]},
                    }
                ]
            ),
        )

    tidal = make_tidal(routes, tmp_path / "tidal.json")

    assert tidal.hires_match_for(TRACK) is None


def test_hires_match_returns_none_for_dissimilar_song(tmp_path):
    def routes(request):
        return httpx.Response(
            200,
            json=_search_payload(
                [
                    {
                        "id": 1,
                        "title": "Completely Different Song",
                        "duration": 12,
                        "artists": [{"name": "Nobody"}],
                        "mediaMetadata": {"tags": ["LOSSLESS", "HIRES_LOSSLESS"]},
                    }
                ]
            ),
        )

    tidal = make_tidal(routes, tmp_path / "tidal.json")

    assert tidal.hires_match_for(TRACK) is None


def test_device_login_polls_until_approved(tmp_path):
    calls = {"device": 0, "token": 0}

    def routes(request):
        if request.url.path.endswith("/device_authorization"):
            calls["device"] += 1
            return httpx.Response(
                200,
                json={
                    "deviceCode": "dc",
                    "userCode": "AB12",
                    "verificationUriComplete": "link.tidal.com/AB12",
                    "expiresIn": 300,
                    "interval": 2,
                },
            )
        if request.url.path.endswith("/token"):
            calls["token"] += 1
            if calls["token"] == 1:
                return httpx.Response(400, json={"status": 400, "sub_status": 1002})
            assert request.headers["Authorization"].startswith("Basic ")
            body = urllib.parse.parse_qs(request.content.decode())
            assert body["grant_type"] == ["urn:ietf:params:oauth:grant-type:device_code"]
            assert body["device_code"] == ["dc"]
            return httpx.Response(
                200,
                json={
                    "access_token": "at",
                    "refresh_token": "rt",
                    "expires_in": 604800,
                    "user": {"userId": 7, "countryCode": "DE"},
                },
            )
        return httpx.Response(404)

    tidal = make_tidal(routes, tmp_path / "tidal.json")

    tidal.ensure_login()

    assert tidal._access_token == "at"
    assert tidal._country == "DE"
    saved = json.loads((tmp_path / "tidal.json").read_text(encoding="utf-8"))
    assert saved["access_token"] == "at"
    assert saved["refresh_token"] == "rt"
    # a second call with a fresh token makes no further requests
    tidal.ensure_login()
    assert calls["token"] == 2


def test_login_times_out_when_never_approved(tmp_path):
    def routes(request):
        if request.url.path.endswith("/device_authorization"):
            return httpx.Response(
                200,
                json={
                    "deviceCode": "dc",
                    "userCode": "AB12",
                    "verificationUriComplete": "link.tidal.com/AB12",
                    "expiresIn": 4,
                    "interval": 2,
                },
            )
        if request.url.path.endswith("/token"):
            return httpx.Response(400, json={"status": 400, "sub_status": 1002})
        return httpx.Response(404)

    tidal = make_tidal(routes, tmp_path / "tidal.json")

    try:
        tidal.ensure_login()
        raised = False
    except RuntimeError as error:
        raised = "timed out" in str(error)
    assert raised


def test_refreshes_token_close_to_expiry(tmp_path):
    cache = tmp_path / "tidal.json"
    cache.write_text(
        json.dumps(
            {
                "access_token": "old",
                "refresh_token": "rt",
                "expires_at": time.time() + 100,
                "country_code": "US",
            }
        ),
        encoding="utf-8",
    )

    def routes(request):
        body = urllib.parse.parse_qs(request.content.decode())
        assert body["grant_type"] == ["refresh_token"]
        assert body["refresh_token"] == ["rt"]
        assert request.headers["Authorization"].startswith("Basic ")
        return httpx.Response(200, json={"access_token": "new", "expires_in": 604800})

    tidal = make_tidal(routes, cache)

    tidal.ensure_login()

    assert tidal._access_token == "new"
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert saved["access_token"] == "new"


def test_fresh_cached_token_makes_no_requests(tmp_path):
    cache = tmp_path / "tidal.json"
    cache.write_text(
        json.dumps(
            {
                "access_token": "at",
                "refresh_token": "rt",
                "expires_at": time.time() + 7 * 86400,
                "country_code": "US",
            }
        ),
        encoding="utf-8",
    )

    def routes(request):
        raise AssertionError("no HTTP expected")

    tidal = make_tidal(routes, cache)

    tidal.ensure_login()

    assert tidal._access_token == "at"


def _bts(manifest: dict) -> dict:
    encoded = base64.b64encode(json.dumps(manifest).encode()).decode()
    return {"manifestMimeType": "application/vnd.tidal.bts", "manifest": encoded}


def _logged_in_tidal(routes, tmp_path) -> LiveTidal:
    cache = tmp_path / "tidal.json"
    cache.write_text(
        json.dumps(
            {
                "access_token": "at",
                "refresh_token": "rt",
                "expires_at": time.time() + 7 * 86400,
                "country_code": "US",
            }
        ),
        encoding="utf-8",
    )
    return make_tidal(routes, cache)


def test_stream_resolves_bts_manifest_url(tmp_path):
    def routes(request):
        assert request.headers["Authorization"] == "Bearer at"
        assert request.url.params["audioquality"] == "HI_RES"
        assert request.url.params["countryCode"] == "US"
        return httpx.Response(
            200,
            json=_bts(
                {
                    "urls": ["https://stream.tidal/a.flac"],
                    "codecs": "flac",
                    "encryptionType": "NONE",
                }
            ),
        )

    tidal = _logged_in_tidal(routes, tmp_path)

    stream = tidal.stream("9")

    assert stream.url == "https://stream.tidal/a.flac"


def test_stream_rejects_encrypted_manifest(tmp_path):
    def routes(request):
        return httpx.Response(
            200,
            json=_bts({"urls": ["https://stream.tidal/a"], "encryptionType": "WIDEVINE"}),
        )

    tidal = _logged_in_tidal(routes, tmp_path)

    try:
        tidal.stream("9")
        raised = False
    except RuntimeError as error:
        raised = "encrypted" in str(error)
    assert raised


def test_stream_rejects_non_bts_manifest(tmp_path):
    def routes(request):
        return httpx.Response(
            200,
            json={
                "manifestMimeType": "application/vnd.tidal.dash",
                "manifest": base64.b64encode(b"<MPD/>").decode(),
            },
        )

    tidal = _logged_in_tidal(routes, tmp_path)

    try:
        tidal.stream("9")
        raised = False
    except RuntimeError as error:
        raised = "unsupported" in str(error)
    assert raised
