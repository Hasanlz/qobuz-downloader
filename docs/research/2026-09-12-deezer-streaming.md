# Deezer streaming — live research 2026-09-12

Question: how does a `LiveDeezer` source resolve and download a FLAC,
given a valid user ARL cookie? Verified live against the gw-light API
and the media delivery service; cross-checked with orpheusdl-deezer,
kmille/deezer-downloader, pleezer, deezspot, streamrip.

## Findings

1. **Session bootstrap** — `POST /ajax/gw-light.php` with the ARL
   cookie, `method=deezer.getUserData`, empty `api_token`. Returns:
   - `results.checkForm` — the CSRF `api_token` every later gw-light
     call needs (empty/foreign token ⇒ `VALID_TOKEN_REQUIRED`)
   - `results.USER.OPTIONS.license_token` — the media authorization
     credential, with `expiration_timestamp`
   - `results.USER.OPTIONS.web_sound_quality` — format rights:
     `lossless: true` is required for FLAC
2. **Track metadata** — `song.getData` (`{"sng_id": id}`) returns
   `TRACK_TOKEN` (+ `TRACK_TOKEN_EXPIRE`), `FILESIZE_FLAC`,
   `MD5_ORIGIN`, `MEDIA_VERSION`, `FALLBACK`.
3. **Media URL** — `POST https://media.deezer.com/v1/get_url` (no
   cookie needed; license-token authorized):

   ```json
   {"license_token": "...",
    "media": [{"type": "FULL",
               "formats": [{"cipher": "BF_CBC_STRIPE", "format": "FLAC"}]}],
    "track_tokens": ["<TRACK_TOKEN>"]}
   ```

   URL at `data[0].media[0].sources[0].url` (host
   `cdnt-*.dzcdn.net`, Akamai `hdnea` token, time-limited).
   `data[0].errors[0].code == 2002` ⇒ geo-block/rights — retry with
   the `FALLBACK` track's token. `formats` is an ordered fallback
   list (request FLAC → MP3_320 → … in one call).
4. **Legacy route is dead** — `e-cdns-proxy-*.dzcdn.net` is NXDOMAIN;
   the md5-origin URL and its AES `jo6aey6haid2Teih` key are defunct.
5. **Decryption (BF_CBC_STRIPE)** — every 2048-byte block whose index
   `% 3 == 0` (and which is a full block) is Blowfish-CBC encrypted;
   a trailing partial block never is. Key = for
   `i in 0..15: md5(str(SNG_ID)).hexdigest()[i] ^ [i+16] ^ b"g4el58wc0zvf9na1"[i]`;
   IV fixed `00 01 02 03 04 05 06 07`; cipher re-initialized per block.
   FLAC is encrypted exactly like MP3.
6. **Public search** — `api.deezer.com/search?q=...` needs no auth
   and returns id/title/artist/album/duration per track.

## Live verification (this session)

- Leprous "Dare You" (`sng_id 417538262`): song.getData →
  FILESIZE_FLAC 50 953 076 → get_url FLAC source → download 50 953 076
  bytes → Blowfish-decrypt → valid 16-bit/44.1 kHz FLAC, 405.4 s.
- Catalog reality: Deezer does **not** carry خاکستر / طلسم / Skylar
  Grey "Twisted" (0 hits) but does carry Leprous "Dare You", Orbit
  Culture "Saw" — Deezer is a third fallback, not the Persian
  rescuer (Tidal already covers those).

## Consequences for the implementation

- `LiveDeezer` implements the `Source` protocol: public search for
  matching, gw-light for qualities (web_sound_quality rights +
  FILESIZE_* presence), get_url + streamed Blowfish decrypt for the
  download itself.
- `pycryptodome` becomes a required dependency (small, pure-wheel).
- The engine's byte source must decrypt after download; because the
  engine streams bytes through `ByteSource.stream`, decryption is
  cleanest at the Deezer source boundary: the media URL is fetched
  and decrypted chunk-by-chunk *inside* a wrapping ByteSource so
  `.part` resume and length validation still work (length = full
  encrypted size; decryption preserves length, so byte accounting is
  unaffected — resume on a striped cipher is impossible though, so a
  resumed deezer download restarts cleanly).
- Retry policy: error 2002 (geo/rights) → try FALLBACK track;
  expired CDN `hdnea` → re-run get_url.

Open (accepted): resume doesn't work for Deezer downloads (the
 Blowfish stripe depends on absolute block position; a resume would
 need re-downloading from block 0). `.part` files just restart.
