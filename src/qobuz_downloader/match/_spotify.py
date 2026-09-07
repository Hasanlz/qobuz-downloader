from typing import Any, Protocol

import httpx
import re
import json

_TOKEN_URL = "https://accounts.spotify.com/api/token"


class SpotifyMetadata(Protocol):
    def track(self, spotify_id: str) -> dict[str, Any]: ...

    def album(self, spotify_id: str) -> dict[str, Any]: ...

    def playlist_tracks(
        self, spotify_id: str, limit: int | None = None
    ) -> list[dict[str, Any]]: ...


class EmbedSpotify:
    def __init__(self, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
            follow_redirects=True,
            timeout=30.0,
        )

    def track(self, spotify_id: str) -> dict[str, Any]:
        entity = self._entity("track", spotify_id)
        return {
            "id": entity["id"],
            "name": entity.get("name", ""),
            "artists": entity.get("artists", []),
            "album": {},
            "duration_ms": entity.get("duration"),
        }

    def album(self, spotify_id: str) -> dict[str, Any]:
        entity = self._entity("album", spotify_id)
        track_list = entity.get("trackList") or []
        artists = entity.get("artists") or (
            [{"name": track_list[0].get("subtitle", "")}] if track_list else []
        )
        return {
            "id": spotify_id,
            "name": entity.get("name", ""),
            "artists": artists,
            "total_tracks": len(track_list),
        }

    def playlist_tracks(
        self, spotify_id: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        entity = self._entity("playlist", spotify_id)
        entries = entity.get("trackList", [])
        if limit is not None:
            entries = entries[:limit]
        return [
            {
                "id": entry["uri"].rsplit(":", 1)[-1],
                "name": entry.get("title", ""),
                "artists": [{"name": entry.get("subtitle", "")}],
                "album": {},
                "duration_ms": entry.get("duration"),
            }
            for entry in entries
        ]

    def _entity(self, kind: str, spotify_id: str) -> dict[str, Any]:
        response = self._http.get(f"https://open.spotify.com/embed/{kind}/{spotify_id}")
        response.raise_for_status()
        match = _NEXT_DATA.search(response.text)
        if match is None:
            raise RuntimeError(f"no embed metadata for spotify {kind} {spotify_id}")
        page = json.loads(match.group(1))["props"]["pageProps"]
        entity = (page.get("state") or {}).get("data", {}).get("entity")
        if not entity:
            raise RuntimeError(
                f"spotify {kind} {spotify_id} not found (embed status {page.get('status')})"
            )
        return entity


_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


class Spotify:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        http: httpx.Client | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http or httpx.Client(timeout=30.0)
        self._token: str | None = None

    def track(self, spotify_id: str) -> dict[str, Any]:
        return self._get(f"https://api.spotify.com/v1/tracks/{spotify_id}")

    def album(self, spotify_id: str) -> dict[str, Any]:
        return self._get(f"https://api.spotify.com/v1/albums/{spotify_id}")

    def album_tracks(self, spotify_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        url: str | None = f"https://api.spotify.com/v1/albums/{spotify_id}/tracks?limit=50"
        while url:
            payload = self._get(url)
            items.extend(payload["items"])
            url = payload.get("next")
        return items

    def playlist_tracks(self, spotify_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        url: str | None = f"https://api.spotify.com/v1/playlists/{spotify_id}/tracks?limit=100"
        while url:
            payload = self._get(url)
            items.extend(item["track"] for item in payload["items"] if item.get("track"))
            url = payload.get("next")
        return items

    def _get(self, url: str) -> dict[str, Any]:
        if self._token is None:
            response = self._http.post(
                _TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(self._client_id, self._client_secret),
            )
            response.raise_for_status()
            self._token = response.json()["access_token"]
        response = self._http.get(
            url, headers={"Authorization": f"Bearer {self._token}"}
        )
        response.raise_for_status()
        return response.json()
