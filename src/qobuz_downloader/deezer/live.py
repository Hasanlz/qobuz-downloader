"""Live Deezer client: public search, gw-light metadata, get_url media.

The ARL cookie (``DEEZER_ARL``) authenticates gw-light; the media URL
service is authorized by the license token from ``deezer.getUserData``.
Full-track media is Blowfish-encrypted in stripes (every third 2048-byte
block) — ``docs/research/2026-09-12-deezer-streaming.md`` — and is
decrypted lazily by :class:`DecryptingSource` carried inside the
Stream, so the engine never sees ciphertext (ADR 0002).
"""

import hashlib
import logging
from collections.abc import Iterator
from dataclasses import replace

import httpx
from Crypto.Cipher import Blowfish

from qobuz_downloader.deezer._interface import Deezer
from qobuz_downloader.domain import Quality, Stream, Track, renumber

log = logging.getLogger(__name__)

_GW = "https://www.deezer.com/ajax/gw-light.php"
_API = "https://api.deezer.com"
_MEDIA = "https://media.deezer.com"
_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"
_BF_SECRET = b"g4el58wc0zvf9na1"
_BF_IV = b"\x00\x01\x02\x03\x04\x05\x06\x07"
_BLOCK = 2048

_FORMATS = {Quality.LOSSY: "MP3_320", Quality.CD: "FLAC"}


def _bf_key(sng_id: str) -> bytes:
    """The classic deemix key: md5(song id) hex bytes xored with a secret."""
    md5_hex = hashlib.md5(sng_id.encode()).hexdigest().encode()
    return bytes(md5_hex[i] ^ md5_hex[i + 16] ^ _BF_SECRET[i] for i in range(16))


class DecryptingSource:
    """A byte source that streams a Deezer media url as plaintext.

    Every third 2048-byte block (counted from the stream start) is
    Blowfish-CBC encrypted; a trailing partial block never is. The
    stripe depends on absolute block position, so a mid-file resume
    cannot decrypt: range requests are answered like a server that
    ignores ranges (plain 200), and the engine restarts cleanly.
    """

    def __init__(self, http: httpx.Client, url: str, sng_id: str) -> None:
        self._http = http
        self._url = url
        self._key = _bf_key(sng_id)

    def stream(self, url: str, start: int):
        from qobuz_downloader.engine._source import ByteResponse

        response = self._http.send(
            self._http.build_request("GET", self._url), stream=True
        )
        response.raise_for_status()
        length = response.headers.get("content-length")
        return ByteResponse(
            status=200,  # ranges are unsupported: the engine restarts
            length=int(length) if length is not None else None,
            chunks=self._chunks(response),
        )

    def _chunks(self, response: httpx.Response) -> Iterator[bytes]:
        block_index = 0
        buffer = b""
        try:
            for chunk in response.iter_bytes(64 * 1024):
                buffer += chunk
                while len(buffer) >= _BLOCK:
                    yield self._block(buffer[:_BLOCK], block_index)
                    buffer = buffer[_BLOCK:]
                    block_index += 1
            if buffer:
                yield buffer
        finally:
            response.close()

    def _block(self, data: bytes, index: int) -> bytes:
        if index % 3 == 0 and len(data) == _BLOCK:
            return Blowfish.new(self._key, Blowfish.MODE_CBC, _BF_IV).decrypt(data)
        return data


class LiveDeezer(Deezer):
    def __init__(self, arl: str = "", http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(timeout=30.0, follow_redirects=True)
        self._http.cookies.set("arl", arl, domain=".deezer.com")
        self._http.headers["User-Agent"] = _USER_AGENT
        self._arl = arl
        self._api_token = ""
        self._license_token = ""
        self._allowed: set[str] = set()
        self._songs: dict[str, dict] = {}

    # -- session ----------------------------------------------------------

    def has_login(self) -> bool:
        return bool(self._arl)

    def ensure_login(self) -> None:
        """Bootstrap the gw-light session (api + license tokens)."""
        if not self._arl:
            raise RuntimeError(
                "deezer login needed — set the DEEZER_ARL environment"
                " variable to your Deezer ARL cookie"
            )
        if self._license_token:
            return
        response = self._http.post(
            _GW,
            params={
                "method": "deezer.getUserData",
                "input": "3",
                "api_version": "1.0",
                "api_token": "",
            },
            json={},
        )
        response.raise_for_status()
        results = response.json().get("results", {})
        self._api_token = results.get("checkForm", "")
        options = (results.get("USER") or {}).get("OPTIONS") or {}
        self._license_token = options.get("license_token", "")
        sound = options.get("web_sound_quality") or {}
        if sound.get("lossless"):
            self._allowed.update({"MP3_320", "FLAC"})
        elif sound.get("high"):
            self._allowed.add("MP3_320")
        if not self._license_token:
            raise RuntimeError("deezer ARL rejected: no license token returned")

    # -- matching ---------------------------------------------------------

    def search_tracks(self, query: str, limit: int) -> list[Track]:
        response = self._http.get(_API + "/search", params={"q": query, "limit": limit})
        response.raise_for_status()
        return [self._candidate(item) for item in response.json().get("data", [])]

    @staticmethod
    def _candidate(item: dict) -> Track:
        return Track(
            id=str(item["id"]),
            title=item.get("title", ""),
            artist=(item.get("artist") or {}).get("name", ""),
            album=(item.get("album") or {}).get("title", ""),
            duration_seconds=item.get("duration"),
        )

    # -- native URLs ------------------------------------------------------

    def native_tracks(self, kind: str, native_id: str) -> list[Track]:
        """Tracks behind a deezer.com track/album/playlist link.

        Public API metadata; streaming (the download itself) needs the
        ARL, which ensure_login surfaces as a clear error at stream time.
        """
        if kind == "track":
            return [self._candidate(self._public(f"track/{native_id}"))]
        if kind == "album":
            album = self._public(f"album/{native_id}")
            return [
                replace(
                    self._candidate(item),
                    track_number=item.get("track_position")
                    or item.get("position"),
                    collection=album.get("title", ""),
                    track_total=album.get("nb_tracks"),
                )
                for item in self._edge_items(album, f"album/{native_id}/tracks")
            ]
        if kind == "playlist":
            playlist = self._public(f"playlist/{native_id}")
            collected = [
                self._candidate(item)
                for item in self._edge_items(playlist, f"playlist/{native_id}/tracks")
            ]
            return renumber(
                collected, collection=playlist.get("title", "") or "playlist"
            )
        raise ValueError(f"unsupported deezer URL kind: {kind}")

    def _edge_items(self, parent: dict, path: str) -> list[dict]:
        """All items of a `tracks` edge, paged (the public API caps at 25)."""
        edge = parent.get("tracks") or {}
        items = list(edge.get("data", []))
        total = edge.get("total") or len(items)
        while len(items) < total:
            page = self._public(path, index=len(items))
            batch = page.get("data", [])
            if not batch:
                break
            items.extend(batch)
        return items

    def _public(self, path: str, index: int = 0) -> dict:
        response = self._http.get(
            f"{_API}/{path}", params={"index": index} if index else None
        )
        response.raise_for_status()
        return response.json()

    def _song_data(self, deezer_track_id: str) -> dict:
        if deezer_track_id in self._songs:
            return self._songs[deezer_track_id]
        self.ensure_login()
        response = self._http.post(
            _GW,
            params={
                "method": "song.getData",
                "input": "3",
                "api_version": "1.0",
                "api_token": self._api_token,
            },
            json={"sng_id": deezer_track_id},
        )
        response.raise_for_status()
        results = response.json().get("results", {})
        if not results.get("SNG_ID"):
            raise RuntimeError(f"deezer track {deezer_track_id} not found")
        self._songs[deezer_track_id] = results
        return results

    def qualities(self, deezer_track_id: str) -> list[Quality]:
        song = self._song_data(deezer_track_id)
        ladder: list[Quality] = []
        if "FLAC" in self._allowed and song.get("FILESIZE_FLAC"):
            ladder.extend([Quality.LOSSY, Quality.CD])
        elif "MP3_320" in self._allowed and song.get("FILESIZE_MP3_320"):
            ladder.append(Quality.LOSSY)
        return ladder

    def cover_url(self, deezer_track_id: str) -> str | None:
        try:
            song = self._song_data(deezer_track_id)
            picture = song.get("ALB_PICTURE")
            if not picture:
                return None
            return (
                "https://e-cdns-images.dzcdn.net/images/cover/"
                f"{picture}/1000x1000-000000-80-0-0.jpg"
            )
        except Exception:
            return None

    # -- streaming --------------------------------------------------------

    def stream(self, track: Track, quality: Quality) -> Stream:
        from qobuz_downloader.source import parse

        _, native_id = parse(track.id)
        song = self._song_data(native_id)
        formats = [
            {"cipher": "BF_CBC_STRIPE", "format": _FORMATS[rung]}
            for rung in (Quality.CD, Quality.LOSSY)
            if _FORMATS[rung] in self._allowed and rung <= quality
        ]  # ordered preference: the service takes the first available
        if not formats:
            raise RuntimeError(
                "the deezer account cannot stream this track's formats"
            )
        response = self._http.post(
            _MEDIA + "/v1/get_url",
            json={
                "license_token": self._license_token,
                "media": [{"type": "FULL", "formats": formats}],
                "track_tokens": [song["TRACK_TOKEN"]],
            },
        )
        response.raise_for_status()
        entry = (response.json().get("data") or [{}])[0]
        if entry.get("errors"):
            raise RuntimeError(f"deezer media rejected: {entry['errors']}")
        media = (entry.get("media") or [{}])[0]
        sources = media.get("sources") or []
        if not sources:
            raise RuntimeError("deezer returned no media source")
        url = sources[0]["url"]
        log.info(
            "deezer media for %s: %s (%s bytes)",
            song.get("SNG_TITLE"),
            media.get("format"),
            sources[0].get("filesize"),
        )
        return Stream(
            url=url,
            quality=quality,
            byte_source=DecryptingSource(self._http, url, str(song["SNG_ID"])),
        )
