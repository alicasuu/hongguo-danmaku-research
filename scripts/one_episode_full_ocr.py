#!/usr/bin/env python3
"""One Android episode, continuous recording and 2-fps screen-danmaku OCR.

For a disposable emulator research pilot. UI-only evidence is not a native
danmaku API export. It will refuse success unless video progress spans the
episode from its start to its end. All output is private until encrypted.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from PIL import Image
from hongguo import v1_android as native
from hongguo.v1_ocr import EpisodeOCRTracker, ocr_frame, tesseract_tsv, group_tesseract_tsv


def receipt(out: Path, **fields):
    out.mkdir(parents=True, exist_ok=True)
    with (out / "pilot_receipt.json").open("w", encoding="utf-8") as file:
        json.dump(fields, file, indent=2, ensure_ascii=False)


def screenshot(app, out: Path, name: str):
    path = out / f"{name}.png"
    app.screenshot(path)
    return path


def progress(path: Path):
    """Scrubber X relative to the observed Hongguo 1080x2400 UI."""
    from PIL import Image
    with Image.open(path) as image:
        im = image.convert("RGB")
        w, h = im.size
        if not 0.43 <= w / h <= 0.47:
            return None
        scale = w / 1080
        y = round(h * 2186 / 2400)
        l, r = round(w * 42 / 1080), round(w * 1039 / 1080)
        found = []
        for x in range(l, r + 1):
            n = 0
            for yy in range(y - 5, y + 6):
                red, green, blue = im.getpixel((x, yy))
                if min(red, green, blue) > 219 and max(red, green, blue) - min(red, green, blue) < 20:
                    n += 1
            if n >= 5:
                found.append(x)
        if not found:
            return None
        groups = [[found[0]]]
        for x in found[1:]:
            if x - groups[-1][-1] <= max(2, round(scale * 2)):
                groups[-1].append(x)
            else:
                groups.append([x])
        groups.sort(key=len, reverse=True)
        if len(groups[0]) < 4 or (len(groups) > 1 and len(groups[1]) >= .75 * len(groups[0])):
            return None
        return max(0., min(1., (((groups[0][0] + groups[0][-1]) / 2) - l) / (r - l)))


def visible_series_title(image: Path, title: str):
    """The lower player card displays a clipped title; require its long prefix."""
    with Image.open(image) as original:
        w, h = original.size
        crop = image.parent / "title_verification_crop.png"
        original.crop((0, int(.78*h), int(.78*w), int(.90*h))).save(crop)
    rows = group_tesseract_tsv(tesseract_tsv(crop), confidence_floor=25, allow_short=True)
    normalized = "".join(r["text"] for r in rows).replace(" ", "")
    wanted = title.replace(" ", "")[:6]
    return wanted in normalized, normalized[:80]


def navigate(app, out: Path, title: str, episode: int):
    nav = out / "navigation"
    nav.mkdir(parents=True, exist_ok=True)
    exact_error = ""
    try:
        if not native.exact_search(app, title, nav):
            raise RuntimeError("search card title verification failed")
        candidate = screenshot(app, nav, "from_exact_search")
        matched, text = visible_series_title(candidate, title)
        if not matched:
            raise RuntimeError(f"search opened uncertain player: {text!r}")
    except Exception as error:
        exact_error = f"{type(error).__name__}: {error}"
        # Independent fallback from the earlier verified Android smoke trial:
        # the theater's first visible card opened this particular series.
        # Never assume that a dynamic recommendation still matches: verify it.
        for _ in range(3):
            app.back()
            time.sleep(.6)
        app.run("shell", "monkey", "-p", "com.phoenix.read", "-c",
                "android.intent.category.LAUNCHER", "1", check=False)
        time.sleep(3)
        app.tap(410, 2270)
        time.sleep(7)
        screenshot(app, nav, "theater_fallback")
        app.tap(527, 645)
        time.sleep(10)
        candidate = screenshot(app, nav, "opened_fallback")
        matched, text = visible_series_title(candidate, title)
        if not matched:
            raise RuntimeError(f"Neither exact search ({exact_error}) nor theater card opened target; "
                               f"observed lower card={text!r}")
    # Rewind via visible episode selector when available, else require an
    # independently visible episode number in native UI/screenshot.
    try:
        native.select_episode(app, episode, nav)
    except Exception:
        text = app.xml()
        if f"第{episode}集" not in text:
            verify_frame = screenshot(app, nav, "episode_label_check")
            lines = group_tesseract_tsv(tesseract_tsv(verify_frame), confidence_floor=30)
            if not any(f"第{episode}集" in row["text"] for row in lines):
                raise RuntimeError("Episode label could not be verified")
    screenshot(app, nav, "episode_verified")
    print(json.dumps({"navigation":"target_and_episode_verified", "fallback_reason":exact_error},
                     ensure_ascii=False), flush=True)


def record_episode(app, out: Path, *, ceiling_seconds=120., interval=.5):
    native.enable_danmaku(app, out)
    destination = "/sdcard/hongguo_single_episode.mp4"
    raw = out / "android_screen_recording.mp4"
    # Android screenrecord has a 180s ceiling. One first episode was seen to
    # last about 88s, so the 120s pilot leaves margin for pre-roll and outro.
    limit = min(179, math.ceil(ceiling_seconds + 12))
    capture_start = datetime.now(timezone.utc)
    proc = subprocess.Popen([app.adb, "shell", "screenrecord", "--bit-rate", "1600000",
                             "--time-limit", str(limit), destination],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    time.sleep(1.2)
    if proc.poll() is not None:
        raise RuntimeError("recording exited before rewind")
    try:
        app.tap(540, 1100)
        before = screenshot(app, out, "before_rewind")
        fraction = progress(before)
        if fraction is None:
            raise RuntimeError("cannot read player scrubber")
        x = round(42 + fraction * 997)
        app.run("shell", "input", "swipe", str(x), "2186", "42", "2186", "250")
        time.sleep(.6)
        post = screenshot(app, out, "after_rewind")
        reset = progress(post)
        if reset is None or reset > .025:
            raise RuntimeError(f"00:00 rewind not confirmed (progress={reset})")
        # Controls may pause after drag; only resume the visible player.
        app.tap(540, 1100)
        time.sleep(ceiling_seconds + 1)
    finally:
        proc.wait(timeout=ceiling_seconds + 60)
    app.run("pull", destination, str(raw), timeout=90)
    if not raw.exists() or raw.stat().st_size < 100000:
        raise RuntimeError("missing continuous Android recording")
    # Extract fixed-frequency PNGs offline. ADB screencap on each tick would
    # block and create timing drift in the device's real playback.
    extraction = out / "frames"
    extraction.mkdir(exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
                    "-vf", f"fps={1/interval:.4f}", "-start_number", "0",
                    str(extraction / "frame_%05d.png")], check=True, timeout=ceiling_seconds*5)
    frames = sorted(extraction.glob("frame_*.png"))
    if not frames:
        raise RuntimeError("zero extracted PNGs")
    # Find first near-zero frame *following* a rewind; keep a receipt for audit.
    marks = [(i, progress(p)) for i, p in enumerate(frames)]
    start = next((i for i, p in marks[:40] if p is not None and p <= .025), None)
    if start is None:
        raise RuntimeError("continuous recording does not show 00:00")
    end = next((i for i,p in marks[start+1:] if p is not None and p >= .98), None)
    if end is None:
        raise RuntimeError(f"no verified near-end progress in {len(frames)} frames")
    selected = frames[start:end+1]
    if not .5*(len(selected)-1) >= 20:
        raise RuntimeError("implausibly short sampled episode")
    tracker = EpisodeOCRTracker(repeat_window_ms=7000)
    errors = []
    for i, frame in enumerate(selected):
        cropped = frame.with_name(frame.stem + "_roi.png")
        try:
            candidate = ocr_frame(frame, cropped, elapsed_ms=round(i*interval*1000))
            tracker.ingest(candidate["observed_ms"], candidate["rows"], str(frame))
        except Exception as error:
            errors.append({"frame": frame.name, "error": str(error)})
        finally:
            cropped.unlink(missing_ok=True)
    keep = {Path(x.screenshot) for x in tracker.items}
    keep.add(selected[0]); keep.add(selected[-1]); keep.add(before); keep.add(post)
    for frame in frames:
        if frame not in keep:
            frame.unlink(missing_ok=True)
    results = out / "screen_danmaku_OCR_candidates.csv"
    with results.open("w", newline="", encoding="utf-8-sig") as file:
        fieldnames = ["text", "video_offset_ms_estimated", "timestamp_source",
                      "ocr_confidence", "source_screenshot", "captured_at_utc_estimated",
                      "platform_message_id", "platform_sent_at", "review_status"]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({"text": x.text, "video_offset_ms_estimated": x.first_seen_ms,
                          "timestamp_source": "ocr_estimated", "ocr_confidence": x.confidence,
                          "source_screenshot": str(Path(x.screenshot).relative_to(out)),
                          "captured_at_utc_estimated": (capture_start+timedelta(milliseconds=x.first_seen_ms)).isoformat(),
                          "platform_message_id": "", "platform_sent_at": "",
                          "review_status": "unverified_ocr_candidate"}
                         for x in tracker.items)
    receipt(out, status="recorded_00_to_end", first_frame_index=start, last_frame_index=end,
            episode_seconds_estimated=round((len(selected)-1)*interval, 3),
            raw_video=str(raw.relative_to(out)),
            sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
            frame_sampling_seconds=interval, extracted_frames=len(selected),
            ocr_candidate_count=len(tracker.items), ocr_errors=errors,
            note="Candidate text is visible screen OCR, not native platform danmaku API.")
    return len(tracker.items)


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--output", type=Path, default=Path("output/single_episode_pilot"))
    args.add_argument("--series-title", default="全球死考：刚下刑场你让我去考试一季")
    args.add_argument("--episode", type=int, default=1)
    opts = args.parse_args()
    out = opts.output
    out.mkdir(parents=True, exist_ok=True)
    try:
        app = native.Android()
        navigate(app, out, opts.series_title, opts.episode)
        count = record_episode(app, out)
        print(json.dumps({"pilot":"complete", "ocr_candidates":count}), flush=True)
    except Exception as error:
        receipt(out, status="failed", error=f"{type(error).__name__}: {error}")
        print(json.dumps({"pilot":"failed", "error":str(error)}, ensure_ascii=False), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
