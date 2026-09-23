# Live Queue diagnosis — 2026-09-24

Status: captured; production Queue was not modified by this diagnosis.

## Method

- Loaded Qobuz credentials from the external credentials file without recording their values.
- Replayed the current Spotify Playlist with `--limit 0` into `/tmp/opencode/current-replay.sqlite3`; no audio was downloaded.
- Ran the read-only position inventory against the replay DB.
- Probed the 31 missing positions with the same Qobuz/Deezer matching and scoring path. The probe was rerun after fixing two temporary recorder bugs; only the corrected run is reported here.

## Results

- Spotify positions: **1118**
- Replay Queue rows/distinct positions: **1087 / 1087**
- Missing positions: **31**
- Corrected probe classifications: **1 matched**, **21 rejected for quality**, **9 below threshold**, **0 search errors**.
- The one matched missing position is a repeated `April Rain - My Silent Angel` occurrence. Its source Track was already queued at position 607, so the existing source-id dedup skipped position 729.
- Tidal was not available, so a Source-unavailable result is not evidence of global catalog absence.

## Gap evidence

| Position | Classification | Spotify Track | Best observed candidate | Score |
| ---: | --- | --- | --- | ---: |
| 90 | below-threshold | Skylar Grey - Twisted | qobuz — Various Artists - Twisted | 0.000 |
| 193 | rejected-quality | Leprous - Dare You | deezer — Leprous - Dare You | 1.000 |
| 195 | rejected-quality | Clouds - In This Empty Room | deezer — Clouds - In This Empty Room (feat. Gogo Melone) | 1.000 |
| 221 | rejected-quality | John Legend - Start A Fire | deezer — John Legend - Start A Fire | 1.000 |
| 328 | rejected-quality | Az Shanbe - Har Ghadam | deezer — Az Shanbe - Har Ghadam | 1.000 |
| 450 | below-threshold | Battleme - Hey Hey, My My | deezer — Battleme - Doin' Time In My Head Ain't Cheap | 0.000 |
| 561 | rejected-quality | Matthew Perryman Jones - Living in the Shadows | deezer — Matthew Perryman Jones - Living in the Shadows | 1.000 |
| 633 | rejected-quality | London After Midnight - Sacrifice | deezer — London After Midnight - Sacrifice | 1.000 |
| 668 | rejected-quality | Broken Iris - Where Butterflies Never Die | deezer — Broken Iris - Where Butterflies Never Die | 1.000 |
| 688 | rejected-quality | Ebi - Atreh Toh | deezer — Ebi - Atreh Toh | 1.000 |
| 728 | rejected-quality | April Rain - Reprise | deezer — April Rain - Reprise | 1.000 |
| 729 | matched | April Rain - My Silent Angel | deezer — April Rain - My Silent Angel | 1.000 |
| 742 | rejected-quality | We Are Magonia - The Living Will Envy the Dead | deezer — We Are Magonia - The Living Will Envy the Dead | 1.000 |
| 751 | below-threshold | Garood - Dancing on the Shore | qobuz — Jonathan Butler - Dancing on the Shore | 0.000 |
| 752 | below-threshold | Garood - The Other Side - Instrumental | qobuz — The Greatest Showman Ensemble - The Other Side (From "The Greatest Showman") | 0.000 |
| 759 | rejected-quality | Estas Tonne - Bird’s Teardrops | deezer — Estas Tonne - Bird's Teardrops (Live) | 0.919 |
| 760 | rejected-quality | Estas Tonne - Fusion (Live) - Radio Edit | deezer — Estas Tonne - Fusion (Live) (Radio Edit) | 1.000 |
| 762 | rejected-quality | Estas Tonne - Spirit of Time (Live) | deezer — Estas Tonne - Spirit of Time (Live) | 1.000 |
| 802 | below-threshold | Hamed Mohammadi - خاکستر | qobuz — Hamed Homayoun - Rabeteh | 0.000 |
| 804 | below-threshold | Hamed Mohammadi - طلسم | qobuz — Hamed Homayoun - Rabeteh | 0.000 |
| 805 | below-threshold | Hamed Mohammadi - گل مرداب | qobuz — HaMiX - Close | 0.000 |
| 806 | below-threshold | Sackrun - Yadollah | qobuz — Sackrun - Lotfali | 0.000 |
| 824 | rejected-quality | Kayhan Kalhor - Where Are You? | deezer — Kayhan Kalhor and Ali Bahrami Fard - Where Are You? | 0.888 |
| 829 | rejected-quality | Simin Ghanem - Range mesi | deezer — Simin Ghanem - Range mesi | 1.000 |
| 906 | rejected-quality | Exilym - One more step before the end | deezer — Exilym - One more step before the end | 1.000 |
| 907 | rejected-quality | Exilym - This is the end | deezer — Exilym - This is the end | 1.000 |
| 945 | rejected-quality | Orbit Culture - Saw | deezer — Orbit Culture - Saw | 1.000 |
| 958 | rejected-quality | Black Country Communion - Little Secret | deezer — Black Country Communion - Little Secret | 1.000 |
| 981 | rejected-quality | Clouds - Driftwood | deezer — Clouds - Driftwood (feat. Pim Blankenstein) | 1.000 |
| 999 | below-threshold | Robot 29 - Bia Benevisim - Persian Rock Reimagined | qobuz — Robot 29 - Labe Karon | 0.000 |
| 1041 | rejected-quality | Break My Fucking Sky - Seven | deezer — Break My Fucking Sky - Seven | 1.000 |

## Interpretation

- The 30 replay Unmatched results are not all equivalent. Twenty-one have a strong Deezer candidate but Deezer exposes only lossy audio, while nine have no candidate above the current lossless matcher threshold.
- The repeated occurrence is a Queue identity limitation, not a catalog miss.
- The production rematch duplicates are stale replacement rows created because Queue identity is source `track.id`; they require cleanup/recovery, not position-based deletion.

## Safety note

The production database was recreated empty by a separate process during diagnosis. No production backup was found, and the temporary replay was not copied over it.
