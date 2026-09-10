# Quaver

**Quaver** — a terminal UI for [qobuz-downloader](https://github.com/Hasanlz/qobuz-downloader):
search Qobuz, paste Qobuz or Spotify URLs, and download lossless audio with a live
queue view — all without leaving the terminal.

## Features

- **Login screen** — email/password (app credentials scraped automatically) or
  `QOBUZ_USER_AUTH_TOKEN` + `QOBUZ_APP_ID` + `QOBUZ_APP_SECRET`. Optional
  "remember me" (on by default) persists credentials to
  `~/.config/quaver/settings.json` — next launches skip the login screen
  entirely, retrying transient network errors 3× before giving up. **Log out**
  (button in the top bar) clears them and returns to the login screen.
- **Queue tab** — live table of every track with status glyph, per-track progress
  and failure reasons. Global pause (`s`), retry failed/stuck (`r`).
- **Per-track hold** — press `h` (or Enter) on a pending row to put that track on
  hold (⏸): the worker skips it and downloads everything else. `h`/Enter again
  releases it. Holds survive restarts (stored in the queue database).
- **Player bar** — plays downloaded files *and streams tracks straight from
  Qobuz without downloading* (Find a song, press Enter). Seek bar shows how far
  into the song you are; a live spectrum (real RMS levels read from the audio)
  dances with the music. `space`/▶ toggles pause. Backed by `mpv` when
  installed, `ffplay` otherwise. Vol -/Vol + adjust volume (mpv).
- **Toasts** — a toast pops when tracks are queued, unmatched, retried, or held.
- **Search spinner** — a loading animation runs while a Qobuz search is in flight.

## Install

Proxies: `socks://` proxy env vars (v2rayN style) are normalized to
`socks5://` automatically at startup.

Requires Python 3.12+ and an active Qobuz subscription (free accounts cannot
download).

```bash
# from a checkout of this repository:
pip install -e "tui[big-playlists]"
# make `quaver` available on PATH (adjust venv path to taste):
ln -s "$(pip show quaver | awk '/Location/{print $2}')/../bin/quaver" ~/.local/bin/quaver
```

## Run

```bash
quaver                     # downloads to ~/Music/Qobuz (configurable on login screen)
quaver --dir ~/music/flac  # explicit download directory
# skip the login screen (paste works normally in your shell):
quaver --token TOK --app-id ID --app-secret SECRET
quaver --email you@example.com --password SECRET
```

Credentials: log in on the first screen, or export
`QOBUZ_USER_AUTH_TOKEN` + `QOBUZ_APP_ID` + `QOBUZ_APP_SECRET` (or
`QOBUZ_EMAIL` + `QOBUZ_PASSWORD`) before launching to skip it.

## Editing and paste

Text fields support Backspace/Delete, `Ctrl+U` (clear line), arrows, Home/End.
Pasting: **hold Shift while pasting** (`Shift+Insert` or `Shift+right-click`) —
this bypasses the app's mouse handling and the text arrives as a terminal
paste. Plain `Ctrl+V` only pastes text previously copied *inside* the app
(the app cannot read the OS clipboard), and plain right/middle-click are
forwarded to the app as mouse events. For long tokens, pasting into the shell
with the `--token` flags above is the smoothest path.

## Keys

| Key | Action |
| --- | --- |
| `s` | Pause / resume downloads |
| `r` | Retry failed or stuck tracks |
| `/` | Jump to search |
| `,` | Settings |
| `enter` | Download URL / run search / queue selected result |
| `down` / `up` | Move between login fields |
| `Backspace` / `Delete` | Erase left / right of cursor |
| `Ctrl+U` | Clear the field |
| `Shift+paste` | Paste from system clipboard into a field |
| `space` | Play/pause; plays the highlighted track when idle |
| `enter` (on found track) | Stream-play it without downloading |
| `h` | Hold / release the highlighted queue row |
| `d` | Download the highlighted preview/search row |
| `enter` (on queue row) | Play completed track, or hold/resume it |

## Install once, run anywhere

The installer symlinks the executable into `~/.local/bin` (already on your
`PATH`), so plain `quaver` works from any directory.

## Layout

- `src/quaver/app.py` — Textual app, main screen (queue/search/log tabs),
  player bar, settings modal.
- `src/quaver/login.py` — login screen and credential plumbing.
- `src/quaver/player.py` — audio backends: `mpv` (JSON IPC) with `ffplay`
  fallback (SIGSTOP/SIGCONT pause).
- `src/quaver/spectrum.py` — live loudness bars (ffmpeg astats RMS reader).
- `src/quaver/holds.py` — per-track hold store (sidecar table in the queue DB).
- `src/quaver/worker.py` — `DownloadWorker` thread: owns its own
  `SqliteQueue` connection, drains pending tracks through the shared
  `Engine`, streams progress via `post_message`, honours pause and per-track
  holds (a paused download keeps its `.part` file and resumes at the byte offset).
- `src/quaver/settings.py` — JSON settings with credential redaction.

Tests: `pytest tui/tests` (Textual Pilot drives the real app against fake Qobuz/byte
sources; download/pause/retry cycle, per-track holds, player lifecycle, search
spinner, and login-navigation flows).
