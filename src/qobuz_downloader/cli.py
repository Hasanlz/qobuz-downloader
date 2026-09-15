import argparse
import logging
import os
import sys
from pathlib import Path

import httpx

from qobuz_downloader import collect
from qobuz_downloader.domain import (
    Complete,
    Quality,
    Track,
    Unmatched,
    UnmatchedTrack,
)
from qobuz_downloader.engine import Engine
from qobuz_downloader.lyrics import FallbackLyrics, LrcLib, NetEase
from qobuz_downloader.match import LiveSpotify, make_matcher
from qobuz_downloader.match._catalog import Catalog
from qobuz_downloader.naming import Naming
from qobuz_downloader.queue import SqliteQueue
from qobuz_downloader.qobuz import LiveQobuz
from qobuz_downloader.source import Source, parse
from qobuz_downloader.source._deezer import DeezerSource
from qobuz_downloader.source._tidal import TidalSource
from qobuz_downloader.tidal import LiveTidal

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


def _sources_registry(
    qobuz: LiveQobuz, tidal: LiveTidal | None, deezer=None
) -> dict[str, Source]:
    """Downloadable platforms keyed by source name.

    A platform joins only when it can actually stream: Qobuz always
    (its credentials were validated at login), Tidal only after its
    one-time device login is cached, Deezer only with DEEZER_ARL set.
    Matching and native-URL collection use this same gate, so no track
    is ever queued against a platform that could not download it —
    tracks missing from the credentialed platforms are reported
    unmatched instead of failing later at stream time.
    """
    registry: dict[str, Source] = {}
    from qobuz_downloader.source import QobuzSource

    registry["qobuz"] = QobuzSource(qobuz)
    if tidal is not None and tidal.has_login():
        registry["tidal"] = TidalSource(tidal)
    if deezer is not None and deezer.has_login():
        registry["deezer"] = DeezerSource(deezer)
    return registry


def _build_catalog(
    mode: str, registry: dict[str, Source], allow_lossy: bool
) -> Catalog:
    """Source search order per --source, plus the report label."""
    order = {
        "qobuz": ["qobuz", "tidal", "deezer"],
        "tidal": ["tidal", "qobuz", "deezer"],
        "deezer": ["deezer", "qobuz", "tidal"],
    }
    names = order.get(mode, list(registry))
    sources = [registry[name] for name in names if name in registry]
    label = (
        " + ".join(s.name.capitalize() for s in sources)
        if len(sources) > 1
        else (sources[0].name.capitalize() if sources else "Qobuz")
    )
    return Catalog(sources, label=label, mode=mode, allow_lossy=allow_lossy)


def _collect(
    qobuz: LiveQobuz,
    matcher: LiveSpotify,
    url: str,
    *,
    tidal: LiveTidal | None = None,
    deezer=None,
) -> tuple[list[Track], list[UnmatchedTrack]]:
    log.info("collecting tracks from %s", url)
    if "qobuz.com" in url:
        return qobuz.tracks(qobuz.item(url)), []
    if collect.is_native(url):
        return collect.native_tracks(url, tidal=tidal, deezer=deezer), []
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
    parser.add_argument("--file-template", default="{tracknumber}. {title} - {artist}")
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
        "--tidal",
        action="store_true",
        help="replace the Qobuz file with a Tidal copy when Tidal has higher"
        " quality (fires only for tracks Qobuz delivered at 24-bit/44.1 or"
        " /48; needs a one-time Tidal login, a paid subscription for HiRes)",
    )
    parser.add_argument(
        "--source",
        default="best",
        choices=["best", "qobuz", "tidal", "deezer"],
        help="which catalog to match and download from: 'best' (default)"
        " searches every platform you have credentials for and keeps the"
        " highest-quality copy; a single platform name prefers it, with the"
        " other credentialed platforms as fallback; tracks on platforms"
        " without credentials are reported unmatched",
    )
    parser.add_argument(
        "--allow-lossy",
        action="store_true",
        help="when no lossless copy exists on any source, take MP3 instead of"
        " leaving the track unmatched",
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

    # Tidal: search/metadata needs no login (public partner token), but
    # only a *logged-in* Tidal joins the platform registry — otherwise
    # tracks would queue against a catalog we cannot stream from, and
    # fail at download time. --tidal (or --source tidal) triggers the
    # one-time browser device login; a cached login is picked up
    # silently and lets Tidal participate without any flag.
    tidal_client: LiveTidal | None = LiveTidal()
    if args.tidal or args.source == "tidal":
        try:
            tidal_client.ensure_login()
        except (RuntimeError, httpx.HTTPError) as error:
            print(
                f"error: tidal login failed: {error}"
                + (
                    " — --source tidal needs a working Tidal login"
                    if args.source == "tidal"
                    else " — continuing without Tidal"
                ),
                file=sys.stderr,
            )
            if args.source == "tidal":
                return 2
    elif not tidal_client.has_login():
        tidal_client = None  # no cached login and none requested: Tidal sits out

    # Deezer: search is public, but streaming needs the DEEZER_ARL
    # cookie; without it Deezer stays out of the registry entirely.
    from qobuz_downloader.deezer import LiveDeezer

    deezer: LiveDeezer | None = LiveDeezer(arl=os.environ.get("DEEZER_ARL", ""))
    if not deezer.has_login() and args.source == "deezer":
        print(
            "error: --source deezer needs the DEEZER_ARL environment"
            " variable set to your Deezer ARL cookie",
            file=sys.stderr,
        )
        return 2

    registry = _sources_registry(qobuz, tidal_client, deezer)
    catalog = _build_catalog(args.source, registry, args.allow_lossy)

    engine = Engine(
        qobuz,
        naming,
        lyrics=None if args.no_lyrics else FallbackLyrics(LrcLib(), NetEase()),
        tidal=tidal_client if args.tidal else None,
        sources=registry,
    )
    engine.allow_lossy(args.allow_lossy)
    queue = SqliteQueue(Path(args.db) if args.db else root / ".queue.sqlite3")
    matcher = make_matcher(qobuz, catalog=catalog)

    had_error = False
    unmatched_total = 0
    for url in args.urls:
        try:
            tracks, unmatched = _collect(
                qobuz,
                matcher,
                url,
                tidal=tidal_client,
                deezer=deezer,
            )
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
            unmatched_total += 1

    missing_platforms = [
        name
        for name, ready in (("tidal", tidal_client), ("deezer", deezer))
        if ready is None or not ready.has_login()
    ]
    if unmatched_total and missing_platforms:
        print(
            f"note: {unmatched_total} track(s) unmatched; some may exist on"
            f" platforms without credentials ({', '.join(missing_platforms)})"
            " — add a Tidal login (--tidal) or DEEZER_ARL to download those",
            file=sys.stderr,
        )

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
            if outcome.upgraded:
                note += ", upgraded from Tidal"
            source = parse(track.id)[0]
            if source != "qobuz":
                note += f", from {source}"
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
