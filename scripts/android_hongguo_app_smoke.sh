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
# Dismiss the Android notification prompt without granting access or signing in.
adb shell input tap 540 1480
sleep 18
adb exec-out screencap -p > "$outdir/after_notification.png"

# Explore only publicly visible app screens. No account login, no permission grants.
sleep 50
adb exec-out screencap -p > "$outdir/home_after_68s.png"
timeout 25s adb shell uiautomator dump /sdcard/hongguo-home.xml > /dev/null 2>&1 || true
adb pull /sdcard/hongguo-home.xml "$outdir/home_ui.xml" > /dev/null 2>&1 || true

# Tap the Theater tab, which is visibly labeled 剧场 on the app's home screen.
adb shell input tap 411 2270
sleep 35
adb exec-out screencap -p > "$outdir/theater.png"
timeout 25s adb shell uiautomator dump /sdcard/hongguo-theater.xml > /dev/null 2>&1 || true
adb pull /sdcard/hongguo-theater.xml "$outdir/theater_ui.xml" > /dev/null 2>&1 || true

# Attempt to open the first visible public drama. Collect a short, sampled
# screen sequence only; screenshots alone do not count as complete native danmaku.
adb shell input tap 527 645
sleep 25
adb exec-out screencap -p > "$outdir/video_attempt.png"
for frame in $(seq -w 1 10); do
  sleep 5
  adb exec-out screencap -p > "$outdir/video_sample_$frame.png"
done
adb shell input tap 540 1200
sleep 2
adb exec-out screencap -p > "$outdir/video_controls.png"
timeout 25s adb shell uiautomator dump /sdcard/hongguo-video.xml > /dev/null 2>&1 || true
adb pull /sdcard/hongguo-video.xml "$outdir/video_ui.xml" > /dev/null 2>&1 || true
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
