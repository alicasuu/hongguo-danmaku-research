#!/usr/bin/env bash
set -euo pipefail

# One-shot, user-authorized first-episode study. Raw screenshots, video and
# audience text must not be attached to a public GitHub Actions run.
mkdir -p output/single_episode_pilot output/single_episode_encrypted
export HONGGUO_V1_BOOTSTRAP_ONLY=1
set +e
bash scripts/android_hongguo_app_smoke.sh
bootstrap_rc=$?
if [ "$bootstrap_rc" -eq 0 ]; then
  bash scripts/v1_install_keyboard.sh
  PYTHONPATH=. python3 scripts/one_episode_full_ocr.py \
    --output output/single_episode_pilot
  capture_rc=$?
else
  capture_rc="$bootstrap_rc"
fi
set -e

# Persist bootstrap debug evidence privately even when navigation fails.
if [ -d output/android_hongguo_app_smoke ]; then
  cp -a output/android_hongguo_app_smoke output/single_episode_pilot/bootstrap
fi

# Encryption runs before the upload-artifact step, including failure cases.
bash scripts/single_episode_encrypt.sh \
  output/single_episode_pilot output/single_episode_encrypted/episode_ocr_pilot
echo "one_episode_capture_exit=${capture_rc}"
exit "$capture_rc"
