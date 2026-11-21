#!/usr/bin/env bash
set -euo pipefail

HONGGUO_V1_BOOTSTRAP_ONLY=1 bash scripts/android_hongguo_app_smoke.sh
bash scripts/v1_install_keyboard.sh

if [ "${V1_PILOT:-false}" = true ]; then
  python -m hongguo.v1_android \
    --output output/v1_pilot \
    --max-episodes 1 \
    --capture-seconds 12 \
    --interval-seconds .75
else
  python -m hongguo.v1_android \
    --max-episodes "${V1_BATCH_SIZE:-20}" \
    --capture-seconds "${V1_CAPTURE_SECONDS:-115}" \
    --interval-seconds .75
fi
