#!/usr/bin/env bash
set -euo pipefail

# UTF-8 input over ADB. Use the project's own GitHub release, never an APK mirror.
keyboard_apk="$(mktemp --suffix=.apk)"
trap 'rm -f "$keyboard_apk"' EXIT
curl --fail --location --silent --show-error --retry 3 --max-time 90 \
  'https://github.com/senzhk/ADBKeyBoard/releases/download/v2.5-dev/keyboardservice-debug.apk' \
  -o "$keyboard_apk"
test "$(stat -c%s "$keyboard_apk")" -gt 25000
unzip -tqq "$keyboard_apk"
adb install -r "$keyboard_apk"
adb shell ime enable com.android.adbkeyboard/.AdbIME
adb shell ime set com.android.adbkeyboard/.AdbIME
adb shell ime list -s | grep 'com.android.adbkeyboard'
