# 01 — Source protocol, id prefixes, Engine dispatch

Status: done

## Why

The Engine, Queue and Matcher are all hard-wired to `Qobuz`: `Engine`
takes a `Qobuz`, `Track.id` in the queue DB is a bare Qobuz id, and
`SqliteQueue` is schema-keyed on it. Before any second audio platform
can exist, something has to translate "a queued Track" into "the right
platform client" without the Engine knowing which platform it is talking
to.

## Scope

- Define the `Source` protocol (search_tracks / qualities / stream /
  cover_url) in a new `qobuz_downloader/source/` package; `Qobuz`
  (the existing interface) satisfies it — adopt, don't duplicate.
- Track id convention: `tidal:<id>`, `deezer:<id>`; bare ids mean Qobuz
  (existing DBs keep working). Parsing helper
  `source.parse(track_id) -> (source_name, native_id)` + tests.
- `Engine` accepts a source registry; `qualities`/`stream`/`cover_url`
  calls dispatch by parsed prefix. The `--tidal` upgrade path stays
  Qobuz-specific (it only fires after a Qobuz download).
- Non-FLAC validation: engine `_validate` accepts MP3 when the download
  is a lossy tier (mutagen MP3); FLAC otherwise. Extension mapping per
  quality already exists (`_EXTENSIONS`).

## Done when

- [x] `Engine.download` works with a registry containing only the Qobuz
  adapter and passes the existing engine tests unchanged (ids stay bare
  there)
- [x] new unit tests cover prefix parsing and dispatch
  (`tests/test_source.py`, `tests/test_match.py` catalog integration)
- [x] no behavior change for a plain `qobuz-downloader URL` run
  (128 passed; TUI signatures untouched)

Implementation notes: `source/_base.py` holds the protocol + parse/
qualify to avoid the package-cycle (`_qobuz.py` imports it); `_tags.py`
gained ID3/APIC writing for `.mp3` outputs; `Engine.allow_lossy` opts
into the lossy tier at download time.
