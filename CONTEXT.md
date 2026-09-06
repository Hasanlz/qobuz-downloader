# Qobuz Downloader

Saves lossless audio files from a Qobuz subscription to the local disk.

## Language

### Catalog

**Item**:
Anything addressable by a Qobuz URL: a Track, Album, Artist, or Playlist.
_Avoid_: resource, entity

**Track**:
A single piece of music on Qobuz; the smallest downloadable unit.
_Avoid_: song

**Album**:
A release containing Tracks.
_Avoid_: release, record

**Artist**:
A person or group on Qobuz. Downloading an Artist means downloading their Albums.

**Playlist**:
An ordered list of Tracks. Not audio itself — downloading a Playlist means downloading its Tracks.

### Audio

**Quality**:
Which of the available audio formats a Track is delivered in. A ladder from lowest to highest: Lossy, CD quality, Hi-Res.
_Avoid_: bitrate, format

**Lossless**:
FLAC audio. Both CD quality and Hi-Res are Lossless.
_Avoid_: hi-fi, hifi (ambiguous — could mean any Lossless)

**CD quality**:
16-bit / 44.1 kHz FLAC.

**Hi-Res**:
FLAC above CD quality, up to 24-bit / 192 kHz.
_Avoid_: hi-fi, hifi

**Lossy**:
MP3 320 kbps audio.

### Intake

**Qobuz URL**:
A URL identifying a Qobuz Item directly. Needs no Match.

**Spotify URL**:
A URL identifying a track, album, or playlist on Spotify. Identifies no Qobuz Item until Matched.

**Match**:
The Qobuz Item found to correspond to a Spotify URL's item. Matching can fail.
_Avoid_: resolve, convert, translate

**Unmatched**:
A Spotify item with no satisfactory Match. Reported to the user and marked in the Queue — never silently skipped.

### Downloading

**Download**:
Retrieving a Track at a chosen Quality and saving it as a local audio file.
_Avoid_: stream-rip, rip, capture

**Subscription**:
The user's Qobuz membership (e.g. Studio). It caps the highest Quality a Track can be downloaded at.

**Preferred Quality**:
The Quality a Download requests. Hi-Res by default; the user may cap it (e.g. to CD quality).

**Fallback**:
Using a lower Quality than the Preferred Quality because the Track or Subscription doesn't offer it. The user is always told when a Download falls back.
_Avoid_: downgrade notice, quality drop

**Partial download**:
A local file for a Track that exists on disk but is not a complete, valid Download. Treated as a failure.

**Queue**:
The persistent list of wanted Tracks and their download status (pending, complete, failed), surviving across runs.

**Naming template**:
A user-defined pattern, with placeholders like artist, album, and title, that determines the names of downloaded files and the directories they live in.
_Avoid_: format string, naming scheme
