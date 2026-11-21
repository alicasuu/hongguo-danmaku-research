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

- Latest UI exploration: [run 44882326465](https://github.com/alicasuu/hongguo-danmaku-research/actions/runs/44882326465) installed the app, dismissed optional Android notifications, and captured the real first-run 《用户协议》/《隐私政策》 consent screen in `theater.png` and `video_attempt.png`. Because these are legal/privacy-consent choices, the CI script intentionally leaves them untouched. A human decision to consent is required before operating the app beyond this screen; no playback or native message result should be inferred from this run.

**Playback verified (2026-11-21):** With the user's explicit authorization, the isolated, unsigned-in emulator accepted the first-run agreement. [Run 44883794463](https://github.com/alicasuu/hongguo-danmaku-research/actions/runs/44883794463) shows actual moving video from 《满院亲戚全是上古大妖》 episode 1, followed by automatic episode 2 playback. Ten distinct 5-second video samples and UI hierarchy dumps are retained as short-lived evidence. The initial sample showed video subtitles, **not confirmed native danmaku**. No research message rows were inferred from subtitles or public comment counts.

**Evidence limits:** This proves installed package launch and real video playback, **not** native message IDs or source timestamped danmaku. App exploration produces visually sampled screenshots, which must never be relabeled as full message-pool data. This workflow does not log into a personal account, read credentials, bypass client/server signing, accept terms, or call private APIs.

The Android emulator action is pinned to `reactivecircus/android-emulator-runner` commit `a421e43855164a8197daf9d8d40fe71c6996bb0d`. No APK binaries, credentials, or personal data are committed to Git; the APK is temporary and screenshots/logs are 7-day workflow artifacts.
