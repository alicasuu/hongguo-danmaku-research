# Additions from the repository review and public-data pilot

All migrations are additive. Existing research and demo records are retained.

- `public_page_snapshots`: immutable sanitized public-page evidence, source/capture timestamps, hash, response bytes and fetch time. Catalogs and source durations are retained here without overwriting the old catalog.
- `comments.record_type`: distinguishes `episode_comment_preview`, `drama_review_preview`, and older ordinary comments. Missing source/parent IDs remain NULL. `comment_observations` retains each preview observation and changing likes.
- `engagement_snapshots.coverage_status`: new public observations are `verified_partial`; older observations default to `unverified`.
- Native `danmaku.raw_json` now stores the original message item, not merely normalized fields. New columns: `source_url`, `offset_source`, `posting_time_raw_json`, `identity_basis`, `last_seen_at`. Original posting values remain raw until units/timezone are verified; a plausible numeric field alone does not populate `posted_at`.
- `native_danmaku_versions`: immutable raw revisions, linked to original page evidence and SHA-256. Message/page commits remain atomic. Missing native IDs use a separately labeled content/offset/raw-time fingerprint; it can collapse indistinguishable messages and is not a platform ID.
- Existing `visible_overlay_*` tables remain separate, with platform message IDs and offsets NULL; observed video position is never promoted to native timing.

The current 240 real preview records and 22 prior overlay records may contain overlapping text; they must not be summed as unique native messages. All native and video live-success counters remain zero.

---

## Earlier documentation

# 数据字典与研究局限

## normalized tables

- `dramas`: drama_id, title, url, genre, ai_classification, description, status, episode_count, creator, rank_source, discovered_at, last_seen, source. All records need ID+title.
- `episodes`: episode_id, drama_id, episode_number, duration_seconds, media_path, media_status, completeness, subtitles_path, subtitle_status, media_sha256, media_bytes. Only source-exposed or explicitly imported episodes are entered.
- `ranking_snapshots`: drama_id, rank_type, rank, heat_value, heat_raw, observed_at, source_url, metric_definition=`composite_heat_not_verified_views`.
- `engagement_snapshots`: drama_id, episode_id nullable, scope=drama/episode, metric, numeric value, raw label, precision, source, observed_at, collected_at. `views` is reserved for actual view counts, never estimated from rank heat.
- `danmaku`: exact message ID when provided, text, episode ID, native playback milliseconds or estimated observation time with explicit `timing_method`, original posted_at if available, captured_at, coverage and source. Not interchangeable with comments.
- `comments`: comment ID, parent_id, episode or drama scope, text, likes, posted_at and collection time.
- `assets`: kind video/subtitles, local path, checksum, bytes, observed duration, declared and technically verified full flags, access basis.
- `drama_reviews`: human AI/live-action classification, human likeness rating 1..5, voice/subtitle observations, frame count, reviewer and confidence.
- `collection_runs`, `collection_events`: run status, elapsed status and error details. Each failed episode remains visible.

## Time provenance

- `playback_time_ms` means offset in episode playback, **not wall-clock post time**.
- `posted_at` is wall-clock publication timestamp where provided.
- `captured_at` is crawler clock, and must not be mistaken for posted_at.
- `timing_method=platform_native`: only when raw platform value verified.
- `timing_method=estimated_observation`: player currentTime when a DOM message was *noticed*. Delays/seek/repeats may bias it.

## Completion/status claims

- `verified_full`: video valid per ffprobe, declared to be complete based on authorized source, and duration matches declared expected duration within min(max(0.25 seconds, 2%), 5%). This is a **technical indicator**, not a legal permission determination or proof every frame exists.
- `completeness=unverified`: includes short previews, unmatched durations, missing expected duration or unreviewed full episodes.
- If only 3 preview episode IDs appear in the public site, those are 3 IDs, **not the whole season**.
- `coverage=partial/sampled_visible/full_claimed`: producer/export assertions only; do not claim `full_claimed` without platform coverage documentation.

## Missing sources and research gaps

As of the Nov 2026 pilot design, publicly readable SSR metadata is a plausible acquisition path; the site may change or deny automated access. Full current-app playback and authentic historical danmaku may require explicit provider permission or an authorized export. Signed/DRM endpoints are not implemented. Dataset completeness therefore remains unverified until the research team can secure the necessary sources.

## Selection validity

The public Hongguo hot list is explicitly ranked by composite engagement heat. Research requiring *top 10 by views* must acquire a view metric with a consistent definition and observation date. Never change field names to disguise this difference.

## Privacy

Do not include viewer ID, phone number, or personal profiles unless specifically necessary and approved by the research protocol. Keep raw comments in restricted storage. Use anonymized aggregates when publishing and consider retention limits.

## Native adapter additions (2026-11-09)

See `NATIVE_COLLECTION_STATUS.md` for live access failures and the distinction between tested fixture ingestion and successful platform collection. `native_danmaku_pages` stores atomic page checkpoints, evidence paths/hashes and inserted/updated counts. Episode columns `media_duration_seconds`, `expected_duration_seconds`, and `duration_validation` separate observed media length from source metadata; migrations are additive. Video verification now includes full decoding.

## Screen-visible overlay additions (2026-11-09)

`visible_overlay_records` holds text and review attribution per page session and displaying episode. `dom_render_id` is a renderer index, and local `record_id` is a deduplication key; neither is a platform message ID. `source_posted_at_raw` is the source review's Unix-seconds posting time; the UTC conversion is separate. This mode enforces NULL `platform_message_id` and `platform_playback_time_ms`.

`visible_overlay_observations` holds sampled player positions, observation times, pause state and clipping flags. `visible_overlay_captures` holds the local evidence path and SHA-256 with its collection run. Records and observations are committed atomically per capture and replayed idempotently. All records use `sampled_visible` coverage. These tables are excluded from native-danmaku counts and leave existing `danmaku` and `comments` rows unchanged. See `VISIBLE_OVERLAY_COLLECTION.md` for the actual source trace, current counts and reproduction instructions.
