import base64
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from qobuz_downloader.domain import Quality, Stream, Track
from qobuz_downloader.match.live import _THRESHOLD, _score_track
from qobuz_downloader.tidal._interface import Tidal

log = logging.getLogger(__name__)

_API = "https://api.tidal.com/v1/"
_OAUTH = "https://auth.tidal.com/v1/oauth2"
# public partner token from Tidal's embed player: search/metadata only
_PARTNER_TOKEN = "TPIsV0A9lyiqKl9u"
# public Fire TV client credentials (same pair tidal-wave and streamrip ship)
_CLIENT_ID = "fX2JxdmntZWK0ixT"
_CLIENT_SECRET = "1Nm5AfDAjxrgJFJbKNWLeAyKGVGmINuXPPLHVXAvxAg="
_SCOPE = "r_usr+w_usr+w_sub"

_REFRESH_MARGIN = 24 * 3600  # refresh a week-long token a day early
_AUTHORIZATION_PENDING = 1002
_SLOW_DOWN = 1003

_DEFAULT_CACHE = Path.home() / ".cache" / "qobuz-downloader" / "tidal.json"


class LiveTidal(Tidal):
    def __init__(
        self,
        http: httpx.Client | None = None,
        cache: Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http or httpx.Client(
            timeout=httpx.Timeout(30.0, read=60.0), follow_redirects=True
        )
        self._cache = cache or _DEFAULT_CACHE
        self._sleep = sleep
        self._access_token = ""
        self._refresh_token = ""
        self._expires_at = 0.0
        self._country = "US"
        self._load_cache()

    # -- matching ---------------------------------------------------------

    def hires_match_for(self, track: Track) -> str | None:
        response = self._http.get(
            _API + "search",
            params={
                "query": f"{track.artist} {track.title}",
                "limit": 20,
                "types": "tracks",
                "countryCode": self._country,
            },
            headers={"X-Tidal-Token": _PARTNER_TOKEN},
        )
        response.raise_for_status()
        items = response.json().get("tracks", {}).get("items", [])
        best: dict[str, Any] | None = None
        best_score = 0.0
        for item in items:
            tags = item.get("mediaMetadata", {}).get("tags", [])
            if "HIRES_LOSSLESS" not in tags:
                continue
            score = _score_track(track, self._candidate(item))
            if score > best_score:
                best, best_score = item, score
        if best is None or best_score < _THRESHOLD:
            return None
        log.info(
            "tidal match for %s - %s: %s (%s)",
            track.artist,
            track.title,
            best.get("title"),
            ",".join(best.get("mediaMetadata", {}).get("tags", [])),
        )
        return str(best["id"])

    @staticmethod
    def _candidate(item: dict[str, Any]) -> Track:
        return Track(
            id=str(item["id"]),
            title=item.get("title", ""),
            artist=(item.get("artists") or [{}])[0].get("name", ""),
            album=(item.get("album") or {}).get("title", ""),
            duration_seconds=item.get("duration"),
        )

    # -- streaming --------------------------------------------------------

    def stream(self, tidal_track_id: str) -> Stream:
        self.ensure_login()
        response = self._http.get(
            _API + f"tracks/{tidal_track_id}/playbackinfopostpaywall",
            params={
                "audioquality": "HI_RES",
                "playbackmode": "STREAM",
                "assetpresentation": "FULL",
                "countryCode": self._country,
            },
            headers={"Authorization": f"Bearer {self._access_token}"},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("manifestMimeType") != "application/vnd.tidal.bts":
            raise RuntimeError(
                f"unsupported tidal manifest: {payload.get('manifestMimeType')}"
            )
        manifest = json.loads(base64.b64decode(payload["manifest"]))
        if manifest.get("encryptionType") != "NONE":
            raise RuntimeError("tidal stream is encrypted")
        urls = manifest.get("urls") or []
        if not urls:
            raise RuntimeError("tidal manifest has no stream urls")
        return Stream(
            url=urls[0],
            quality=Quality.HIRES_192,
            sampling_rate=manifest.get("sampleRate"),
            bit_depth=manifest.get("bitDepth"),
        )

    # -- auth -------------------------------------------------------------

    def ensure_login(self) -> None:
        if self._access_token and self._expires_at - time.time() > _REFRESH_MARGIN:
            return
        if self._refresh_token:
            try:
                self._refresh()
                return
            except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as error:
                log.warning("tidal token refresh failed: %s", error)
        self._device_login()

    def _device_login(self) -> None:
        response = self._http.post(
            _OAUTH + "/device_authorization",
            data={"client_id": _CLIENT_ID, "scope": _SCOPE},
        )
        response.raise_for_status()
        data = response.json()
        uri = data["verificationUriComplete"]
        log.info(
            "tidal login: open https://%s in a browser and approve the code %s",
            uri,
            data.get("userCode", ""),
        )
        interval = max(data.get("interval", 2), 2)
        deadline = time.monotonic() + data.get("expiresIn", 300)
        while time.monotonic() < deadline:
            self._sleep(interval)
            token = self._http.post(
                _OAUTH + "/token",
                data={
                    "client_id": _CLIENT_ID,
                    "device_code": data["deviceCode"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "scope": _SCOPE,
                },
                auth=(_CLIENT_ID, _CLIENT_SECRET),
            )
            body = token.json()
            if token.status_code == 200 and "access_token" in body:
                self._store(body)
                return
            if body.get("sub_status") == _SLOW_DOWN:
                interval += 2
                continue
            if body.get("sub_status") != _AUTHORIZATION_PENDING:
                raise RuntimeError(
                    f"tidal login failed: {body.get('userMessage') or body}"
                )
        raise RuntimeError("tidal login timed out — run again to retry")

    def _refresh(self) -> None:
        token = self._http.post(
            _OAUTH + "/token",
            data={
                "client_id": _CLIENT_ID,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
                "scope": _SCOPE,
            },
            auth=(_CLIENT_ID, _CLIENT_SECRET),
        )
        token.raise_for_status()
        body = token.json()
        if "access_token" not in body:
            raise RuntimeError(f"tidal refresh rejected: {body}")
        self._store(body)

    def _store(self, body: dict[str, Any]) -> None:
        self._access_token = body["access_token"]
        self._refresh_token = body.get("refresh_token") or self._refresh_token
        self._expires_at = time.time() + body.get("expires_in", 604800)
        user = body.get("user") or {}
        self._country = user.get("countryCode") or self._country
        self._save_cache()

    def _save_cache(self) -> None:
        self._cache.parent.mkdir(parents=True, exist_ok=True)
        self._cache.write_text(
            json.dumps(
                {
                    "access_token": self._access_token,
                    "refresh_token": self._refresh_token,
                    "expires_at": self._expires_at,
                    "country_code": self._country,
                }
            ),
            encoding="utf-8",
        )

    def _load_cache(self) -> None:
        try:
            data = json.loads(self._cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self._access_token = data.get("access_token", "")
        self._refresh_token = data.get("refresh_token", "")
        self._expires_at = data.get("expires_at", 0.0)
        self._country = data.get("country_code") or self._country
