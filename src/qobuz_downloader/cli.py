import argparse
import logging
import os
import sys
from pathlib import Path

import httpx

from qobuz_downloader.domain import (
    Complete,
    Quality,
    Track,
    Unmatched,
    UnmatchedTrack,
)
from qobuz_downloader.engine import Engine
from qobuz_downloader.lyrics import LrcLib
from qobuz_downloader.match import LiveSpotify, make_matcher
from qobuz_downloader.naming import Naming
from qobuz_downloader.queue import SqliteQueue
from qobuz_downloader.qobuz import LiveQobuz

_QUALITIES = {
    "cd": Quality.CD,
    "hires96": Quality.HIRES_96,
    "hires": Quality.HIRES_192,
}

log = logging.getLogger("qobuz_downloader")


def _quality(value: str) -> Quality:
    if value not in _QUALITIES:
        raise ValueError(f"unknown quality {value!r} (choose from cd, hires96, hires)")
    return _QUALITIES[value]


def _collect(
    qobuz: LiveQobuz, matcher: LiveSpotify, url: str
) -> tuple[list[Track], list[UnmatchedTrack]]:
    log.info("collecting tracks from %s", url)
    if "qobuz.com" in url:
        return qobuz.tracks(qobuz.item(url)), []
    result = matcher.match(url)
    if isinstance(result, Unmatched):
        return [], [UnmatchedTrack(title=url, artist="", reason=result.reason)]
    return result.tracks, result.unmatched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qobuz-downloader",
        description="Saves lossless audio files from a Qobuz subscription to the local disk.",
    )
    parser.add_argument("urls", nargs="*", help="Qobuz or Spotify URLs (omit to resume pending downloads)")
    parser.add_argument(
        "--dir", default=".", help="download directory (default: current directory)"
    )
    parser.add_argument(
        "--quality",
        default="hires",
        help="preferred quality ceiling: cd, hires96, hires (default: hires)",
    )
    parser.add_argument(
        "--dir-template",
        default="",
        help="directory layout; placeholders: {artist}, {album}, {collection}, {title},"
        " {tracknumber} (default: album or playlist name; no subdirectory for a"
        " single track)",
    )
    parser.add_argument("--file-template", default="{tracknumber} - {title}")
    parser.add_argument(
        "--db", default=None, help="queue database path (default: <dir>/.queue.sqlite3)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="download at most this many tracks this run (every track is still"
        " matched and queued; re-run to continue with the rest)",
    )
    parser.add_argument(
        "--no-lyrics",
        action="store_true",
        help="do not save .lrc lyric files alongside tracks",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="log every match decision and download retry to stderr",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

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
    engine = Engine(
        qobuz,
        naming,
        lyrics=None if args.no_lyrics else LrcLib(),
    )
    queue = SqliteQueue(Path(args.db) if args.db else root / ".queue.sqlite3")
    matcher = make_matcher(qobuz)

    had_error = False
    for url in args.urls:
        try:
            tracks, unmatched = _collect(qobuz, matcher, url)
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

    if not args.urls:
        requeued = queue.requeue_failed()
        print(f"resuming: {requeued} failed track(s) re-queued")

    pending = queue.pending()
    if not pending:
        print("queue is empty — pass URLs to download something")
        return 1 if had_error else 0
    # --limit caps this run's downloads only; the whole URL stays queued so a
    # re-run picks up the rest
    batch = pending[: max(args.limit, 0)] if args.limit is not None else pending
    print(
        f"downloading {len(batch)} track(s) at {args.quality}"
        + (f" ({len(pending) - len(batch)} more queued)" if len(batch) < len(pending) else "")
    )
    failures = 0
    consecutive_failures = 0
    for track in batch:
        outcome = engine.download(track, preferred)
        if isinstance(outcome, Complete):
            queue.complete(track)
            consecutive_failures = 0
            specs = f"{outcome.bit_depth}/{outcome.sampling_rate:g}" if outcome.sampling_rate else outcome.quality.name.lower()
            note = f", fell back from {preferred.name.lower()}" if outcome.fell_back else ""
            print(f"done: {track.artist} - {track.title} ({specs}{note})")
        else:
            failures += 1
            consecutive_failures += 1
            queue.fail(track, outcome.reason)
            print(
                f"failed: {track.artist} - {track.title} ({outcome.reason})",
                file=sys.stderr,
            )
            if consecutive_failures >= 5:
                remaining = len(queue.pending())
                print(
                    f"aborting after 5 consecutive failures (network down?):"
                    f" {remaining} track(s) still pending — re-run the same command to resume",
                    file=sys.stderr,
                )
                return 1
    return 1 if failures or had_error else 0


if __name__ == "__main__":
    sys.exit(main())
