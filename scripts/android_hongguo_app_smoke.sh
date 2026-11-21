#!/usr/bin/env bash
set -euo pipefail

# An isolated CI emulator is used; never sign in or store application credentials.
package="com.phoenix.read"
outdir="output/android_hongguo_app_smoke"
mkdir -p "$outdir"
apk="$(mktemp --suffix=.apk)"
trap 'rm -f "$apk"' EXIT

{
  printf 'App: Hongguo Free Short Drama\n'
  printf 'Expected package: %s\n' "$package"
  printf 'Source: AppChina (Yingyonghui) app-market listing, independently matching Xiaomi and Tencent store metadata\n'
  printf 'Listing: https://semdiy.appchina.com/backend-web/app/download/com.phoenix.read/bd.sem.baidu/sm\n'
} > "$outdir/report.txt"

# Download from the named Android app-market listing, not an unaudited APK mirror.
url="https://mobile.appchina.com/market/download/redirect?p=delivery&package=com.phoenix.read&channel=bd.sem.baidu&force=true"
curl --fail --location --show-error --silent --retry 3 --retry-all-errors --connect-timeout 30 --max-time 420 \
  --user-agent 'Mozilla/5.0 (Linux; Android 14; Pixel 7)' \
  "$url" -o "$apk"

bytes="$(stat -c%s "$apk")"
printf 'Downloaded bytes: %s\n' "$bytes" | tee -a "$outdir/report.txt"
if [ "$bytes" -lt 40000000 ]; then
  echo "The response was too small to be a real Hongguo APK." >&2
  exit 1
fi

if ! unzip -tqq "$apk"; then
  echo "Downloaded content is not a valid APK/ZIP archive." >&2
  exit 1
fi

tools_dir="$(find "$ANDROID_HOME/build-tools" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -1)"
aapt="$tools_dir/aapt"
apksigner="$tools_dir/apksigner"
"$aapt" dump badging "$apk" > "$outdir/badging.txt"
"$apksigner" verify --print-certs "$apk" > "$outdir/signature.txt"
actual_package="$(sed -n "s/^package: name='\([^']*\)'.*/\1/p" "$outdir/badging.txt" | head -1)"
version="$(sed -n "s/^package: .*versionName='\([^']*\)'.*/\1/p" "$outdir/badging.txt" | head -1)"
printf 'APK package: %s\nAPK version: %s\n' "$actual_package" "$version" | tee -a "$outdir/report.txt"
sha256sum "$apk" | sed "s| $apk$|  hongguo.apk|" | tee -a "$outdir/report.txt"
md5sum "$apk" | sed "s| $apk$|  hongguo.apk|" | tee -a "$outdir/report.txt"
unzip -Z1 "$apk" | awk -F/ '/^lib\/[^/]+\// {print $2}' | sort -u > "$outdir/native_abis.txt"
printf 'Native library ABIs:\n' | tee -a "$outdir/report.txt"
tee -a "$outdir/report.txt" < "$outdir/native_abis.txt"

if [ "$actual_package" != "$package" ]; then
  echo "APK package identity differs from the official Android app-store listing." >&2
  exit 1
fi

adb wait-for-device
adb install -r "$apk" 2>&1 | tee "$outdir/install.txt"
adb shell pm path "$package" | tee "$outdir/package_paths.txt"
adb shell monkey -p "$package" -c android.intent.category.LAUNCHER 1 > "$outdir/launch.txt" 2>&1
sleep 15
adb exec-out screencap -p > "$outdir/launch.png"

# Fresh hosted Android devices sometimes show a system launcher ANR *above*
# the app's notification dialog. Dismiss both system overlays in order,
# using the observed UI hierarchy instead of tapping blindly.
dismiss_system_overlays() {
  for iteration in $(seq 1 8); do
    timeout 20s adb shell uiautomator dump /sdcard/hongguo-system.xml > /dev/null 2>&1 || true
    hierarchy="$(adb shell cat /sdcard/hongguo-system.xml 2>/dev/null || true)"
    if [[ "$hierarchy" == *"isn't responding"* ]]; then
      printf 'Dialog %s: dismiss system launcher ANR\\n' "$iteration" >> "$outdir/report.txt"
      adb shell input tap 500 1230
      sleep 7
    elif [[ "$hierarchy" == *"permission_deny_button"* ]]; then
      printf 'Dialog %s: deny optional notifications\\n' "$iteration" >> "$outdir/report.txt"
      adb shell input tap 540 1470
      sleep 6
    else
      printf 'Dialog %s: no blocking system overlay\\n' "$iteration" >> "$outdir/report.txt"
      break
    fi
  done
}
dismiss_system_overlays
sleep 5
adb exec-out screencap -p > "$outdir/after_notification.png"

# This fresh, isolated emulator is never signed in. The user explicitly
# approved accepting Hongguo's first-run agreement/privacy notice for this
# research session on 2026-11-21. Only accept after verifying exact UI labels.
timeout 20s adb shell uiautomator dump /sdcard/hongguo-consent.xml > /dev/null 2>&1 || true
consent_ui="$(adb shell cat /sdcard/hongguo-consent.xml 2>/dev/null || true)"
if [[ "$consent_ui" == *"欢迎使用红果免费短剧"* && "$consent_ui" == *"同意并继续"* ]]; then
  printf 'First-run notice: user-authorized agreement accepted\\n' >> "$outdir/report.txt"
  adb shell input tap 540 1470
  sleep 10
else
  printf 'First-run notice: absent or unrecognized; no blind consent tap\\n' >> "$outdir/report.txt"
fi
dismiss_system_overlays
adb exec-out screencap -p > "$outdir/after_consent.png"
timeout 20s adb shell uiautomator dump /sdcard/hongguo-after-consent.xml > /dev/null 2>&1 || true
adb pull /sdcard/hongguo-after-consent.xml "$outdir/after_consent_ui.xml" > /dev/null 2>&1 || true

# The app has been seen auto-playing a drama after fresh consent, but a
# separate run fell back to the Android launcher. Verify foreground state
# before EVERY tap so a launcher search is never mistaken for Hongguo.
is_app_foreground() {
  adb shell dumpsys activity activities > "$outdir/foreground_check.txt" 2>&1 || true
  grep -q 'topResumedActivity=.*com.phoenix.read/' "$outdir/foreground_check.txt"
}
ensure_app_foreground() {
  for attempt in 1 2 3; do
    if is_app_foreground; then return 0; fi
    printf 'Reopening official app, attempt %s\\n' "$attempt" >> "$outdir/report.txt"
    adb shell monkey -p "$package" -c android.intent.category.LAUNCHER 1 > /dev/null 2>&1 || true
    sleep 12
  done
  is_app_foreground
}
capture_ui() {
  local stage="$1"
  timeout 20s adb shell uiautomator dump "/sdcard/hongguo-$stage.xml" > /dev/null 2>&1 || true
  adb pull "/sdcard/hongguo-$stage.xml" "$outdir/${stage}_ui.xml" > /dev/null 2>&1 || true
}
has_player_ui() {
  local path="$1"
  [ -s "$path" ] && grep -Eq '全屏观看|content-desc="清屏"|text="第[0-9]+集"' "$path"
}

sleep 18
ensure_app_foreground || true
adb exec-out screencap -p > "$outdir/home_after_68s.png"
capture_ui home
if ! has_player_ui "$outdir/home_ui.xml"; then
  # In a real home tab, 剧场 is the second bottom-navigation item.
  if ensure_app_foreground; then
    adb shell input tap 410 2270
    sleep 14
  fi
fi
adb exec-out screencap -p > "$outdir/theater.png"
capture_ui theater
if ! has_player_ui "$outdir/theater_ui.xml"; then
  # Open the first visible drama card only while inside Hongguo.
  if ensure_app_foreground; then
    adb shell input tap 527 645
    sleep 15
  fi
fi
ensure_app_foreground || true
adb exec-out screencap -p > "$outdir/video_attempt.png"
capture_ui video

if ensure_app_foreground; then
  # Some video-heavy app screens make uiautomator dump time out even though
  # the actual video is visible in screenshot evidence. Inspect the menu
  # after successful in-app navigation without relying on that XML alone.
  printf 'In-app video candidate; inspecting menu and short sequence\\n' >> "$outdir/report.txt"
  adb shell input tap 540 1200
  sleep 2
  adb exec-out screencap -p > "$outdir/video_controls.png"
  adb shell input tap 1000 192
  sleep 3
  adb exec-out screencap -p > "$outdir/video_options.png"
  capture_ui video_options
  # The 2026-11-21 genuine player screenshot and UI hierarchy show the
  # off-state Danmaku switch at bounds [901,1777][996,1830]. Toggle only
  # when that exact control is confirmed in the current app UI.
  if [ -s "$outdir/video_options_ui.xml" ] && grep -q 'text="弹幕"' "$outdir/video_options_ui.xml"; then
    printf 'Native Danmaku settings control verified; enabling user-authorized overlay\\n' >> "$outdir/report.txt"
    adb shell input tap 950 1803
    sleep 3
    adb exec-out screencap -p > "$outdir/video_danmaku_enabled.png"
    capture_ui video_danmaku_enabled
  else
    printf 'Native Danmaku control not in current menu; not toggling blindly\\n' >> "$outdir/report.txt"
  fi
  # Dismissing the settings sheet pauses the video; the large centered
  # play control is at [540,1100] in the verified paused screenshot.
  adb shell input keyevent KEYCODE_BACK
  sleep 2
  adb exec-out screencap -p > "$outdir/video_after_options.png"
  adb shell input tap 540 1100
  sleep 4
  adb exec-out screencap -p > "$outdir/video_after_resume.png"
  # Capture real in-app playback after enabling Danmaku. These are
  # observational screenshots, not native message API response records.
  for frame in $(seq -w 1 35); do
    if ! ensure_app_foreground; then break; fi
    adb exec-out screencap -p > "$outdir/danmaku_frame_$frame.png"
    sleep 3
  done
else
  printf 'Video player UI not confirmed in this attempt\\n' >> "$outdir/report.txt"
fi
adb shell dumpsys activity activities > "$outdir/activities.txt" 2>&1 || true
adb logcat -d -t 800 -s AndroidRuntime:E ActivityTaskManager:I > "$outdir/launch_logcat.txt" 2>&1 || true
if ! adb shell pm path "$package" | grep -q 'package:'; then
  echo "APK installed but package disappeared." >&2
  exit 1
fi
test -s "$outdir/launch.png"
test -s "$outdir/after_notification.png"
test -s "$outdir/theater.png"
test -s "$outdir/video_attempt.png"
printf '\nRESULT: APP_INSTALLED_AND_LAUNCHED\n' | tee -a "$outdir/report.txt"
echo "Hongguo native Android app installed and launched; emulator screenshot collected."
