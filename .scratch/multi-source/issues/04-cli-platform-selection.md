# 04 — CLI platform selection and docs

Status: code-complete (live smoke tests pending user's Tidal login)

## Why

The user picks a platform per run: which catalog to download from, and
whether to hunt everywhere for the highest quality. Today no such flag
exists — the run is Qobuz-only.

## Scope

- [x] `--source {best,qobuz,tidal}` — default `qobuz` (qobuz → tidal
  fallback); `best` searches both and keeps the highest-quality copy.
  `deezer` joins the choices when ticket 03 lands.
- [x] `--allow-lossy`: permit the MP3 tier when no lossless copy exists
  on any source; without it, lossy-only matches are not queued
  (Catalog checks the source ladder; Engine honors it at stream time)
- [x] Credentials: Tidal login is the existing device flow, cached in
  `~/.cache/qobuz-downloader/tidal.json`; a missing login never aborts
  a run — Tidal still matches, downloads report "tidal login needed"
  with instructions. `--source tidal` without a login is a hard error
  with a how-to-fix message.
- [x] Progress output: `done: Artist - Title (16/44.1, from tidal)` —
  winning source visible
- [x] README: new "Sources" section (platform table, quality ceilings,
  credentials, what `best` does, Spotify-is-metadata-only rationale)
- [x] CONTEXT.md glossary: **Source**, **Source order**, extended
  **Fallback** (now covers cross-platform), updated Track/Match/
  Unmatched/Subscription wording

## Done when

- [ ] `--source tidal …` runs a playlist end to end (live smoke test)
- [ ] `--source best` queues a Qobuz-missing track from Tidal (live)
  — rematch4 run in progress; already verified via partner-token probe
  that 23/28 missing tracks are on Tidal
- [x] README/CONTEXT updated

Blocked by: 02 (code-complete), 03 (not started — needs ARL)
