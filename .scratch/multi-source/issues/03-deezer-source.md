# 03 — Deezer source: public matching + ARL streaming

Status: done

## Why

Deezer's catalog overlaps Qobuz's least where the user needs it most:
tracks missing from Qobuz/Tidal. Deezer is the fallback that makes
"the track eventually must be downloaded" true in practice.

## Scope — all landed

- [x] `LiveDeezer` implementing the `Source` protocol:
  - `search_tracks`: `api.deezer.com/search` — no auth
  - `qualities`: gw-light `song.getData` FILESIZE_FLAC/MP3_320 +
    account rights (`web_sound_quality`) → ladder
  - `stream`: license-token `media.deezer.com/v1/get_url` (researched
    live — see `docs/research/2026-09-12-deezer-streaming.md`) +
    streamed Blowfish-stripe decryption via a `byte_source` carried
    in the Stream (ADR 0002)
  - `cover_url`: `ALB_PICTURE` → `e-cdns-images.dzcdn.net`
- [x] `pycryptodome` is now a required dependency
- [x] ARL via `DEEZER_ARL` env; missing ARL ⇒ Deezer still matches,
  downloads fail with a clear reason; `--source deezer` without ARL is
  a hard error with instructions
- [x] 404/geo-restricted (error 2002)/unlicensed-format paths fail
  cleanly (Failed outcome, never a crash); resume restarts cleanly
  (striped cipher can't mid-file resume — documented in ADR 0002)
- [x] Engine honors `stream.byte_source` when a platform needs a
  custom transport

## Done when

- [x] public-search matching works without credentials (unit tests,
  mocked HTTP — `tests/test_deezer.py`, 12 tests)
- [x] a live ARL downloads a full FLAC end to end, validated by
  mutagen, with tags + cover art written (Leprous "Dare You",
  deezer:417538262 → valid 16/44.1 FLAC, 405.4 s, Vorbis tags + 130 KB
  cover)
- [x] the 404/geo-restricted/readable=false paths fall back cleanly

Live catalog probe: Deezer rescues 3 of the 5 tracks still unmatched
after Tidal (Broken Iris "Where Butterflies Never Die", Estas Tonne
"Spirit of Time (Live)", Break My Fucking Sky "Seven"); only Garood
"The Other Side - Instrumental" and Robot 29 "Bia Benevisim" are on
no platform. Note: خاکستر & co are NOT on Deezer — Tidal covers those.

Blocked by: 01 (done)
