from collections.abc import Iterator
from typing import Any

from qobuz_downloader.match._spotify import SpotifyMetadata


def _artist_names(payload: dict[str, Any] | list[Any]) -> list[str]:
    items = payload.get("items", []) if isinstance(payload, dict) else payload
    names = []
    for item in items:
        profile = item.get("profile") if isinstance(item, dict) else None
        name = (profile or item).get("name") if isinstance(profile or item, dict) else None
        if name:
            names.append(name)
    return names


class PublicSpotify(SpotifyMetadata):
    def __init__(self) -> None:
        from spotapi import Public

        self._public = Public

    def track(self, spotify_id: str) -> dict[str, Any]:
        union = self._public.song_info(spotify_id)["data"]["trackUnion"]
        artists = union.get("firstArtist", {"items": []}).get("items", []) + union.get(
            "otherArtists", {"items": []}
        ).get("items", [])
        return {
            "id": union.get("id", spotify_id),
            "name": union.get("name", ""),
            "artists": [{"name": name} for name in _artist_names(artists)],
            "album": {},
            "duration_ms": (union.get("duration") or {}).get("totalMilliseconds"),
        }

    def album(self, spotify_id: str) -> dict[str, Any]:
        batches = self._public.album_info(spotify_id)
        first = next(batches, None)
        if first is None:
            raise RuntimeError(f"spotify album {spotify_id} not found")
        track_batches = first if isinstance(first, list) else []
        name = ""
        artist = ""
        for batch in batches:
            if isinstance(batch, dict) and batch.get("albumOfTrack"):
                album = batch["albumOfTrack"]
                name = album.get("name", name)
                artist = _artist_names(album.get("artists", {}))
                artist = artist[0] if artist else artist
                break
        return {
            "id": spotify_id,
            "name": name,
            "artists": [{"name": artist}] if artist else [],
            "total_tracks": len(track_batches),
        }

    def playlist_tracks(
        self, spotify_id: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        tracks: list[dict[str, Any]] = []
        for batch in self._public.playlist_info(spotify_id):
            for entry in batch.get("items", []):
                union = (entry.get("itemV2") or {}).get("data") or {}
                if union.get("__typename") not in (None, "Track"):
                    continue
                uri = union.get("uri", "")
                if not uri.startswith("spotify:track:"):
                    continue
                artists = union.get("artists", {}).get("items", [])
                tracks.append(
                    {
                        "id": uri.rsplit(":", 1)[-1],
                        "name": union.get("name", ""),
                        "artists": [{"name": name} for name in _artist_names(artists)],
                        "album": {
                            "name": (union.get("albumOfTrack") or {}).get("name", "")
                        },
                        "duration_ms": (
                            union.get("trackDuration") or {}
                        ).get("totalMilliseconds"),
                    }
                )
                if limit is not None and len(tracks) >= limit:
                    return tracks
        return tracks
