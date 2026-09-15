# Multi-source downloads — Qobuz / Tidal / Deezer

Status: done (Deezer research + implementation verified live 2026-09-12)

## Problem

A Spotify playlist matched against Qobuz leaves tracks Unmatched whenever
Qobuz doesn't carry them (about 30 of 1110 tracks on the user's live
playlist — Persian rock, small post-rock bands, one-off reimaginings). An
Unmatched track is only reported, never queued, so it is silently *not
downloaded*. The user's requirement: **a wanted track must eventually be
downloaded** — if one platform doesn't have it, another should.

## User-facing contract

- `--source {best,qobuz,tidal,deezer}` selects where downloads come from:
  - `qobuz` — today's behavior, single catalog (default)
  - `tidal` / `deezer` — that catalog alone
  - `best` — search every available catalog and download the highest
    Quality copy; Unmatched-on-Qobuz tracks fall back to the other
    catalogs
- `--allow-lossy` opts into MP3 320 / Deezer 128 tiers when no lossless
  copy exists anywhere (default off: FLAC only, as today)

### What each platform can provide

| Platform | Match metadata | Audio |
|---|---|---|
| Qobuz | search API (auth) | FLAC up to 24/192 (subscription) |
| Tidal | search API (partner token) | FLAC up to 24/192; HiRes needs paid tier |
| Deezer | `api.deezer.com` search (no auth) | FLAC 16/44.1 + MP3 320; needs `DEEZER_ARL` (subscription cookie) |
| Spotify | (metadata source for Match — already implemented) | **no audio** — Spotify serves no downloadable stream; downloads must come from the other platforms |

Spotify as an *audio* source is out of scope by design: it has no
download endpoint, and stream-ripping it is DRM circumvention. Its role
stays what it already is: the playlist/track metadata the Match runs
against. (Track ids keep the `spotify:` prefix for metadata-only rows.)

## Architecture

Track ids become source-qualified: `tidal:<id>`, `deezer:<id>`; bare
numeric ids keep meaning Qobuz (back-compat with existing queue DBs).

New `source/` package beside `qobuz/` and `tidal/`:

- `Source` protocol: `search_tracks(query, limit) -> list[Track]`,
  `qualities(track) -> list[Quality]`, `stream(track, quality) -> Stream`,
  `cover_url(track) -> str | None`. `Qobuz` already fits; `Tidal` gains
  search/qualities; `LiveDeezer` implements it with the gw-light API +
  ARL.
- `Catalog` (in `match/`): resolves a Spotify track on one or more
  Sources, scoring candidates per source with the existing
  `_score_track`, and stamping the winning candidate with its
  source-prefixed id. `--source best` = search all, pick the highest
  Quality (ties: highest match score, then provider order qobuz → tidal
  → deezer); other values = search that source first and fall back to the
  rest only when the track is not there (the "eventually downloaded"
  guarantee).
- `Engine` takes a source registry keyed by prefix and dispatches
  `qualities`/`stream`/`cover_url` by parsing the Track id. Validation
  stays FLAC-or-nothing for lossless tiers; with `--allow-lossy` the
  engine accepts MP3 (mutagen check) and names files `.mp3`.

### Deezer streaming notes (researched, needs a live ARL to finish)

- gw-light (`/ajax/gw-light.php?method=song.getData`, ARL cookie) yields
  `FILESIZE_MP3_320` / `FILESIZE_FLAC` per track
- stream URL: `https://e-cdns-proxy-{md5origin[0]}.dzcdn.net/mobile/1/{md5origin}?q=…`
  license-gated; 320/FLAC bodies are Blowfish-CBC encrypted per 2048-byte
  chunk with the standard deemix key derivation (`md5(sng_id) ⊕ md5(arlc)`
  …), so `pycryptodome` becomes a dependency of the `deezer` extra
- ticket 03 captures the unknowns (exact license flow, chunk pattern) as
  a research step against a real ARL

## Issues

- 01-source-protocol — done: Source protocol, id prefixes, Engine dispatch
- 02-tidal-source — code-complete: Tidal search/qualities as a full Source
  (live stream smoke test pending the user's one-time Tidal device login)
- 03-deezer-source — done: LiveDeezer via license-token get_url +
  Blowfish-stripe decryption (ADR 0002), live end-to-end verified
- 04-cli-platform-selection — code-complete: `--source` / `--allow-lossy`,
  credential setup, README + CONTEXT.md updates
