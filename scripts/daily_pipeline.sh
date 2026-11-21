#!/usr/bin/env bash
# One-shot V1 entry point. No cron, watch loop or 24-hour follow-up.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec python -m hongguo.v1_android --max-episodes "${V1_BATCH_SIZE:-20}"
