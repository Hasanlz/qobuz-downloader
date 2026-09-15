# 2. Deezer streams through a decrypting ByteSource adapter

Date: 2026-09-12

## Status

Accepted

## Context

Deezer full-track media (FLAC, MP3_320) is delivered
Blowfish-encrypted: every third 2048-byte block is
`BF_CBC_STRIPE`-encrypted with a per-track key derived from the song
id (`docs/research/2026-09-12-deezer-streaming.md`). The engine's
download loop streams bytes through its `ByteSource` abstraction and
resumes partial (`.part`) downloads via HTTP Range requests.

Three integration options existed:

1. Teach the engine about encrypted downloads (a `decrypt` step after
   streaming) — couples the generic engine to one platform's crypto.
2. Download to memory/temp file inside `LiveDeezer`, return a
   `file://`-like URL — breaks the engine's streaming/resume model.
3. A `DecryptingByteSource` that wraps the engine's byte source for
   deezer tracks: HTTP on the outside, plaintext FLAC on the inside.

## Decision

`LiveDeezer.stream(track, quality)` resolves the media URL via the
license-token `get_url` endpoint and returns a `Stream` whose bytes are
decrypted lazily by a wrapping ByteSource. The engine never learns
about Blowfish: it downloads, validates (mutagen), tags, and resumes
exactly as for Qobuz/Tidal.

Because the stripe depends on absolute block position, a resumed
Deezer download cannot decrypt correctly — so the adapter returns
`status != 206` for range requests (the engine's existing
"server-ignores-range → restart cleanly" path handles it).

`pycryptodome` becomes a required dependency.

## Consequences

- Engine stays platform-agnostic; crypto lives at the Deezer boundary.
- Deezer downloads never resume mid-file (they restart); acceptable
  for a fallback platform whose downloads are single-digit MBs/min.
- Length validation uses the encrypted size, which equals the
  plaintext size (Blowfish-CBC here is length-preserving on the
  striped blocks), so incompleteness detection is unaffected.
