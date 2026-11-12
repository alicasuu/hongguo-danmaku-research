#!/usr/bin/env bash
# Local, user-configured job. Does not fetch private App data or bypass access restrictions.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p output/logs
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
# Users are responsible for depositing lawful real episode-metric/danmaku exports into data/inbox.
python -m hongguo sync-inbox --inbox data/inbox > "output/logs/inbox_${STAMP}.json"
# Public-site metadata only; do not assume rankings are real views.
if [[ "${ENABLE_PUBLIC_CRAWL:-0}" == "1" ]]; then
    python -m hongguo crawl --top 10 --rank hot-drama --delay 3 > "output/logs/public_rank_${STAMP}.json" || true
fi
python -m hongguo report --out output/reports > "output/logs/report_${STAMP}.json"
python -m hongguo audit --top 10 --out output/audit > "output/logs/audit_${STAMP}.json"
printf 'Snapshot cycle finished (UTC): %s\n' "$STAMP"
