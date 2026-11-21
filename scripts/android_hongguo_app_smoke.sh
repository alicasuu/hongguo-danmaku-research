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
adb shell dumpsys activity activities > "$outdir/activities.txt" 2>&1 || true
adb logcat -d -t 800 -s AndroidRuntime:E ActivityTaskManager:I > "$outdir/launch_logcat.txt" 2>&1 || true
if ! adb shell pm path "$package" | grep -q 'package:'; then
  echo "APK installed but package disappeared." >&2
  exit 1
fi
test -s "$outdir/launch.png"
printf '\nRESULT: APP_INSTALLED_AND_LAUNCHED\n' | tee -a "$outdir/report.txt"
echo "Hongguo native Android app installed and launched; emulator screenshot collected."
