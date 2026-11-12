# Week 1 research update: Hongguo collection pilot

## Slide 1 — Design and source validation

- Goal: top 10 micro-dramas; separate composite heat from verified views.
- Proposed schema: drama → episode → video/danmaku/comments/engagement.
- Verified accessible public sources; record robots/terms/permission status.
- Explain whether full videos and true playback-timed danmaku are actually obtainable.

## Slide 2 — Actual collection progress

- # selected dramas / requested 10; # real dramas with IDs and metadata.
- # episode IDs collected vs declared total; # technically verified full videos.
- # actual danmaku with native timestamps; # comments and replies.
- # episode-level metrics and 24h comparisons.
- Missing records: what is inaccessible, not estimated zeros.

## Slide 3 — Bottlenecks, coverage and scale

- Top bottlenecks: source access, signed/DRM video, native danmaku time positions, API/source mapping, storage.
- Show actual measured throughput where available; differentiate assumed estimates.
- Next: authorization; 1 fully validated drama; expand to 10; then scale to 100 and 1000.

## Short spoken update (edit counts from actual report)

This week I built a reproducible data collection pipeline for Hongguo micro-dramas. It collects public ranking and episode metadata, stores it in SQLite, supports incremental engagement snapshots and authorized video, danmaku, and comment imports, and generates a coverage report. One key limitation is that the public ranking shows a composite heat score rather than verified views. Another is that we still need a permitted source for complete episode videos and authentic timestamped danmaku. I'm validating these before scaling from the initial 10 dramas to a larger collection.
