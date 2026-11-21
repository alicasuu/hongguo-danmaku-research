#!/usr/bin/env bash
set -euo pipefail

# UTF-8 input over ADB. Use the project's own GitHub release, never an APK mirror.
keyboard_apk="$(mktemp --suffix=.apk)"
trap 'rm -f "$keyboard_apk"' EXIT
curl --fail --location --silent --show-error --retry 3 --max-time 90 \
  'https://github.com/senzhk/ADBKeyBoard/releases/download/v2.5-dev/keyboardservice-debug.apk' \
  -o "$keyboard_apk"
# Official v2.5-dev GitHub release asset is 18,753 bytes. Verify its exact
# published SHA-256, rather than rejecting it using an incorrect size floor.
test "$(stat -c%s "$keyboard_apk")" -eq 18753
printf '%s  %s\n' '41a8a0996d7397a2390d1ca16a75cb66c4a7bdaa89cf4e63600a4d3fb346fbbb' "$keyboard_apk" | sha256sum --check --status
unzip -tqq "$keyboard_apk"
adb install -r "$keyboard_apk"
# On a newly booted API-35 emulator, PackageManager may need several
# seconds to register a newly installed input-method service.
for attempt in $(seq 1 20); do
  if adb shell ime list -a 2>/dev/null | grep -F -q 'com.android.adbkeyboard/.AdbIME'; then
    break
  fi
  sleep 2
done
adb shell ime list -a | grep -F 'com.android.adbkeyboard/.AdbIME'
adb shell ime enable com.android.adbkeyboard/.AdbIME
adb shell ime set com.android.adbkeyboard/.AdbIME
adb shell ime list -s | grep 'com.android.adbkeyboard'
