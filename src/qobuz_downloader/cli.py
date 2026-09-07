import argparse
import os
import sys
from pathlib import Path

import httpx

from qobuz_downloader.domain import (
    Complete,
    Failed,
    Quality,
    Track,
    Unmatched,
    UnmatchedTrack,
)
from qobuz_downloader.engine import Engine
from qobuz_downloader.match import LiveSpotify, make_matcher
from qobuz_downloader.naming import Naming
from qobuz_downloader.queue import Queue, SqliteQueue
from qobuz_downloader.qobuz import LiveQobuz

_QUALITIES = {
    "cd": Quality.CD,
    "hires96": Quality.HIRES_96,
    "hires": Quality.HIRES_192,
}


def _quality(value: str) -> Quality:
    if value not in _QUALITIES:
        raise ValueError(f"unknown quality {value!r} (choose from cd, hires96, hires)")
    return _QUALITIES[value]


def _collect(
    qobuz: LiveQobuz, matcher: LiveSpotify, url: str, limit: int | None = None
) -> tuple[list[Track], list[UnmatchedTrack]]:
    if "qobuz.com" in url:
        tracks = qobuz.tracks(qobuz.item(url))
        return (tracks[:limit] if limit is not None else tracks), []
    result = matcher.match(url, limit)
    if isinstance(result, Unmatched):
        return [], [UnmatchedTrack(title=url, artist="", reason=result.reason)]
    return result.tracks, result.unmatched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qobuz-downloader",
        description="Saves lossless audio files from a Qobuz subscription to the local disk.",
    )
    parser.add_argument("urls", nargs="+", help="Qobuz or Spotify URLs")
    parser.add_argument(
        "--dir", default=".", help="download directory (default: current directory)"
    )
    parser.add_argument(
        "--quality",
        default="hires",
        help="preferred quality ceiling: cd, hires96, hires (default: hires)",
    )
    parser.add_argument("--dir-template", default="{artist}/{album}")
    parser.add_argument("--file-template", default="{tracknumber} - {title}")
    parser.add_argument(
        "--db", default=None, help="queue database path (default: <dir>/.queue.sqlite3)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="queue at most this many tracks per URL",
    )
    args = parser.parse_args(argv)

    try:
        preferred = _quality(args.quality)
    except ValueError as error:
        parser.error(str(error))

    token = os.environ.get("QOBUZ_USER_AUTH_TOKEN")
    app_id = os.environ.get("QOBUZ_APP_ID")
    app_secret = os.environ.get("QOBUZ_APP_SECRET")
    if token and app_id and app_secret:
        qobuz = LiveQobuz.from_token(app_id, app_secret, token)
    else:
        email = os.environ.get("QOBUZ_EMAIL")
        password = os.environ.get("QOBUZ_PASSWORD")
        if not (email and password):
            print(
                "set QOBUZ_USER_AUTH_TOKEN + QOBUZ_APP_ID + QOBUZ_APP_SECRET,"
                " or QOBUZ_EMAIL + QOBUZ_PASSWORD",
                file=sys.stderr,
            )
            return 2
        qobuz = LiveQobuz()
        try:
            qobuz.login(email, password)
        except (ValueError, RuntimeError, httpx.HTTPError) as error:
            print(f"login failed: {error}", file=sys.stderr)
            return 1

    root = Path(args.dir).expanduser()
    naming = Naming(args.dir_template, args.file_template, root=root)
    engine = Engine(qobuz, naming)
    queue = SqliteQueue(Path(args.db) if args.db else root / ".queue.sqlite3")
    matcher = make_matcher(qobuz)

    had_error = False
    for url in args.urls:
        try:
            tracks, unmatched = _collect(qobuz, matcher, url, args.limit)
        except (ValueError, RuntimeError) as error:
            print(f"error: {error}", file=sys.stderr)
            had_error = True
            continue
        report = queue.add(tracks)
        if report.added:
            print(f"queued {len(report.added)} track(s)")
        for track in report.skipped:
            print(f"skipped: {track.artist} - {track.title}")
        for miss in unmatched:
            who = f"{miss.artist} - {miss.title}" if miss.artist else miss.title
            print(f"unmatched: {who} ({miss.reason})", file=sys.stderr)

    pending = queue.pending()
    print(f"downloading {len(pending)} track(s) at {args.quality}")
    failures = 0
    for track in pending:
        outcome = engine.download(track, preferred)
        if isinstance(outcome, Complete):
            queue.complete(track)
            specs = f"{outcome.bit_depth}/{outcome.sampling_rate:g}" if outcome.sampling_rate else outcome.quality.name.lower()
            note = f", fell back from {preferred.name.lower()}" if outcome.fell_back else ""
            print(f"done: {track.artist} - {track.title} ({specs}{note})")
        else:
            failures += 1
            queue.fail(track, outcome.reason)
            print(
                f"failed: {track.artist} - {track.title} ({outcome.reason})",
                file=sys.stderr,
            )
    return 1 if failures or had_error else 0


if __name__ == "__main__":
    sys.exit(main())
