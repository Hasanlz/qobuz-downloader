from typing import Any

import httpx

_TOKEN_URL = "https://accounts.spotify.com/api/token"


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
