# Quaver — Terminal UI

Status: ready-for-human

## Spec

A Textual front end for the downloader, living in `tui/` as a self-contained
package (`pip install -e "tui[big-playlists]"`). It composes the existing
library pieces rather than re-implementing them:

- `LiveQobuz` for auth, search, streaming and quality resolution
- `Engine` + `HttpByteSource` for downloads; a wrapping `ByteSource` reports
  byte progress and can abort mid-track (raising `KeyboardInterrupt`, which the
  Engine does not catch) so a paused download keeps its `.part` file and the
  Engine's Range-resume picks up from the same byte offset
- `SqliteQueue` as source of truth; the UI opens its own short-lived
  connections for writes and reads row state directly for display
- `Matcher` for Spotify URLs; match errors surface as Unmatched rows with the
  reason — never a crash (spotapi's exception family is caught in workers)
- `Naming`, `LrcLib` for file layout and lyrics

## Interface

- Login: email/password or token; remembered sessions auto-login with retry;
  logout wipes credentials
- Queue tab: live status per Track, global pause, retry failed and stuck rows,
  per-track hold (persisted in a `tui_holds` sidecar table)
- Search tab: Qobuz search plus URL preview (Find shows the Match before any
  Download; Enter on a found Track streams it without downloading, `d` queues it)
- Player bar: plays downloaded files or streams (ffplay backend, mpv when
  installed), seek bar, RMS-reactive spectrum (ffmpeg astats reader)

## Issues

- 01-ui-screens — login/queue/search/log screens, settings modal
- 02-download-worker — worker thread, progress, pause/hold/resume, retry stuck
- 03-player — streaming playback, seek bar, spectrum
