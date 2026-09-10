# qobuz-downloader

Saves lossless audio files (FLAC) from a Qobuz subscription to your local disk. Accepts both Qobuz and Spotify URLs — Spotify links are matched against Qobuz's catalog automatically, downloads always come from your own Qobuz account.

## Requirements

- Python 3.12+
- An active **Qobuz subscription** (free accounts cannot download; Studio tier recommended for Hi-Res)

## Install

```bash
git clone https://github.com/Hasanlz/qobuz-downloader.git
cd qobuz-downloader
pip install -e ".[big-playlists]"
```

The `big-playlists` extra adds support for Spotify playlists over 100 tracks (tested with 1000+). Without it, playlist matching falls back to the embed page, which caps at 100 tracks.

## Credentials

Set environment variables before running.

**Preferred — token auth (no stored password):**

```bash
export QOBUZ_USER_AUTH_TOKEN="..."   # user auth token
export QOBUZ_APP_ID="..."            # 9-digit app id
export QOBUZ_APP_SECRET="..."        # 32-char app secret
```

**Alternative — email/password** (app id and secret are scraped automatically):

```bash
export QOBUZ_EMAIL="you@example.com"
export QOBUZ_PASSWORD="..."
```

No Spotify credentials are needed — metadata comes from public embed pages / Spotify's public partner API.

## Usage

```bash
qobuz-downloader URL [URL ...] [options]
```

### URL types

| Input | Behavior |
|---|---|
| `https://open.qobuz.com/track/25273041` | downloads the track |
| `https://play.qobuz.com/album/0060254746222` | downloads every track on the album |
| `https://www.qobuz.com/us-en/interpreter/amy-winehouse/5045` | downloads the artist's albums |
| `https://open.spotify.com/track/...` | finds the track on Qobuz, downloads it |
| `https://open.spotify.com/album/...` | matches the album, downloads it |
| `https://open.spotify.com/playlist/...` | matches and downloads track by track |

Qobuz and Spotify URLs can be mixed in one command.

### Examples

Download an album at the best available quality (files land in `./Album Name/`):

```bash
qobuz-downloader https://play.qobuz.com/album/0060254746222 --dir ~/Music
```

Download a 1000-track Spotify playlist (files land in `./Playlist Name/`, numbered by playlist position):

```bash
qobuz-downloader https://open.spotify.com/playlist/6Nq4BLzd6vTMIye1kkUhBN --dir ~/Music
```

Download a single track (goes straight into `--dir`, no subdirectory):

```bash
qobuz-downloader https://open.qobuz.com/track/25273041 --dir ~/Music
```

Test the waters first — the whole playlist is matched and queued, but only the first 3 tracks are downloaded:

```bash
qobuz-downloader https://open.spotify.com/playlist/6Nq4BLzd6vTMIye1kkUhBN --limit 3 --dir ~/Music
```

Every re-run of the same command downloads the next batch; omit `--limit` to download everything still queued.

Force CD quality (16-bit/44.1 kHz) to save bandwidth:

```bash
qobuz-downloader https://play.qobuz.com/album/0060254746222 --quality cd
```

Custom file layout:

```bash
qobuz-downloader URL --dir-template "{artist}/{album}" --file-template "{tracknumber}. {title}"
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--dir` | `.` | download directory (also where the queue database lives) |
| `--quality` | `hires` | preferred quality ceiling: `cd`, `hires96`, `hires` |
| `--dir-template` | *dynamic* | directory layout; placeholders: `{artist}`, `{album}`, `{collection}`, `{title}`, `{tracknumber}`. Empty by default: albums get a directory named after the album, playlists after the playlist, single tracks go straight into `--dir` |
| `--file-template` | `{tracknumber}. {title} - {artist}` | filename pattern; must not contain path separators. For playlists the number is the position in the playlist, for albums the position on the album. Numbers are zero-padded to the collection's size: a 200-track playlist numbers `001`–`200`, a 20-track album `01`–`20` |
| `--limit` | none | download at most this many tracks this run; everything is still matched and queued, and re-running continues with the rest |
| `--db` | `<dir>/.queue.sqlite3` | queue database location |
| `--no-lyrics` | off | skip saving `.lrc` lyric files |
| `--tidal` | off | after downloading from Qobuz, replace the file with a Tidal copy when Tidal has strictly higher quality — see [Tidal upgrades](#tidal-upgrades) |

*Omit all URLs to resume whatever is pending in the queue database.*

### Progress output

Everything goes to the terminal: summary lines on stdout, progress and warnings on stderr. While matching a playlist you see each track as it is processed (`[7] Artist - Title` and what it matched to); downloads print `done:`/`failed:` per track. Pass `--verbose` for details — every API page fetch and download retry.

## Lyrics

By default every downloaded track also gets a synced **`.lrc`** sidecar file next to the audio — `01 - Rehab.flac` gets `01 - Rehab.lrc` — sourced from [LRCLIB](https://lrclib.net) (free, no account). Lyrics lookup never blocks a download: if no synced lyrics exist for a track, only the audio is saved. Use `--no-lyrics` to disable.

## Quality: what you get

You always get the **best audio the track actually offers**, never more, never less:

- The tool requests Hi-Res by default (24-bit, up to 192 kHz)
- If the track's master is lower (e.g. 24-bit/44.1 kHz) you get that, and the output says so:
  `done: The Weeknd - Blinding Lights (24/44.1, fell back from hires_192)`
- Pure lossless FLAC only — MP3 is never downloaded (use `--quality cd` as a bandwidth cap)

## Tidal upgrades

The two catalogs don't always carry the same master. Pass `--tidal` and after each Qobuz download the tool checks Tidal for the same track and, if Tidal's copy is strictly higher quality, downloads it and replaces the Qobuz file in place (the `.lrc` sidecar stays):

```bash
qobuz-downloader URL --tidal --dir ~/Music
```

The check is deliberately narrow — [research](docs/research/2026-09-09-tidal-quality-comparison.md) against a real 1000-track playlist found upgrades **only** happen when Qobuz delivered 24-bit at 44.1 or 48 kHz (60% of those had HiRes FLAC on Tidal); for 16/44.1 and 24-bit >48 kHz results the check is skipped entirely. The Tidal stream's real bit depth/sample rate is read back from the downloaded FLAC, and the Qobuz file is kept unless the Tidal copy is genuinely better — so a HiFi (non-Plus) subscription can never make things worse.

Requirements and flow:

- A Tidal account with HiRes FLAC access (HiFi Plus tier); without one, `--tidal` simply never replaces anything
- First use (or expired token) prints a `link.tidal.com/XXXXX` URL — open it in a browser, approve, and the tool continues; the token is cached in `~/.cache/qobuz-downloader/tidal.json` and refreshed automatically
- Upgrades show up in the progress output as `done: Artist - Title (24/96, upgraded from Tidal)`
- A Tidal failure never fails the track: the Qobuz file is already on disk
- Tracks already completed by earlier runs are not retro-upgraded; delete the file and re-run the command to redo one

## Queue, retries, interruptions

State lives in `.queue.sqlite3` inside your download directory:

- Tracks already downloaded are **skipped** on re-runs — safe to re-run any command
- Interrupted downloads leave a `.part` file and **resume** from where they stopped (fresh stream URL fetched automatically; if the server won't resume, it restarts cleanly)
- Failed tracks stay marked failed and are **retried the next time you run any command** that re-adds them
- Every file is validated as a real FLAC before being renamed into place

### Resuming after a disconnect

If your internet drops mid-playlist (say 50 of 1000 downloaded), just run the **same command again**:

```bash
qobuz-downloader https://open.spotify.com/playlist/6Nq4BLzd6vTMIye1kkUhBN --dir ~/Music
```

The 50 completed tracks are skipped, the interrupted one resumes from its `.part`, and the rest continue.

To resume **without re-fetching and re-matching the playlist** (~10 minutes saved on a 1000-track list), omit the URLs entirely:

```bash
qobuz-downloader --dir ~/Music
```

This re-queues failed tracks and downloads everything still pending from the queue database.

**Circuit breaker:** if 5 tracks fail in a row, the run stops instead of churning through the whole list while the network is down. Fix your connection and re-run — the queue remembers exactly where it left off.

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests
```

## Terminal UI

A Textual front end lives in [`tui/`](tui/README.md) — search, paste Qobuz or
Spotify URLs, watch live per-track progress, hold/resume individual tracks,
and play (stream or downloaded) right in the terminal.

Design docs: [`CONTEXT.md`](CONTEXT.md) (domain glossary) and [`docs/adr/`](docs/adr/) (decisions).

## Disclaimer

For educational purposes and personal use with your own Qobuz subscription. By using this tool you accept the [Qobuz API Terms of Use](https://static.qobuz.com/apps/api/QobuzAPI-TermsofUse.pdf). Not affiliated with Qobuz or Spotify.
