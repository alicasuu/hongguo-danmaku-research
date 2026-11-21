#!/usr/bin/env bash
set -euo pipefail

adb wait-for-device
boot_completed="$(adb shell getprop sys.boot_completed | tr -d '\r')"
if [ "$boot_completed" != "1" ]; then
  echo "Android device connected but boot did not complete: $boot_completed" >&2
  exit 1
fi

outdir="output/android_emulator_smoke"
mkdir -p "$outdir"

{
  printf 'ADB device:\n'
  adb devices -l
  printf '\nAndroid release: '
  adb shell getprop ro.build.version.release | tr -d '\r'
  printf 'API level: '
  adb shell getprop ro.build.version.sdk | tr -d '\r'
  printf 'Model: '
  adb shell getprop ro.product.model | tr -d '\r'
  printf 'CPU ABI: '
  adb shell getprop ro.product.cpu.abi | tr -d '\r'
  printf 'Boot completed: %s\n' "$boot_completed"
} | tee "$outdir/device_info.txt"

adb shell am start -a android.intent.action.MAIN -c android.intent.category.HOME
adb exec-out screencap -p > "$outdir/home.png"
test -s "$outdir/home.png"

echo "Android emulator boot, adb, and screenshot checks PASSED."
