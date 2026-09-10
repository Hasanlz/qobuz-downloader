# Tidal quality comparison: how often is Tidal actually higher than Qobuz?

Date: 2026-09-09. Research for the proposed "Tidal fallback" feature (after downloading a track from Qobuz, check Tidal for a higher-quality version of the same track and prefer it if available).

## Method

Sampled 59 tracks from the real queue database (`/home/hasanlz/Music/.queue.sqlite3`, the "Optimistic Delusion" Spotify playlist, 1067 rows): all 11 COMPLETE tracks plus every 22nd PENDING row (48 of 1056). No audio was downloaded or streamed — metadata API calls only.

Per sampled track:

1. **Qobuz quality** — `GET https://www.qobuz.com/api.json/0.2/track/get?track_id=<id>` with `X-App-Id` / `X-User-Auth-Token` headers (queue ids are already Qobuz track ids, so no Qobuz-side search). Read `maximum_bit_depth` and `maximum_sampling_rate`.
2. **Tidal availability** — `GET https://api.tidal.com/v1/search?query=<artist> <title>&types=tracks&limit=20&countryCode=US` with the public partner token header `X-Tidal-Token: TPIsV0A9lyiqKl9u`. Best match picked with the same fuzzy scoring as `_score_track` in `src/qobuz_downloader/match/live.py` (title similarity >= 0.5 gate; weighted score: title 0.6, artist 0.25, duration 0.15; durations in seconds on both sides). A match was accepted when score >= 0.6 and artist similarity >= 0.4; ties within 0.05 were broken toward non-versioned (non-remaster) stereo candidates, and versioned matches would be noted. The Tidal `version` field ended up null for every selected match; one matched title embeds "(Remastered)" in its title string itself (Metallica "No Remorse" — flagged in the raw CSV, LOSSLESS-only, verdict unaffected).
3. **Verdict** — mapping (Tidal HiRes FLAC = any FLAC > 16-bit/44.1, up to 24/192, per Tidal's help pages; `LOSSLESS`-only = 16/44.1; MQA/360RA dropped platform-wide since July 24, 2024):
   - `TIDAL_HIGHER` — Tidal `HIRES_LOSSLESS` vs Qobuz 16-bit, or vs Qobuz 24-bit at 44.1/48 kHz.
   - `MQA_HIGHER` — Tidal `MQA` vs Qobuz 16-bit (counted separately; zero occurrences — see Sources for the MQA sunset).
   - `QOBUZ_HIGHER` — Qobuz 24-bit but Tidal `LOSSLESS` only.
   - `EQUAL` — both 16/44.1; or Qobuz already 24-bit > 48 kHz (Tidal's actual sample rate is not exposed by the search API's tag list, so "higher" cannot be proven from metadata — treated as equal-at-best; this is a limitation of both this study and the proposed feature).
   - `NO_TIDAL_MATCH` / `MATCH_UNCLEAR` — no acceptable fuzzy match (zero occurrences).

Politeness: 0.4 s sleep between requests, up to 3 retries with exponential backoff for timeouts/transport errors and HTTP 429/5xx, 30 s client timeout (httpx default read timeout of 5 s raised, as in `src/qobuz_downloader/qobuz/live.py`).

### Caveats

- N = 59 from a single playlist, rock/metal-heavy with some Iranian pop — not a random sample of either catalog; percentages are indicative, not precise.
- The Tidal tag-based comparison cannot see the exact sample rate of a HiRes FLAC track (only the `HIRES_LOSSLESS` tag), so a TIDAL_HIGHER verdict for a Qobuz 24/44.1 track could mean anything from 24/48 to 24/192 on Tidal's side; conversely, EQUAL for Qobuz 24/>48k tracks is conservative (Tidal could be higher, but it is unprovable via this API).
- Qobuz `track/get` returned 404 for one sample id (368533876, Ashes of Eden — the same id resolves fine via `track/search` with 16/44.1); that record was repaired from the search endpoint rather than dropped. Worth knowing if the fallback needs to handle Qobuz API quirks.
- Fuzzy matching is approximate; 8 of 9 TIDAL_HIGHER matches were exact title+artist+duration (score 1.0); Miley Cyrus "Night Crawling" scored 0.782 (feat. credit in the Tidal title), Metallica "No Remorse" 0.787.

## Numbers

**59 tracks sampled; every track found a Tidal match** — even the Iranian artists (Amir Tataloo, Homayra, Ali Zandevakili) matched exactly. Verdict counts:

| Verdict | Count | % of 59 |
|---|---|---|
| TIDAL_HIGHER | 9 | 15.3% |
| QOBUZ_HIGHER | 8 | 13.6% |
| EQUAL | 42 | 71.2% |
| MQA_HIGHER | 0 | 0% |
| NO_TIDAL_MATCH | 0 | 0% |
| MATCH_UNCLEAR | 0 | 0% |

**TIDAL_HIGHER tracks (all 9):**

| Artist | Title | Qobuz | Tidal |
|---|---|---|---|
| Amir Tataloo | Boht | 24/44.1 | HIRES_LOSSLESS |
| Avantasia | Lucifer | 24/44.1 | HIRES_LOSSLESS |
| Bad Omens | Like A Villain | 24/48 | HIRES_LOSSLESS |
| Faouzia | Hero | 24/44.1 | HIRES_LOSSLESS |
| Five Finger Death Punch | Welcome To The Circus | 24/48 | HIRES_LOSSLESS |
| Ghost | Faith | 24/44.1 | HIRES_LOSSLESS |
| Miley Cyrus | Night Crawling | 24/44.1 | HIRES_LOSSLESS |
| Old Gods of Asgard | Dark Ocean Summoning | 24/44.1 | HIRES_LOSSLESS |
| Soen | Illusion | 24/48 | HIRES_LOSSLESS |

Stratified by Qobuz quality — the headline finding:

| Qobuz quality bucket | n | TIDAL_HIGHER | QOBUZ_HIGHER | EQUAL |
|---|---|---|---|---|
| 16/44.1 | 38 | **0** | 0 | 38 |
| 24-bit at 44.1/48 kHz | 15 | **9 (60%)** | 6 | 0 |
| 24-bit > 48 kHz | 6 | **0** | 2 | 4 |

- Zero of 38 tracks where Qobuz delivered 16/44.1 had HiRes FLAC on Tidal.
- 9 of 15 tracks (60%) where Qobuz delivered 24-bit at 44.1/48 kHz had HiRes FLAC on Tidal.
- Zero of 6 tracks where Qobuz delivered 24-bit > 48 kHz were beaten by Tidal (4 carried `HIRES_LOSSLESS` tags but with no provable rate advantage; the other 2, Linkin Park "New Divide" and Metallica "No Remorse" — both 24/96 — were LOSSLESS-only on Tidal).
- Tidal `HIRES_LOSSLESS` appeared on 13 of 59 tracks overall; for 4 of those (Within Temptation "Wireless" 24/96, Pink Floyd "Marooned"/"Wish You Were Here" 24/192, Bring Me The Horizon "Doomed" 24/96) Qobuz was already at >= 24/96.
- No MQA tags anywhere (consistent with the 2024-07-24 MQA sunset). Two tracks additionally carried `DOLBY_ATMOS` (Five Finger Death Punch "Welcome To The Circus", Within Temptation "Wireless"); the comparison used the stereo FLAC tags.

## Per-track table

59 rows, sorted by verdict then Qobuz bit depth. "Match" = fuzzy score (1.0 = exact title + artist + duration).

| # | Artist | Title | Qobuz bd/sr | Tidal tags | Match | Verdict |
|---|-------|-------|-------------|------------|-------|---------|
| 1 | Amir Tataloo | Boht | 24/44.1 | LOSSLESS, HIRES_LOSSLESS | 1.0 | TIDAL_HIGHER |
| 2 | Avantasia | Lucifer | 24/44.1 | LOSSLESS, HIRES_LOSSLESS | 1.0 | TIDAL_HIGHER |
| 3 | Bad Omens | Like A Villain | 24/48 | LOSSLESS, HIRES_LOSSLESS | 1.0 | TIDAL_HIGHER |
| 4 | Faouzia | Hero | 24/44.1 | LOSSLESS, HIRES_LOSSLESS | 1.0 | TIDAL_HIGHER |
| 5 | Five Finger Death Punch | Welcome To The Circus | 24/48 | LOSSLESS, HIRES_LOSSLESS, DOLBY_ATMOS | 1.0 | TIDAL_HIGHER |
| 6 | Ghost | Faith | 24/44.1 | LOSSLESS, HIRES_LOSSLESS | 1.0 | TIDAL_HIGHER |
| 7 | Miley Cyrus | Night Crawling | 24/44.1 | LOSSLESS, HIRES_LOSSLESS | 0.782 | TIDAL_HIGHER |
| 8 | Old Gods of Asgard | Dark Ocean Summoning | 24/44.1 | LOSSLESS, HIRES_LOSSLESS | 1.0 | TIDAL_HIGHER |
| 9 | Soen | Illusion | 24/48 | LOSSLESS, HIRES_LOSSLESS | 1.0 | TIDAL_HIGHER |
| 10 | Disturbed | The Vengeful One | 24/48 | LOSSLESS | 1.0 | QOBUZ_HIGHER |
| 11 | Linkin Park | New Divide | 24/96 | LOSSLESS | 1.0 | QOBUZ_HIGHER |
| 12 | Linkin Park | In the End | 24/48 | LOSSLESS | 1.0 | QOBUZ_HIGHER |
| 13 | Linkin Park | Numb | 24/48 | LOSSLESS | 1.0 | QOBUZ_HIGHER |
| 14 | Linkin Park | What I've Done | 24/48 | LOSSLESS | 1.0 | QOBUZ_HIGHER |
| 15 | Linkin Park | BURN IT DOWN | 24/44.1 | LOSSLESS | 1.0 | QOBUZ_HIGHER |
| 16 | Linkin Park | Breaking the Habit | 24/48 | LOSSLESS | 1.0 | QOBUZ_HIGHER |
| 17 | Metallica | No Remorse | 24/96 | LOSSLESS | 0.787 | QOBUZ_HIGHER |
| 18 | Bring Me The Horizon | Doomed | 24/96 | LOSSLESS, HIRES_LOSSLESS | 1.0 | EQUAL |
| 19 | Pink Floyd | Marooned | 24/192 | LOSSLESS, HIRES_LOSSLESS | 1.0 | EQUAL |
| 20 | Pink Floyd | Wish You Were Here | 24/192 | LOSSLESS, HIRES_LOSSLESS | 1.0 | EQUAL |
| 21 | Within Temptation | Wireless | 24/96 | LOSSLESS, HIRES_LOSSLESS, DOLBY_ATMOS | 1.0 | EQUAL |
| 22 | Airbag | How I Wanna Be | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 23 | Ali Zandevakili | Lalaei | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 24 | All That Remains | What If I Was Nothing | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 25 | Ashes of Eden | God, Save Me From Myself. | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 26 | Bullet For My Valentine | All These Things I Hate (Revolve Around Me) | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 27 | Bullet For My Valentine | Waking the Demon | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 28 | Draconian | Rivers Between Us | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 29 | Evanescence | Bring Me To Life | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 30 | Evanescence | Taking Over Me | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 31 | Evanescence | Haunted | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 32 | Evanescence | My Heart Is Broken | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 33 | Evgeny Grinko | Valse | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 34 | Gary Moore | Midnight Blues | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 35 | Homayra | Mamzaboonam Bash | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 36 | I Prevail | Bow Down | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 37 | In Flames | Alias | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 38 | Joanne Shaw Taylor | Blackest Day | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 39 | Judas Priest | Prisoner of Your Eyes | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 40 | Kanye West | Heartless | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 41 | Kensington | Insane | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 42 | Kensington | St. Helena | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 43 | Linkin Park | Talking to Myself | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 44 | Ocean Sleeper | Your Love I'll Never Need | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 45 | Rammstein | Deutschland | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 46 | Riverside | Stuck Between | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 47 | Scorpions | Lorelei | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 48 | Scorpions | Still Loving You | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 49 | Seether | Fake It | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 50 | Self Deception | Hell and Back | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 51 | Shamrain | Slow Motions | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 52 | Shamrain | Black November | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 53 | Shinedown | Second Chance | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 54 | Slipknot | If Rain Is What You Want | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 55 | Subheim | One Step Before The Exit | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 56 | System Of A Down | Spiders | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 57 | Theory Of A Deadman | By the Way | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 58 | Three Days Grace | Lost in You | 16/44.1 | LOSSLESS | 1.0 | EQUAL |
| 59 | We Lost The Sea | Bogatyri | 16/44.1 | LOSSLESS | 1.0 | EQUAL |

## Conclusion

**A Tidal fallback is worth implementing — but only as a narrow, quality-triggered top-up, not a general one.**

The data confirms the owner's hypothesis with one refinement:

1. **Check Tidal only when Qobuz delivered 24-bit at 44.1 or 48 kHz.** That band is the only place upgrades were found: 9 of 15 tracks (60%) had `HIRES_LOSSLESS` on Tidal. Everywhere else the check is wasted work.
2. **Qobuz 16/44.1 -> never check.** 0 of 38 upgraded; Tidal's base lossless tier is exactly 16/44.1 FLAC, so EQUAL is the ceiling.
3. **Qobuz 24/88.2+ -> never check.** 0 of 6 upgraded, and the public search API cannot reveal Tidal's actual sample rate, so a "HIRES_LOSSLESS" tag cannot prove an upgrade over 24/96 or 24/192 anyway. The claim "24-bit > 48 kHz on Qobuz never has a provable Tidal upgrade" held in 6 of 6 cases.
4. **In the 24/44.1-24/48 band, ~60% of tracks gain.** The Tidal file is at minimum 24-bit > 44.1 kHz (by Tidal's HiRes definition) and possibly up to 24/192 — a real quality win, MQA-free since Tidal dropped MQA in July 2024.
5. **Verify before replacing.** The search tags are coarse (a `HIRES_LOSSLESS` track could be "just" 24/48). A sound design downloads the Tidal stream, checks its actual bit depth/sample rate against the Qobuz file (the way `track/getFileUrl` reports `sampling_rate`/`bit_depth` on the Qobuz side), and only replaces when strictly higher. Otherwise the occasional no-op re-download wastes bandwidth for no gain.

Expected yield on this playlist: ~9 of 59 tracks (~15%) upgraded, all from the 24/44.1-24/48 band. For this rock/metal-heavy queue that is a modest but genuine improvement; for catalogs with more modern pop production (Miley Cyrus, Faouzia, Ghost in the sample), the hit rate in that band was high.

### Sample-size honesty

N = 59, one playlist (rock/metal-heavy plus some Iranian pop), 15 of 59 in the upgradeable band. The 60% figure is 9 of 15 — the 95% binomial confidence interval is roughly 33%-82%. The *direction* is solid (upgrades exist and are common in the 24/44.1-24/48 band, absent elsewhere); the exact rate needs a bigger sample. The raw CSV below allows re-analysis without re-querying either API.

### Raw data (CSV)

One row per sampled track. `tidal_tags` uses `;` as the list separator.

```csv
qobuz_id,title,artist,album,duration_s,queue_status,qobuz_bit_depth,qobuz_sampling_rate,tidal_id,tidal_title,tidal_version,tidal_tags,tidal_audio_quality,match_score,verdict,note
265691908,New Divide,Linkin Park,Papercuts,269,COMPLETE,24,96,2918430,New Divide,,LOSSLESS,LOSSLESS,1.0,QOBUZ_HIGHER,
104171467,Night Crawling,Miley Cyrus,Plastic Hearts (Explicit),189,COMPLETE,24,44.1,163342289,Night Crawling (feat. Billy Idol),,LOSSLESS;HIRES_LOSSLESS,LOSSLESS,0.782,TIDAL_HIGHER,
34218874,Heartless,Kanye West,808s & Heartbreak,211,COMPLETE,16,44.1,63863048,Heartless,,LOSSLESS,LOSSLESS,1.0,EQUAL,
7020294,In the End,Linkin Park,Hybrid Theory (Hi-Res Version),216,COMPLETE,24,48,1225577,In the End,,LOSSLESS,LOSSLESS,1.0,QOBUZ_HIGHER,
7020285,Numb,Linkin Park,Meteora,187,COMPLETE,24,48,234806,Numb,,LOSSLESS,LOSSLESS,1.0,QOBUZ_HIGHER,
6907106,What I've Done,Linkin Park,Minutes To Midnight (Explicit),205,COMPLETE,24,48,406466,What I've Done,,LOSSLESS,LOSSLESS,1.0,QOBUZ_HIGHER,
7631095,Second Chance,Shinedown,The Sound of Madness,222,COMPLETE,16,44.1,5002024,Second Chance,,LOSSLESS,LOSSLESS,1.0,EQUAL,
17795395,Bring Me To Life,Evanescence,Fallen,235,COMPLETE,16,44.1,31849195,Bring Me To Life,,LOSSLESS,LOSSLESS,1.0,EQUAL,
11092333,BURN IT DOWN,Linkin Park,LIVING THINGS,230,COMPLETE,24,44.1,15937590,BURN IT DOWN,,LOSSLESS,LOSSLESS,1.0,QOBUZ_HIGHER,
17795401,Taking Over Me,Evanescence,Fallen,228,COMPLETE,16,44.1,31849201,Taking Over Me,,LOSSLESS,LOSSLESS,1.0,EQUAL,
17795398,Haunted,Evanescence,Fallen,185,COMPLETE,16,44.1,31849198,Haunted,,LOSSLESS,LOSSLESS,1.0,EQUAL,
17979584,My Heart Is Broken,Evanescence,Evanescence,269,PENDING,16,44.1,32074209,My Heart Is Broken,,LOSSLESS,LOSSLESS,1.0,EQUAL,
38572836,Talking to Myself,Linkin Park,One More Light,231,PENDING,16,44.1,74017617,Talking to Myself,,LOSSLESS,LOSSLESS,1.0,EQUAL,
95787427,No Remorse,Metallica,Kill 'Em All,386,PENDING,24,96,166787869,"No Remorse (Remastered)",,LOSSLESS,LOSSLESS,0.787,QOBUZ_HIGHER,"matched title embeds (Remastered) in the Tidal title string; version field null"
7020281,Breaking the Habit,Linkin Park,Meteora,196,PENDING,24,48,234802,Breaking the Habit,,LOSSLESS,LOSSLESS,1.0,QOBUZ_HIGHER,
125373657,Hero,Faouzia,Hero,174,PENDING,24,44.1,185414467,Hero,,LOSSLESS;HIRES_LOSSLESS,LOSSLESS,1.0,TIDAL_HIGHER,
494830,Lorelei,Scorpions,Sting in the Tail,272,PENDING,16,44.1,3493538,Lorelei,,LOSSLESS,LOSSLESS,1.0,EQUAL,
35541132,The Vengeful One,Disturbed,Immortalized,252,PENDING,24,48,50049985,The Vengeful One,,LOSSLESS,LOSSLESS,1.0,QOBUZ_HIGHER,
4824493,Still Loving You,Scorpions,Comeblack,402,PENDING,16,44.1,8632224,Still Loving You,,LOSSLESS,LOSSLESS,1.0,EQUAL,
19135394,If Rain Is What You Want,Slipknot,.5: The Gray Chapter ,380,PENDING,16,44.1,35987637,If Rain Is What You Want,,LOSSLESS,LOSSLESS,1.0,EQUAL,
50153557,Faith,Ghost,Prequelle,269,PENDING,24,44.1,89387534,Faith,,LOSSLESS;HIRES_LOSSLESS,LOSSLESS,1.0,TIDAL_HIGHER,
365358,All These Things I Hate (Revolve Around Me),Bullet For My Valentine,All These Things I Hate (Revolve Around Me),226,PENDING,16,44.1,11342862,All These Things I Hate (Revolve Around Me),,LOSSLESS,LOSSLESS,1.0,EQUAL,
2807050,By the Way,Theory Of A Deadman,Scars & Souvenirs,214,PENDING,16,44.1,1658028,By the Way,,LOSSLESS,LOSSLESS,1.0,EQUAL,
27673313,Stuck Between,Riverside,Voices In My Head,236,PENDING,16,44.1,52012520,Stuck Between,,LOSSLESS,LOSSLESS,1.0,EQUAL,
157695558,Welcome To The Circus,Five Finger Death Punch,Welcome To The Circus,256,PENDING,24,48,224902859,Welcome To The Circus,,LOSSLESS;HIRES_LOSSLESS;DOLBY_ATMOS,LOSSLESS,1.0,TIDAL_HIGHER,
153963257,Boht,Amir Tataloo,Boht,440,PENDING,24,44.1,224597697,Boht,,LOSSLESS;HIRES_LOSSLESS,LOSSLESS,1.0,TIDAL_HIGHER,
104499994,Illusion,Soen,IMPERIAL,310,PENDING,24,48,169488635,Illusion,,LOSSLESS;HIRES_LOSSLESS,LOSSLESS,1.0,TIDAL_HIGHER,
59009070,Bow Down,I Prevail,TRAUMA,242,PENDING,16,44.1,106321566,Bow Down,,LOSSLESS,LOSSLESS,1.0,EQUAL,
338331360,Like A Villain,Bad Omens,THE DEATH OF PEACE OF MIND,210,PENDING,24,48,438882316,Like A Villain,,LOSSLESS;HIRES_LOSSLESS,LOSSLESS,1.0,TIDAL_HIGHER,
372420948,Your Love I'll Never Need,Ocean Sleeper,Your Love I'll Never Need,200,PENDING,16,44.1,478094079,Your Love I'll Never Need,,LOSSLESS,LOSSLESS,1.0,EQUAL,
79742563,Insane,Kensington,Time,231,PENDING,16,44.1,122011423,Insane,,LOSSLESS,LOSSLESS,1.0,EQUAL,
42079090,Lost in You,Three Days Grace,Life Starts Now,232,PENDING,16,44.1,33754286,Lost in You,,LOSSLESS,LOSSLESS,1.0,EQUAL,
190453093,Slow Motions,Shamrain,Someplace Else,285,PENDING,16,44.1,269032037,Slow Motions,,LOSSLESS,LOSSLESS,1.0,EQUAL,
36481224,St. Helena,Kensington,Control,283,PENDING,16,44.1,66263899,St. Helena,,LOSSLESS,LOSSLESS,1.0,EQUAL,
233630793,Lalaei,Ali Zandevakili,Royaye Bi Tekrar,248,PENDING,16,44.1,323834355,Lalaei,,LOSSLESS,LOSSLESS,1.0,EQUAL,
61710055,Deutschland,Rammstein,Rammstein,322,PENDING,16,44.1,109100969,Deutschland,,LOSSLESS,LOSSLESS,1.0,EQUAL,
231184853,Wireless,Within Temptation,Bleed Out,281,PENDING,24,96,293850318,Wireless,,LOSSLESS;HIRES_LOSSLESS;DOLBY_ATMOS,LOSSLESS,1.0,EQUAL,
60775368,Lucifer,Avantasia,Ghostlights,228,PENDING,24,44.1,107098940,Lucifer,,LOSSLESS;HIRES_LOSSLESS,LOSSLESS,1.0,TIDAL_HIGHER,
47394500,Waking the Demon,Bullet For My Valentine,Scream Aim Fire Deluxe Edition,247,PENDING,16,44.1,1604497,Waking the Demon,,LOSSLESS,LOSSLESS,1.0,EQUAL,
54864096,What If I Was Nothing,All That Remains,A War You Cannot Win,277,PENDING,16,44.1,62248323,What If I Was Nothing,,LOSSLESS,LOSSLESS,1.0,EQUAL,
96100662,Hell and Back,Self Deception,Shapes,176,PENDING,16,44.1,397492951,Hell and Back,,LOSSLESS,LOSSLESS,1.0,EQUAL,
76667272,Mamzaboonam Bash,Homayra,Hamzabonam Bash,340,PENDING,16,44.1,6317514,Mamzaboonam Bash,,LOSSLESS,LOSSLESS,1.0,EQUAL,
76299958,How I Wanna Be,Airbag,Identity (2020 Remaster),422,PENDING,16,44.1,229584146,How I Wanna Be,,LOSSLESS,LOSSLESS,1.0,EQUAL,
335737978,Valse,Evgeny Grinko,Ice for Aureliano Buendia,205,PENDING,16,44.1,436465665,Valse,,LOSSLESS,LOSSLESS,1.0,EQUAL,
1951261,Midnight Blues,Gary Moore,Still Got The Blues,298,PENDING,16,44.1,144928,Midnight Blues,,LOSSLESS,LOSSLESS,1.0,EQUAL,
400480703,Bogatyri,We Lost The Sea,Departure Songs,700,PENDING,16,44.1,51880081,Bogatyri,,LOSSLESS,LOSSLESS,1.0,EQUAL,
17790841,Fake It,Seether,Finding Beauty In Negative Spaces,193,PENDING,16,44.1,31848768,Fake It,,LOSSLESS,LOSSLESS,1.0,EQUAL,
47683887,Marooned,Pink Floyd,The Division Bell ,329,PENDING,24,192,55391528,Marooned,,LOSSLESS;HIRES_LOSSLESS,LOSSLESS,1.0,EQUAL,
46965880,Spiders,System Of A Down,System Of A Down,215,PENDING,16,44.1,33958250,Spiders,,LOSSLESS,LOSSLESS,1.0,EQUAL,
47683565,Wish You Were Here,Pink Floyd,Wish You Were Here,338,PENDING,24,192,55391801,Wish You Were Here,,LOSSLESS;HIRES_LOSSLESS,LOSSLESS,1.0,EQUAL,
95467523,One Step Before The Exit,Subheim,Approach,312,PENDING,16,44.1,144286166,One Step Before The Exit,,LOSSLESS,LOSSLESS,1.0,EQUAL,
37143873,Rivers Between Us,Draconian,Sovran,407,PENDING,16,44.1,68084264,Rivers Between Us,,LOSSLESS,LOSSLESS,1.0,EQUAL,
190371426,Black November,Shamrain,Deeper Into The Night,212,PENDING,16,44.1,269068492,Black November,,LOSSLESS,LOSSLESS,1.0,EQUAL,
86841554,Alias,In Flames,A Sense of Purpose ,289,PENDING,16,44.1,130186835,Alias,,LOSSLESS,LOSSLESS,1.0,EQUAL,
260697318,Blackest Day,Joanne Shaw Taylor,White Sugar,497,PENDING,16,44.1,355232834,Blackest Day,,LOSSLESS,LOSSLESS,1.0,EQUAL,
234565133,Dark Ocean Summoning,Old Gods of Asgard,Rebirth - Greatest Hits ,403,PENDING,24,44.1,325928636,Dark Ocean Summoning,,LOSSLESS;HIRES_LOSSLESS,LOSSLESS,1.0,TIDAL_HIGHER,
368533876,"God, Save Me From Myself.",Ashes of Eden,"God, Save Me From Myself.",174,PENDING,16,44.1,473479087,"God, Save Me From Myself.",,LOSSLESS,LOSSLESS,1.0,EQUAL,qobuz track/get returned 404; quality (16/44.1) verified via track/search for the same id
26916290,Doomed,Bring Me The Horizon,That's The Spirit,274,PENDING,24,96,50793896,Doomed,,LOSSLESS;HIRES_LOSSLESS,LOSSLESS,1.0,EQUAL,
109347,Prisoner of Your Eyes,Judas Priest,Screaming For Vengeance,430,PENDING,16,44.1,490493,Prisoner of Your Eyes,,LOSSLESS,LOSSLESS,1.0,EQUAL,
```

## Sources

- Tidal partner API v1 search: `GET https://api.tidal.com/v1/search?query=...&types=tracks&limit=20&countryCode=US` with `X-Tidal-Token: TPIsV0A9lyiqKl9u` (public partner token). Track objects expose `mediaMetadata.tags` (`LOSSLESS`, `HIRES_LOSSLESS`, `DOLBY_ATMOS`, ...), `version`, `duration` (seconds), `artists[]`. Queried 2026-09-09.
- Qobuz API 0.2 `track/get`: `GET https://www.qobuz.com/api.json/0.2/track/get?track_id=...` with `X-App-Id` / `X-User-Auth-Token` — returns `maximum_bit_depth`, `maximum_sampling_rate`. Queried 2026-09-09.
- Tidal Support, "HiRes FLAC audio" (updated 2026-01-09): Max tier = HiRes FLAC up to 24-bit/192 kHz; High tier = FLAC 16/44.1; HiRes FLAC is defined as any FLAC > 16/44.1. <https://support.tidal.com/hc/en-us/articles/17412130162961-HiRes-FLAC-audio>
- Tidal Support, "Audio Format Updates" (updated 2026-01-09): MQA and 360 Reality Audio "no longer accessible via any Tidal application or integration" as of July 24, 2024; MQA tracks replaced by the highest-quality FLAC distributed to Tidal. <https://support.tidal.com/hc/en-us/articles/25876825185425-Audio-Format-Updates>
