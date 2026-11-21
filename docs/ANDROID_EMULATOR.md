# Android emulator and Hongguo app smoke tests

A **headless Android 15 (API 35) Pixel 7 emulator** now installs and launches the real Hongguo Android app package (`com.phoenix.read`) in an isolated GitHub Actions runner.

- Workflow: [`.github/workflows/android-emulator-smoke.yml`](../.github/workflows/android-emulator-smoke.yml).
- Scripts: [emulator boot](../scripts/android_emulator_smoke.sh), [APK identity and launch](../scripts/android_hongguo_app_smoke.sh).
- Trigger: GitHub Actions > **Android emulator + Hongguo app smoke test** > Run workflow, or pushes touching the workflow/scripts.
- Runtime: GitHub-hosted `ubuntu-latest`, Android 15, Pixel 7, Google APIs x86_64 AVD, adb.
- App: `com.phoenix.read` version `7.4.5.32` (verified with Android `aapt`); APK signature cryptographically verifies with `apksigner`. APK SHA-256: `c4583f645d72b5022f060038a9fd286117f316c6fa7f46990c088083344a7d92`.
- Source: Yingyonghui/AppChina marketplace (a third-party app store), matching the name, developer, package and version listed in Xiaomi and Tencent official app-store listings. The signer certificate was recorded in the CI artifact; the app's distribution provenance was **not** independently attested by the developer.
- Evidence: [successful install and splash/permission screen run](https://github.com/alicasuu/hongguo-danmaku-research/actions/runs/44879942189) and [successful home UI after denying notifications](https://github.com/alicasuu/hongguo-danmaku-research/actions/runs/44880310249). Download the `android-hongguo-app-smoke` artifact from each run (7-day retention), including install log, APK metadata/signature, Android activity report, and actual screenshots.
- Android native ABIs reported by APK: `arm64-v8a`. `adb install` succeeded on the runner's emulator; package presence was verified.

**Evidence limits:** This proves installed package launch and visible app UI, **not** working short-drama video playback or real native timestamped danmaku. App exploration produces visually sampled screenshots, which must never be relabeled as full message-pool data. This workflow does not log into a personal account, read credentials, bypass client/server signing, accept terms, or call private APIs.

The Android emulator action is pinned to `reactivecircus/android-emulator-runner` commit `a421e43855164a8197daf9d8d40fe71c6996bb0d`. No APK binaries, credentials, or personal data are committed to Git; the APK is temporary and screenshots/logs are 7-day workflow artifacts.
