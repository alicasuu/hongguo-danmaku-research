# Research collection acceptance — 2026-11-09 Pacific

The project is **verified partial**, not complete. The generated source of truth is `output/research_completion/report/quality_report.json`, with a readable `report.html`, nine-row `acceptance.csv`, cross-drama comparison, all-episode inventory and scaling scenarios.

## Measured outcomes

- 10 real dramas and all 2,826 stored episode IDs reconcile against fresh source directories in the same order. No original row changed or disappeared.
- 150 episode-comment previews (15 on the first episode of each drama) and 90 drama-review previews (9 per drama): **240 unique records**, 264 observations including the pilot repeat. Original text, source posting times, likes, URL and capture times are retained. Source message IDs and parent IDs were absent; they remain NULL. Reply count collected is zero, not proof that the platform has no replies.
- 147 non-demo metric observations in total, including 22 episode-level observations on 10 episodes (likes and comment totals). The original 30 real drama metrics remain. There are no verified view counts and no comparable 24-hour pairs yet.
- 10 platform-provided first-episode durations; no downloaded full-video durations.
- Native timed danmaku: **0**. Verified full Hongguo videos: **0**.
- Existing visible review overlays remain separate: 22 records, 137 sightings across 10 first episodes. They do not satisfy the native requirement.
- Platform category labels: 4 AI, 5 comic, 1 live action. These are neither model predictions nor independent human assessments of facial realism, dubbing or subtitle quality.
- All existing SQLite rows, including intentionally labeled demo rows, are preserved. `preservation_check.json` compares every old column and row with the pre-work backup; integrity check is `ok` and foreign-key violations are empty.

## Actual executions

The six-page single-drama pilot collected 24 comments/reviews and 27 metrics. The initial all-10 run collected 23 of 24 pages and rejected one mismatched drama identity. A normal subsequent check returned the correct identity. `--resume` reused those 23 saved pages and fetched only the missing page, adding 15 comments and two metrics. The final 24-page batch therefore covers public first-player and detail pages for all 10 dramas, plus four chart pages. It does not cover all episode comment pools. Pilot plus batch retain 30 successful page snapshots.

The native `sinfonlineb` single-episode probe returned application error 110001, zero pages and zero records. The precise request/response is retained without credentials. See `REPOSITORY_COMPARISON.md` for source findings and the blocked authorized-access dependency.

The source-duration follow-up (168,554 ms from the actual public player metadata) also returned 110001. Replaying the completed 24-page batch added zero comments and zero metrics with no failures. **80 automated tests passed**; fixtures remain outside the research database. CSV verification confirms 2,826 inventory rows, 240 real comment/review rows, 147 non-demo metric rows, 10 comparison rows and zero native rows.

## Reusable commands

Run from the project root; use a new output directory for each new snapshot:

```bash
.venv/bin/python -m hongguo research-snapshot --out output/new_snapshot --delay 2
.venv/bin/python -m hongguo research-snapshot --out output/new_snapshot --resume
.venv/bin/python -m hongguo research-report --out output/research_completion/report
.venv/bin/python -m hongguo episode-status --out output/research_completion/episode_status
.venv/bin/python -m hongguo export --out output/research_completion/csv
.venv/bin/python -m unittest discover -s tests -v
```

Authorized files can use the existing media manifest with `media-import`. For permitted direct HTTPS full-file URLs, add `--download-authorized --allowed-host HOST --resume-transfers`; rights and full-episode assertions and independent expected duration are required. No full-video source was available in this run.

For a legitimate provider export, `native-danmaku --capture FILE --access-basis DESCRIPTION --drama-id ID --episode-id ID --out NEW_DIR` validates the request context and raw response offline. Do not supply cookies, passwords or auth headers. Do not import a player's cleaned `{time,text}` list as original native records. `--resume` applies to live scans; a new default scan revisits old playback positions for late posts.

## Requirement acceptance

1. Actual-view Top 10: **BLOCKED**; heat rankings only, selection provisional.
2. Complete videos: **BLOCKED**; 0/2,826 verified files.
3. Native danmaku: **BLOCKED**; unsigned request failure and no demonstrated supported export/session route.
4. Episode engagement: **PARTIAL**; first-episode likes/comments collected; 24-hour follow-up pending.
5. Comments/reviews/replies: **PARTIAL**; 240 preview records; full pagination and reply source unavailable.
6. Catalog: **PARTIAL**; all IDs/order reconciled; platform classification collected; completion enum and independent classification unverified.
7. Cross-drama analysis: **PARTIAL**; sourced comparisons produced; human face/voice/subtitle review and native timing analysis pending.
8. Quality report: **PASS** for generating a sourced report that accurately marks missing coverage, not for completing the dataset.
9. Scaling: **PARTIAL**; public-page benchmark measured, media/native/compute costs unmeasured.

Measured successful page traffic: 9,959,176 decoded response bytes across 30 pages; summed request/rate-wait time 60.7176 seconds (not total session wall time or full-video throughput). Mean 282.6 episodes/drama includes a 1,000-episode outlier. Video size (30 MB), bandwidth (20 Mbps), compute ratios and durations in scaling scenarios are assumptions. Native pool sizes and provider prices are unknown; monetary costs remain NULL with a parameterized formula.

## Follow-up

A one-follow-up launchd job was loaded and its initial early run exited successfully as `pending`. Due time: **2026-11-10 20:23 Pacific**, approximately 24 hours after the last baseline page. It checks the UTC deadline locally every five minutes, fetches public previews only after that deadline, then unloads itself. It cannot obtain private/native data. See `SCHEDULING.md` for status and reboot instructions. The follow-up has not happened and is not counted as collected.
