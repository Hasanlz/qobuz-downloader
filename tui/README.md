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

## Setup — one command

**Windows (PowerShell):**

```powershell
powershell -c "irm https://raw.githubusercontent.com/Hasanlz/qobuz-downloader/main/bootstrap.ps1 | iex"
```

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/Hasanlz/qobuz-downloader/main/bootstrap.sh | bash
```

Each one downloads the project (into `~/quaver`), creates a virtual
environment, installs everything, walks you through your Qobuz credentials and
settings, wires up the `quaver` command for your OS, and ends with a live
sign-in test. Re-run any time — saved values are kept. The scripts honor
`QUAVER_REPO_URL` / `QUAVER_REF` / `QUAVER_HOME`, and forward extra arguments
to the wizard (`--defaults`, `--check`, `--skip-install`, `--no-test`).
Before this lands on `main`, add `QUAVER_REF=<branch>` to the environment.

### Manual (any OS, from a clone of this repository)

```powershell
# Windows (PowerShell)
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e .
pip install -e tui
quaver
```

```bash
# macOS / Linux
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -e tui
quaver    # in .venv/bin — add it to PATH, or:
ln -s "$PWD/.venv/bin/quaver" ~/.local/bin/quaver
```

Without a bootstrap one-liner, run the wizard from a clone: `python wizard.py`
(Windows) / `python3 wizard.py` (macOS/Linux).

## Requirements

Requires Python 3.12+ and an active Qobuz subscription (free accounts cannot
download; Studio for Hi-Res).

## Run

```bash
quaver                     # downloads to ~/Music/Qobuz (configurable on login screen)
quaver --dir ~/music/flac  # explicit download directory
quaver --token TOK --app-id ID --app-secret SECRET   # skip the login screen
```

Credentials: log in on the first screen (remember-me is on by default — you
won't be asked again), or export `QOBUZ_USER_AUTH_TOKEN` + `QOBUZ_APP_ID` +
`QOBUZ_APP_SECRET` (or `QOBUZ_EMAIL` + `QOBUZ_PASSWORD`) before launching to
skip it. On Windows, set them with `$env:QOBUZ_EMAIL = "..."` in PowerShell.

## Audio playback

The player bar needs a system audio tool — the wizard tells you whether it
found one:

| Platform | Command |
| --- | --- |
| Windows | `winget install Gyan.FFmpeg` (or `winget install mpv`) |
| macOS | `brew install ffmpeg` (or `brew install mpv`) |
| Debian/Ubuntu | `sudo apt install ffmpeg` (or `sudo apt install mpv`) |

`mpv` unlocks volume control; with only `ffplay` you get play/stop (and pause
on macOS/Linux). Playback streams tracks straight from Qobuz — no download
needed.

## Proxy note

`socks://` proxy environment variables (v2rayN-style exports) are normalized
to `socks5://` automatically at startup; httpx rejects the bare `socks://`
scheme on its own.

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
