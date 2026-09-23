#!/usr/bin/env python3
"""Compare current Spotify playlist positions with a SQLite download queue.

This is intentionally read-only: it opens the queue with SQLite's
``mode=ro`` URI and never instantiates the application Queue, whose
constructor creates or migrates the database.

The queue stores matched source ids rather than Spotify ids, so this is a
position-coverage diagnostic, not an exact playlist-to-queue join. It
reports the rows occupying each position so duplicate/replacement rows are
visible; use the JSON output as a redacted review artifact.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from qobuz_downloader.match._public import PublicSpotify
from qobuz_downloader.match._spotify import EmbedSpotify
from qobuz_downloader.match._spotify_urls import parse_spotify


def _read_queue(path: Path, track_total: int | None) -> list[dict[str, Any]]:
    """Read queue rows without creating, migrating, or writing the DB."""
    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(tracks)")}
        required = {"id", "track_number", "status", "title", "artist", "track_total"}
        missing = required - columns
        if missing:
            raise RuntimeError(f"queue schema lacks columns: {', '.join(sorted(missing))}")
        query = (
            "SELECT id, track_number, status, title, artist, track_total "
            "FROM tracks"
        )
        parameters: tuple[Any, ...] = ()
        if track_total is not None:
            query += " WHERE track_total = ?"
            parameters = (track_total,)
        query += " ORDER BY rowid"
        return [
            {
                "id": row[0],
                "track_number": row[1],
                "status": row[2],
                "title": row[3],
                "artist": row[4],
                "track_total": row[5],
            }
            for row in db.execute(query, parameters)
        ]


def _fetch_playlist(url: str, metadata_json: Path | None) -> list[dict[str, Any]]:
    if metadata_json is not None:
        return json.loads(metadata_json.read_text())
    kind, spotify_id = parse_spotify(url)
    if kind != "playlist":
        raise ValueError("inventory requires a Spotify playlist URL")
    try:
        client = PublicSpotify()
        return client.playlist_tracks(spotify_id)
    except ImportError:
        # The public adapter is an optional extra. The embed fallback is
        # useful for small playlists, but Spotify may cap it around 100.
        return EmbedSpotify().playlist_tracks(spotify_id)


def build_report(
    spotify_tracks: list[dict[str, Any]],
    queue_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    by_position: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in queue_rows:
        if row["track_number"] is not None:
            by_position[int(row["track_number"])].append(row)

    current_positions = set(range(1, len(spotify_tracks) + 1))
    queue_positions = set(by_position)
    missing = sorted(current_positions - queue_positions)
    unexpected = sorted(queue_positions - current_positions)
    duplicates = [
        {"position": position, "rows": by_position[position]}
        for position in sorted(current_positions & queue_positions)
        if len(by_position[position]) > 1
    ]
    gaps = [
        {
            "position": position,
            "spotify_id": spotify_tracks[position - 1].get("id"),
            "title": spotify_tracks[position - 1].get("name", ""),
            "artists": [
                artist["name"]
                for artist in spotify_tracks[position - 1].get("artists", [])
                if artist.get("name")
            ],
            "duration_ms": spotify_tracks[position - 1].get("duration_ms"),
        }
        for position in missing
    ]
    generations: dict[str, int] = defaultdict(int)
    for row in queue_rows:
        generations[str(row["track_total"])] += 1

    return {
        "spotify_positions": len(spotify_tracks),
        "queue_rows": len(queue_rows),
        "queue_distinct_positions": len(queue_positions),
        "covered_positions": len(current_positions & queue_positions),
        "missing_positions": missing,
        "unexpected_queue_positions": unexpected,
        "duplicate_positions": duplicates,
        "queue_rows_by_track_total": dict(sorted(generations.items())),
        "gaps": gaps,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spotify_url", help="Spotify playlist URL")
    parser.add_argument("queue_db", type=Path)
    parser.add_argument("--json", type=Path, help="write the redacted report here")
    parser.add_argument(
        "--track-total",
        type=int,
        help="only inspect rows from this match generation",
    )
    parser.add_argument(
        "--metadata-json",
        type=Path,
        help="read a captured Spotify track list instead of fetching it",
    )
    args = parser.parse_args()

    spotify_tracks = _fetch_playlist(args.spotify_url, args.metadata_json)
    report = build_report(spotify_tracks, _read_queue(args.queue_db, args.track_total))
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    print(f"spotify positions: {report['spotify_positions']}")
    print(f"queue rows: {report['queue_rows']}")
    print(f"covered positions: {report['covered_positions']}")
    print(
        f"missing positions ({len(report['missing_positions'])}): "
        f"{', '.join(map(str, report['missing_positions']))}"
    )
    print(
        f"unexpected queue positions ({len(report['unexpected_queue_positions'])}): "
        f"{report['unexpected_queue_positions']}"
    )
    print(f"positions with multiple rows ({len(report['duplicate_positions'])})")
    for gap in report["gaps"]:
        print(f"  {gap['position']}: {', '.join(gap['artists'])} - {gap['title']}")
    return 1 if report["missing_positions"] or report["duplicate_positions"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
