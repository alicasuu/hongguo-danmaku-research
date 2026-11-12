# Screen-visible Hongguo overlays

The website does display danmaku-style scrolling text. The earlier statement that danmaku was unavailable was too broad: **native timed-message acquisition is still unverified, but collecting the visible overlays works**. These outputs now have separate storage and semantics.

## Actual collection on November 9, 2026 (America/Los_Angeles)

The single-episode test first imported 3 real overlay records. After that passed, this mode sampled the first episode of each of the existing 10 non-demo dramas. Final results: **22 overlay records, 137 timestamped sightings, 10 episodes across 10 dramas**. All 22 records have a source posting time matched to an embedded review. Native message IDs and native playback offsets are absent for all 22. No synthetic data were added to the research database.

This is a small, bounded sample, not collection of all 2,826 episodes or all comments. The nine expansion players were sampled ten times at approximately one-second intervals, including video startup. The initial episode also has a paused-position observation and a short fresh-playback observation. Paused state is saved. One empty playback attempt was retained before a successful retry. A navigation timeout recovered through the site's chart/detail navigation.

`output/visible_overlays/csv/summary.json` records current counts and per-episode totals. `attempts.json` documents browser attempts; raw `*.capture.json` files preserve actual samples, including empty snapshots. UTC observation timestamps are recorded in each snapshot.

## Provenance and field meanings

Normal website navigation loads `/player/<series_id>` for episode 1. The page's own inline script contains JSON assigned to `_ROUTER_DATA`. The sampler **parses DOM script text as JSON without executing it or reading application globals**. It selects only episode mapping and review fields needed to match visible text. The source path is:

`loaderData["player_(series_id)/page"].episodeSocialInfo.reviews.reviews`

On all ten tested pages, review objects expose `content`, `create_time`, `digg_count`, `user_name`, and `user_avatar`. No message ID or playback-offset field was exposed in these objects. User names, avatars, request metadata and authentication material are not included in capture output. `create_time` is preserved as its original Unix-seconds string and converted separately to UTC; it is a **review posting time**, not a video timestamp.

The public frontend source under `output/browser_followup/` supplies the rendering trace: `ho.aadf847f18.js` passes reviews to the overlay component and comments drawer. Its converter in `9q.8f784bf2bf.js` maps review content, measures text width and calculates scrolling starts, generating `dm-init-<index>` IDs. Current live samples independently confirm the correspondence: each recorded DOM index and full text, including emoji image alt text, exactly matches the corresponding embedded review. The page document is the observed access path; no undocumented backend request, signature emulation, private network interception, or credential extraction was needed. The server-side upstream API behind the loader was not established.

- `platform_message_id` and `platform_playback_time_ms`: NULL. No local hash, renderer index, player clock, or posting time is placed here.
- `dom_render_id`: actual DOM attribute such as `dm-init-0`; a renderer index, not a stable platform message ID.
- `source_posted_at_raw` / `source_posted_at_utc`: matched review posting time. Unmatched overlays retain NULL.
- `observed_playback_time_ms`: video's position at sampling, with `timing_method=observed_playback_position`. It is not when the review was originally posted or intended to appear.
- `observed_at`: collection time. `video_paused` distinguishes playback from a paused display.
- `episode_id`: episode **displaying** the overlay, verified against the existing database. This does not establish which episode the commenter originally posted on.
- `coverage=sampled_visible`: only sampled DOM nodes whose boxes intersect the player layer and viewport. Full node text is retained even when partly on screen; `partially_clipped` records that distinction. This is DOM sampling, not an OCR transcription of just visible characters.

`record_id` and `observation_id` are explicitly local deduplication keys. A record represents render ID plus text within one page session and episode. Multiple sightings of one node contribute one record. Equal text in two source review entries remains two records. Reloads start a new session because renderer indices are not stable IDs. The record count is **not a count of globally unique platform messages**.

## Implementation and rerunning

`hongguo/visible_overlay_snapshot.js` is the read-only browser sampler used for this live run. Execute it with the connected browser's supported DOM-evaluation API after starting playback through the normal UI. It returns a snapshot without accessing cookies, passwords, tokens, profiles or request headers. Wrap snapshots in `{ "schema_version": 1, "session_id": "<local page-session identifier>", "snapshots": [...] }` and save as `*.capture.json`. The session identifier is local bookkeeping, never a message ID. Start a new identifier after navigation/reload. Live capture requires a connected browser controller; the CLI imports its evidence rather than claiming to attach to Chrome.

The repeated sampling loop evaluated the file once per second, appended each snapshot, and saved it immediately, retaining empty samples. After interruption, already-saved snapshots can be imported. Continuing the same still-open page can append to that session. Preserve imported evidence files and save an extended capture under a new filename. The importer deduplicates repeated snapshots and records across files within the same session.

```bash
.venv/bin/python -m hongguo visible-overlays output/visible_overlays \
  --out output/visible_overlays/csv
.venv/bin/python -m unittest discover -s tests -v
```

Directory input processes only `*.capture.json`. Every capture is validated before import; records, sightings and its SHA-256 receipt commit together. A malformed record rolls back that capture. Reimporting unchanged evidence adds zero records or sightings. Native-danmaku parsing continues to reject generated review overlays; the new mode does not relax that restriction.

SQLite tables: `visible_overlay_records`, `visible_overlay_observations`, `visible_overlay_captures`. Existing `danmaku` and `comments` tables are unchanged. CSV exports include those three tables plus `visible_overlay_samples.csv`, joining text, source posting time, observed player position and collection time. Blank CSV fields represent missing values.

## Verification and limits

All 60 tests passed, including eight added tests for missing/zero timing, exact source attribution, rejection of invented native fields, deduplication, reload sessions, invalid/offscreen samples, transactional rollback and CSV separation. Live files were imported through the actual CLI and replayed to verify idempotence. Test fixtures use temporary databases.

Backup: `data/backups/before_visible_overlays.sqlite`. `output/visible_overlays/preservation_check.json` checks every pre-existing row on its original columns, SQLite integrity and foreign keys.

Chrome remains unavailable through the connector; this run used the separate in-app browser's normal public pages. It does not validate the user's authenticated Chrome path. The prior native endpoint error remains `110001`; no real native danmaku records were obtained. Visible-overlay collection works independently of that blocker.
