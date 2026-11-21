# Android emulator test environment

The repo includes a **headless Android 35 emulator smoke test** on GitHub Actions, so local Docker/KVM or Android Studio are not prerequisites for the smoke check.

- Workflow: [`.github/workflows/android-emulator-smoke.yml`](../.github/workflows/android-emulator-smoke.yml)
- Script: [`scripts/android_emulator_smoke.sh`](../scripts/android_emulator_smoke.sh)
- Trigger: GitHub Actions > **Android emulator smoke test** > **Run workflow**, and on changes to the workflow or smoke script on `main`.
- Runtime: GitHub-hosted `ubuntu-latest`; Android API 35, Google APIs, x86_64, Pixel 7 AVD.
- Validation: `adb wait-for-device`, `sys.boot_completed=1`, OS/API/model/ABI properties, launch HOME, capture emulator screenshot.
- Evidence: download the `android-emulator-smoke` workflow artifact (7-day retention), containing `device_info.txt` and `home.png`.

This is a **device/runtime setup check only**. It does **not** install the Hongguo APK, log into any personal account, call native danmaku endpoints, or collect platform data. Those steps require a separately provided, authorized app/source and explicit test plan. No credentials, app identifiers, or private research outputs are committed here.

The Android emulator action is pinned to `reactivecircus/android-emulator-runner` v2 commit `a421e43855164a8197daf9d8d40fe71c6996bb0d`; the job configures KVM when available and falls back to software acceleration otherwise.
