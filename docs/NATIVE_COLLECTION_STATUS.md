# Follow-up: reviewed repositories and repeated unsigned test

The 2026-11-09 Pacific follow-up reviewed `zfdang/hongguo-open-player`, `loocor/redapple`, and `zhangbaio/hongguo` at pinned revisions. See [repository comparison](REPOSITORY_COMPARISON.md) for the evidence and corrected pagination semantics.

The actual `sinfonlineb` endpoint probe returned application error 110001. Genuine native records collected remain **0**. The new parsing/retention/resume tests are implementation validation, not a successful authorized live proof. Ordinary web reviews and visible overlays are still separate datasets.

---

## Earlier documentation

# Native Hongguo collection: implementation and live test

Test date: November 9, 2026, America/Los_Angeles (evidence timestamps use UTC).

**The requested successful live single-episode native-danmaku proof of concept is still blocked.**
The adapter and offline ingestion are implemented and tested, but no real native messages have been obtained.
Do not describe the fixture tests as a successful Hongguo collection.

**Later visible-overlay result:** the separate screen-visible mode successfully collected 22 real overlay records and 137 sightings from the first episodes of all 10 existing dramas. Source review posting times are available; native message IDs and playback offsets are not. See [VISIBLE_OVERLAY_COLLECTION.md](VISIBLE_OVERLAY_COLLECTION.md). The older browser observations below describe the earlier native-only attempt; their zero-row CSV and no-expansion status do not describe the new visible-overlay dataset.

## Browser follow-up after restart (November 9, 2026)

The user confirmed a logged-in **Chrome** session. The connected browser inventory still exposed only the in-app browser and MCP Apps. Selecting Google Chrome failed with `Sky Computer Use service startup request failed`; selecting browser ID `chrome` returned `Browser is not available: chrome`. No Chrome profile, cookies, password, token, or authentication storage was read. The authenticated Chrome website path remains **untested**.

The available in-app browser is a separate session with unverified authentication, not the user's Chrome session. In it, normal UI navigation to `https://hongguoduanju.com/player/7701328280862854168` and clicking `播放短剧` played the selected first episode. The narrow player exposed a `关闭弹幕` control and an XG-DANMU layer. This corrects the earlier limited observation that no danmaku control was visible; a visible floating-text control alone does not establish native data semantics.

The actual floating text is **ordinary reviews converted into overlays** on this inspected path:

- The DOM carries generated IDs such as `dm-init-0`, with no original playback-offset attribute. The same text appears in the ordinary comments drawer.
- Public frontend chunk `ho.aadf847f18.js` passes the same `reviews` list to the overlay component and the comments drawer. The overlay calls the converter exported by module `z2`.
- Public frontend chunk `9q.8f784bf2bf.js` maps each review's `content` to text, measures its width, and schedules starts using scroll speed and spacing. It creates IDs from `dm-init-` plus the list index. Resuming playback can regenerate starts from the current player time. These are browser display positions and IDs, not original native message fields.
- Observed video duration was 168.534 seconds. It is diagnostic player metadata only; no full video was downloaded or independently validated, and no episode metric was inferred from nearby counts.

Saved evidence: `output/browser_followup/observed_overlay.json`, `player_overlay.jpg`, `comments_drawer.jpg`, the downloaded public scripts, and `findings.json` with file hashes and source locations. Six visible overlay nodes were recorded solely as diagnostic evidence, **not as six verified messages**. They were not inserted into either the danmaku or comments dataset. The verified-native CSV has a header and zero rows; accompanying status says **blocked**, not a successfully observed empty native pool. SQLite records an unavailable source receipt and failed collection attempt.

No new native endpoint probe was necessary: the prior actual endpoint response remains error `110001`. This webpage path cannot supply the requested native IDs and offsets, while access to the user's authenticated Chrome session is a separate unresolved tool blocker. This does not prove that every authenticated Hongguo route lacks native danmaku. Expansion to all ten dramas remains gated on a successful genuine single-episode acquisition.

Before follow-up changes, a second SQLite backup was created at `data/backups/before_browser_followup.sqlite`. `output/browser_followup/preservation_check.json` compares all original row values against this backup and checks integrity and foreign keys.

## Existing data and preservation

The starting SQLite database contains 12 dramas and 2,829 episodes: 10 non-demo dramas with 2,826 episode IDs, plus 2 demo dramas with 3 episodes. Both existing danmaku rows and both existing comment rows are synthetic demo records. There are 35 engagement snapshots, of which 30 are non-demo drama-level observations; there are no non-demo episode-level metrics or video assets.

Backup: `data/backups/before_native_collection.sqlite`, made through SQLite's backup API before opening the working database for changes. Every pre-existing row was compared using its original columns and remains present. Only additive schema changes and a failed collection run/event/receipt were added. `output/investigation/preservation_check.json` records the checks. No demo data were deleted or newly inserted into the research database.

## Sources investigated and observed blockers

- Public site: https://hongguoduanju.com/ and https://hongguoduanju.com/detail?series_id=7701328280862854168 . The detail page identifies 北京笔墨留香科技有限公司 in its footer and uses ByteDance-related asset domains. This is direct page evidence, not an independent ownership certification.
- The selected drama is 装穷提亲，娶到全家嫌弃的她, drama `7701328280862854168`, episode 1 `7701328426518465561`. Its public SSR lists 80 episode IDs but `accessible_episode_cnt=3`. Directory coverage is not video availability.
- https://hongguoduanju.com/robots.txt disallows `/player/*/*`. The crawler did not request the player page. No complete video URL, source duration, or episode-level metrics were acquired from the allowed detail page.
- The visible review section is ordinary comments and was not imported as danmaku. No synthetic fallback was used.
- A published third-party implementation identifies a native danmaku wire format: https://github.com/huangxd-/danmu_api/blob/main/danmu_api/sources/hongguo.js . The inspected blob is `31517d4181b88d42611a497aa411f93897530c18`. It is not an official API contract or an authorization grant. Its signature generation and device impersonation code were not incorporated.
- A single unsigned, bounded native request reached `api5-normal-sinfonlinea.fqnovel.com`. HTTP status was 200, but the body was `Code: 110001`, `Message: 未知异常`, `BaseResp.StatusMessage: unknown error`. No data list was returned. This proves failure of this request, not that the episode has zero danmaku, nor that a particular missing credential is conclusively the cause.
- At the initial probe, the user's authenticated session was in the Hongguo mobile app, with no connected mobile session exposed by the tools. The later Chrome login and its separate connection blocker are documented above. No mobile credentials were extracted.
- No official public historical-danmaku export/API was verified during this investigation. No third-party paid data service was purchased or treated as a verified source.

The sandbox initially blocked DNS; the actual public-page fetches and native probe were subsequently run with approved network access. The final native failure is a platform response, not merely the earlier sandbox DNS error.

## Actual acquisition in this run

Saved the real homepage, public detail page, robots policy, public frontend/source references, and the native API error response for investigation. **New real danmaku: 0. Videos: 0. Episode engagement observations: 0.** Existing metadata were preserved, not represented as newly acquired records. No 24-hour live delta was measured.

Evidence:

- `output/native_poc/run_6_page_1.json`: exact unsigned request and native error response.
- `output/native_poc/run_6_result.json`: original failed run. Its first-version error formatter showed `code=None` because the error body uses uppercase `Code`; the parser now reports `110001` correctly. The original evidence was retained unchanged.
- `output/investigation/findings.json`: actual field findings and evidence hashes.
- `output/investigation/robots.html`, `detail.html`, and `detail_ssr.json`: public-source evidence.
- `output/verified_status/episode_status.csv`: all 2,826 non-demo episodes, with unknown metric availability preserved.
- `output/verified_status/episode_engagement.json`: non-demo episode snapshots and comparable deltas (currently absent).

## Commands and incremental behavior

The experimental unsigned probe performs one request by default, checks robots, and stops on access failure. It generates no app signatures, borrows no device identifiers, follows no redirects, and does not retry a platform denial:

```bash
.venv/bin/python -m hongguo native-danmaku \
  --drama-id 7701328280862854168 \
  --episode-id 7701328426518465561 \
  --out output/native_danmaku --max-pages 1
```

A blocked run returns exit code 2. Its receipt records failure, not a zero-message observation. The first attempted request has unknown duration (`0`); no episode duration was invented. If a legitimate source supplies duration, pass `--duration-ms`.

For an authorized raw native response envelope, use:

```bash
.venv/bin/python -m hongguo native-danmaku \
  --drama-id 7701328280862854168 \
  --episode-id 7701328426518465561 \
  --capture /absolute/path/to/authorized_native_envelope.json \
  --access-basis 'Describe the actual authorized export/capture source' \
  --out output/authorized_native
```

The envelope must contain `request.url`, `request.body`, and `response`. It must be the actual response to the native danmaku request, not a renamed comments export. Request context must match the episode, drama, `group_type=30`, and `comment_type=20`. The expected successful response uses `code=0`, `data.data_list[].comment.comment_id`, `common.content.text`, `expand.offset_time`, and `data.common_list_info`. Field semantics come from the inspected interface implementation and still need successful live validation. Header/token material is not needed for offline ingestion and is not copied into its stored request context.

The parser rejects missing IDs, missing/negative/fractional offsets, malformed lists, and API errors. Native offsets remain episode-relative milliseconds, including zero. Message IDs remain exact strings. Ordinary comments cannot enter through this path without the specific native request context and offset fields. A supplied envelope is still provider-asserted evidence, not cryptographic proof of authenticity.

Repeated scans start from playback offset zero and deduplicate by source + episode + message ID. This permits newly posted messages at old playback positions to be discovered. Changed text/offsets update the existing row; raw successful page evidence preserves prior versions. A page and its database checkpoint commit atomically. Pagination is bounded, rejects stuck cursors, and never claims complete history. Pagination semantics are fixture-tested, not live-verified. There is no automatic background polling or deletion detection.

Use `--resume` with the same episode/database to continue after the last committed live page. The checkpoint's evidence file and SHA-256 are checked before network access. Capture imports do not move a live checkpoint. A fresh scan's first-page failure does not inherit an older completed scan's terminal state. A terminal checkpoint returns `already_scanned_partial`, without claiming complete history. Omit `--resume` for subsequent incremental sweeps so late messages at old playback positions can be discovered.

`--retries 2` (default; allowed 0–5) retries connection/timeouts and HTTP 500/502/503/504 with bounded backoff. It does not retry HTTP 401/403/429, a business error inside HTTP 200, or a long/opaque Retry-After. This is recovery from transient failures, not a solution to the platform-access blocker. The native parser and visible-DOM sampler reject the observed generated `dm-init-*` review overlays.

Keep evidence directories separate for separate databases, because filenames use database run IDs. Raw evidence is local and excluded from git by the project's existing `output/` rule.

## Video and engagement improvements

Video downloads use unique temporary files, reject truncated/empty responses, clean up failed transfers, and check ffprobe plus full FFmpeg decoding before promoting a file. Local imports refuse to replace a different existing video. No HLS/DRM support or access-control bypass was added.

Source `duration_seconds` is retained separately from `media_duration_seconds` and `expected_duration_seconds`. `duration_validation` distinguishes missing reference, mismatch, reference conflict, and match. Tolerance is `min(max(0.25 seconds, 2% of expected), 5% of expected)`. This fixes the old three-second tolerance accepting very short previews as full episodes. A manifest cannot silently override a conflicting source duration. Revalidation updates the matching asset record.

Episode metrics require a known episode belonging to the drama. Drama scope cannot carry an episode ID. The same source/observation cannot be duplicated by importing at a later collection time; conflicting values are rejected. Numeric values must be finite and nonnegative. Twenty-four-hour comparisons use the latest observation and the nearest observation within 20–30 hours, with matching episode, metric, source, scope and precision. Decreases are flagged rather than clamped. Missing metrics remain unknown, and no drama heat score is copied to episodes.

```bash
.venv/bin/python -m hongguo episode-status --out output/verified_status
.venv/bin/python -m hongguo report --out output/verified_report
.venv/bin/python -m hongguo export --out output/verified_csv
.venv/bin/python -m unittest discover -s tests -v
```

The general report/export intentionally retains raw mixed-database totals alongside explicitly labeled non-demo counts; the episode-status command excludes demo episodes. Existing demo acceptance/selection workflows are still fixture-oriented and should not be used as proof of a real views-based top ten.

## Verification completed

The initial **43 tests passed**, including full FFmpeg decoding of locally generated test media. The 18 initial new tests cover native request/response validation, exact IDs and zero offsets, repeated and late messages, revisions, page rollback, pagination failure, invalid metrics, same-observation deduplication, latest source/precision-matched deltas, missing metrics, duration conflicts, path traversal, and truncated download cleanup. Fixtures and generated videos run only in temporary test databases. That log remains at `output/investigation/tests.txt`.

After the browser follow-up, **52 tests passed** (`output/browser_followup/tests.txt`). Nine additional tests cover transient recovery, refusal to retry denials, Retry-After handling, exception redaction, cursor/window resumption, failed-page recovery, tampered evidence rejection, generated-review rejection, and first-page failure after an earlier completed scan. These are mock transport tests, not live native collection evidence.

The actual `native-danmaku` command was run against the selected real episode and failed with the saved platform response. `episode-status`, `report`, and `export` were run against the preserved working database. Passing local tests does not resolve the failed live native request.

The official [Douyin interaction guide](https://developer.open-douyin.com/docs/resource/zh-CN/interaction/develop/douyincloud/guide) describes live-stream interactions, not Hongguo recorded-episode danmaku. It was not used as a substitute source.

## Remaining input to finish the live proof of concept

A successful authorized native response for this episode, or a supported platform/provider channel that the local collector can access, is required. Chrome is logged in according to the user but not reachable through the current browser connection; the separately inspected player converts reviews to overlays. A valid source must expose the actual message ID, text, episode mapping and native playback offset. Full video work additionally needs an available authorized file/URL and an independent reference duration. Until that access exists, neither live native collection nor complete video acquisition is achieved.
