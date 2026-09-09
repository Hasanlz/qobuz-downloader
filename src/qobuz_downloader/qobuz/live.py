import hashlib
import time
from typing import Any

import httpx

from qobuz_downloader.domain import (
    Album,
    Artist,
    Item,
    Playlist,
    Quality,
    Stream,
    Track,
    renumber,
)
from qobuz_downloader.qobuz._interface import Qobuz
from qobuz_downloader.qobuz._secrets import fetch_app_credentials
from qobuz_downloader.qobuz._urls import parse

_BASE = "https://www.qobuz.com/api.json/0.2/"
_PAGE_SIZE = 500
_TEST_TRACK_ID = "5966783"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:83.0) Gecko/20100101 Firefox/83.0",
    "Content-Type": "application/json;charset=UTF-8",
}
_FORMAT_IDS = {
    Quality.LOSSY: 5,
    Quality.CD: 6,
    Quality.HIRES_96: 7,
    Quality.HIRES_192: 27,
}
_FORMAT_QUALITIES = {value: key for key, value in _FORMAT_IDS.items()}


def _display_name(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("name")
    return value or ""


class LiveQobuz(Qobuz):
    def __init__(self) -> None:
        self._http = httpx.Client(headers=dict(_HEADERS), follow_redirects=True)
        self._secret = ""
        self._tracks: dict[str, list[Track]] = {}
        self._raw: dict[str, dict[str, Any]] = {}

    @classmethod
    def from_token(
        cls, app_id: str, app_secret: str, user_auth_token: str
    ) -> "LiveQobuz":
        instance = cls()
        instance._http.headers["X-App-Id"] = app_id
        instance._http.headers["X-User-Auth-Token"] = user_auth_token
        instance._secret = app_secret
        return instance

    def login(self, email: str, password: str) -> None:
        app_id, secrets = fetch_app_credentials()
        self._http.headers["X-App-Id"] = app_id
        response = self._http.get(
            _BASE + "user/login",
            params={"email": email, "password": password, "app_id": app_id},
        )
        if response.status_code == 401:
            raise ValueError("invalid Qobuz credentials")
        if response.status_code == 400:
            raise ValueError("invalid Qobuz app id")
        response.raise_for_status()
        payload = response.json()
        if not payload["user"]["credential"]["parameters"]:
            raise ValueError("free accounts cannot download tracks")
        self._http.headers["X-User-Auth-Token"] = payload["user_auth_token"]
        self._secret = self._working_secret(secrets)

    def item(self, url: str) -> Item:
        kind, item_id = parse(url)
        if kind == "album":
            payload = self._call("album/get", album_id=item_id)
            self._cache_tracks(
                str(payload["id"]),
                payload.get("tracks", {}).get("items", []),
                collection=payload.get("title", ""),
            )
            return Album(
                id=str(payload["id"]),
                title=payload.get("title", ""),
                artist=_display_name(payload.get("artist", {}).get("name")),
            )
        if kind == "track":
            payload = self._call("track/get", track_id=item_id)
            self._cache_tracks(str(payload["id"]), [payload])
            return self._track(payload)
        if kind == "playlist":
            payload = self._playlist(item_id)
            return Playlist(id=str(payload["id"]), title=payload.get("name", ""))
        payload = self._artist_albums(item_id)[0]
        return Artist(id=str(payload["artist"]["id"]), name=_display_name(payload["artist"]["name"]))

    def tracks(self, item: Item) -> list[Track]:
        if isinstance(item, Track):
            return [item]
        cached = self._tracks.get(item.id)
        if cached is not None:
            return list(cached)
        if isinstance(item, Album):
            payload = self._call("album/get", album_id=item.id)
            self._cache_tracks(
                item.id, payload.get("tracks", {}).get("items", []), collection=item.title
            )
        elif isinstance(item, Playlist):
            self._playlist(item.id, collection=item.title)
        elif isinstance(item, Artist):
            collected: list[Track] = []
            for album_payload in self._artist_albums(item.id):
                album = self._call("album/get", album_id=str(album_payload["id"]))
                self._cache_tracks(
                    str(album["id"]),
                    album.get("tracks", {}).get("items", []),
                    collection=album.get("title", ""),
                )
                collected.extend(self._tracks[str(album["id"])])
            self._tracks[item.id] = collected
        return list(self._tracks[item.id])

    def qualities(self, track: Track) -> list[Quality]:
        raw = self._raw.get(track.id)
        if raw is None:
            raw = self._call("track/get", track_id=track.id)
            self._raw[track.id] = raw
        bit_depth = raw.get("maximum_bit_depth") or 0
        sampling_rate = raw.get("maximum_sampling_rate") or 0
        ladder = [Quality.LOSSY, Quality.CD]
        if bit_depth >= 24:
            ladder.append(Quality.HIRES_96)
            if sampling_rate > 96:
                ladder.append(Quality.HIRES_192)
        return ladder

    def stream(self, track: Track, quality: Quality) -> Stream:
        payload = self._stream_request(track.id, _FORMAT_IDS[quality], self._secret)
        return Stream(
            url=payload["url"],
            quality=_FORMAT_QUALITIES.get(payload.get("format_id"), quality),
            sampling_rate=payload.get("sampling_rate"),
            bit_depth=payload.get("bit_depth"),
        )

    def search_tracks(self, query: str, limit: int) -> list[Track]:
        payload = self._call("track/search", query=query, limit=limit)
        items = payload.get("tracks", {}).get("items", [])
        tracks = []
        for item in items:
            self._raw[str(item["id"])] = item
            tracks.append(self._track(item))
        return tracks

    def search_albums(self, query: str, limit: int) -> list[Album]:
        payload = self._call("album/search", query=query, limit=limit)
        items = payload.get("albums", {}).get("items", [])
        return [
            Album(
                id=str(item["id"]),
                title=item.get("title", ""),
                artist=_display_name(item.get("artist", {}).get("name")),
                tracks_count=item.get("tracks_count"),
            )
            for item in items
        ]

    def _call(self, endpoint: str, **params: Any) -> dict[str, Any]:
        response = self._http.get(_BASE + endpoint, params=params)
        response.raise_for_status()
        return response.json()

    def _playlist(
        self, playlist_id: str, collection: str | None = None
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        payload: dict[str, Any] = {}
        offset = 0
        while True:
            payload = self._call(
                "playlist/get",
                playlist_id=playlist_id,
                extra="tracks",
                limit=_PAGE_SIZE,
                offset=offset,
            )
            batch = payload.get("tracks", {}).get("items", [])
            items.extend(batch)
            offset += _PAGE_SIZE
            if not batch or len(items) >= payload.get("tracks_count", 0):
                break
        if collection is None:
            collection = payload.get("name", "")
        self._tracks[str(payload["id"])] = renumber(
            self._track(item, collection=collection) for item in items
        )
        return payload

    def _artist_albums(self, artist_id: str) -> list[dict[str, Any]]:
        albums: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload = self._call(
                "artist/get",
                artist_id=artist_id,
                extra="albums",
                limit=_PAGE_SIZE,
                offset=offset,
            )
            batch = payload.get("albums", {}).get("items", [])
            albums.extend(batch)
            offset += _PAGE_SIZE
            if not batch or len(albums) >= payload.get("albums_count", 0):
                break
        return albums

    def _cache_tracks(
        self,
        key: str,
        payloads: list[dict[str, Any]],
        collection: str | None = None,
    ) -> None:
        for payload in payloads:
            self._raw[str(payload["id"])] = payload
        total = len(payloads)
        self._tracks.setdefault(key, []).extend(
            self._track(payload, collection=collection, track_total=total)
            for payload in payloads
        )

    @staticmethod
    def _track(
        payload: dict[str, Any],
        collection: str | None = None,
        track_total: int | None = None,
    ) -> Track:
        album = payload.get("album") or {}
        artist = album.get("artist") or payload.get("performer") or {}
        return Track(
            id=str(payload["id"]),
            title=payload.get("title", ""),
            artist=_display_name(artist.get("name")),
            album=album.get("title", ""),
            track_number=payload.get("track_number"),
            duration_seconds=payload.get("duration"),
            collection=collection,
            track_total=track_total,
        )

    def _working_secret(self, secrets: list[str]) -> str:
        for secret in secrets:
            if not secret:
                continue
            try:
                self._stream_request(_TEST_TRACK_ID, 5, secret)
                return secret
            except RuntimeError:
                continue
        raise RuntimeError("no working app secret found")

    def _stream_request(
        self, track_id: str, format_id: int, secret: str
    ) -> dict[str, Any]:
        unix = int(time.time())
        signature = hashlib.md5(
            f"trackgetFileUrlformat_id{format_id}intentstreamtrack_id{track_id}{unix}{secret}".encode()
        ).hexdigest()
        response = self._http.get(
            _BASE + "track/getFileUrl",
            params={
                "request_ts": unix,
                "request_sig": signature,
                "track_id": track_id,
                "format_id": format_id,
                "intent": "stream",
            },
        )
        if response.status_code == 400:
            raise RuntimeError(f"stream request rejected: {response.text}")
        response.raise_for_status()
        return response.json()
