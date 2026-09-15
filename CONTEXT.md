# Qobuz Downloader

Saves lossless audio files from a Qobuz (or Tidal) subscription to the local disk.

## Language

### Catalog

**Source**:
A download platform: Qobuz, Tidal, or Deezer. Every Track id in the
Queue carries (or implies) its Source — `tidal:233554206`,
`deezer:73997802`; bare ids are Qobuz.
_Avoid_: provider, service

**Source order**:
The preference order Sources are searched in: the chosen platform first
(`--source`), the rest as Fallback. A Source joins only when it has
credentials (can stream); `best` means: search all credentialed
Sources, download the highest Quality.

**Item**:
Anything addressable by a platform URL: a Track, Album, Artist, or
Playlist. Qobuz, Tidal and Deezer URLs name their own Items directly;
Spotify URLs identify nothing until Matched.
_Avoid_: resource, entity

**Track**:
A single piece of music on a Source; the smallest downloadable unit.
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
A URL identifying a track, album, or playlist on Spotify. Identifies no Qobuz Item until Matched. Spotify serves no downloadable audio — it is a metadata source for Match only.

**Match**:
The Track found to correspond to a Spotify URL's item. Matching can fail.
_Avoid_: resolve, convert, translate

**Unmatched**:
A Spotify item with no satisfactory Match on any Source. Reported to the user and marked in the Queue — never silently skipped.

### Downloading

**Download**:
Retrieving a Track at a chosen Quality and saving it as a local audio file.
_Avoid_: stream-rip, rip, capture

**Subscription**:
The user's membership (e.g. Qobuz Studio, Tidal HiFi). It caps the highest Quality a Track can be downloaded at.

**Preferred Quality**:
The Quality a Download requests. Hi-Res by default; the user may cap it (e.g. to CD quality).

**Fallback**:
Using something other than the first choice — a lower Quality than the
Preferred Quality, or another Source than the chosen one — because the
first choice doesn't offer the Track. The user is always told when a
Download falls back.
_Avoid_: downgrade notice, quality drop

**Partial download**:
A local file for a Track that exists on disk but is not a complete, valid Download. Treated as a failure.

**Queue**:
The persistent list of wanted Tracks and their download status (pending, complete, failed), surviving across runs.

**Naming template**:
A user-defined pattern, with placeholders like artist, album, and title, that determines the names of downloaded files and the directories they live in.
_Avoid_: format string, naming scheme

**Lyrics file**:
A sidecar .lrc file, timestamped line by line, saved next to the audio of a Track when lyrics are found for it.

**Resume**:
Running the tool without URLs. Drains the Queue's pending Tracks, re-queuing failed ones, without touching the source playlists again.
