# 02 — Tidal as a full download Source

Status: code-complete (live smoke test pending user's Tidal login)

## Why

`LiveTidal` already logs in (device OAuth, cached in
`~/.cache/qobuz-downloader/tidal.json`), searches (partner token) and
resolves HiRes FLAC streams — but only as the `--tidal` upgrade path.
As a primary/fallback source it needs the full `Source` surface.

## Scope

- [x] `search_tracks(query, limit) -> list[Track]` (search endpoint,
  partner token, no login needed); ids stay native in the client, the
  Catalog stamps `tidal:` at match time
- [x] `qualities(track)`: `tracks/{id}` mediaMetadata tags →
  `HIRES_LOSSLESS` ⇒ [LOSSY, CD, HIRES_96, HIRES_192], else
  [LOSSY, CD]
- [x] `cover_url(track)`: `tracks/{id}` → `cover` id →
  `resources.tidal.com/images/{uuid}/orig.jpg`
- [x] `TidalSource` adapter (`source/_tidal.py`) strips the prefix and
  speaks native ids to `LiveTidal`
- [x] `--source tidal` runs; `--source best` searches qobuz + tidal and
  keeps the highest-quality copy (Catalog.resolve_best)
- [x] Fallback interplay: `_maybe_upgrade` skips tracks already
  downloaded from Tidal (no self-upgrade)
- [x] `stream()` raises a clear "login needed" when there is no cached
  login, so tidal tracks can queue before the one-time login

## Done when

- [x] unit tests with a mocked HTTP layer (search → qualities → stream;
  `tests/test_source.py`, `tests/test_match.py`)
- [ ] a live smoke test (needs the user's Tidal login) downloads a
  Tidal-only track end to end — **blocked on user running the one-time
  device login**

Live verification so far (partner token, no login): 23 of the 28
Qobuz-missing playlist tracks match on Tidal, including خاکستر /
طلسم / گل مرداب (Hamed Mohammadi), each at score 1.00; queued with
`tidal:` ids by the catalog.

Blocked by: 01 (done)
