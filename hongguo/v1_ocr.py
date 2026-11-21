"""One-pass screenshot OCR for V1. All offsets are *estimates*, never native times.

Only text inside the configured player danmaku ROI is eligible. Text in normal
subtitles, reviews, or other UI regions is not automatically a danmaku record.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
import csv
import io
import re
import subprocess


@dataclass(frozen=True)
class SeenText:
    text: str
    first_seen_ms: int
    confidence: float
    screenshot: str
    bbox: tuple[int, int, int, int]


def normalize(text: str) -> str:
    return re.sub(r"[\s\u200b\u200c\u200d，。！？,.!?\-—·:：]+", "", text).casefold()


def is_valid_danmaku_text(text: str) -> bool:
    plain = normalize(text)
    if re.fullmatch(r"第\d+集|\d+(?:\.\d+)?x|(?:播放|收藏|评论|分享|点赞|热榜)\d*", plain):
        return False
    return 3 <= len(plain) <= 80 and bool(re.search(r"[\u4e00-\u9fffA-Za-z]", plain))


def group_tesseract_tsv(raw: str, confidence_floor: float = 45.0):
    """Group OCR tokens by visual line and retain bounding boxes/confidence."""
    rows = csv.DictReader(io.StringIO(raw), delimiter="\t")
    lines: dict[tuple[str, ...], list[dict]] = {}
    for row in rows:
        try:
            conf = float(row["conf"])
            text = row["text"].strip()
            box = tuple(int(row[k]) for k in ("left", "top", "width", "height"))
        except (KeyError, ValueError, TypeError):
            continue
        if conf < confidence_floor or not text:
            continue
        key = tuple(row.get(k, "") for k in ("page_num", "block_num", "par_num", "line_num"))
        lines.setdefault(key, []).append({"text": text, "conf": conf, "box": box})
    result = []
    for tokens in lines.values():
        tokens.sort(key=lambda t: t["box"][0])
        text = "".join(t["text"] for t in tokens)
        if not is_valid_danmaku_text(text):
            continue
        x0 = min(t["box"][0] for t in tokens)
        y0 = min(t["box"][1] for t in tokens)
        x1 = max(t["box"][0] + t["box"][2] for t in tokens)
        y1 = max(t["box"][1] + t["box"][3] for t in tokens)
        result.append({"text": text, "confidence": round(sum(t["conf"] for t in tokens) / len(tokens), 1),
                       "bbox": (x0, y0, x1, y1)})
    return result


def tesseract_tsv(image: Path, *, lang: str = "chi_sim+eng", timeout: int = 30) -> str:
    cmd = ["tesseract", str(image), "stdout", "-l", lang, "--psm", "11", "tsv"]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)
    return result.stdout


def crop_danmaku_zone(screenshot: Path, output: Path) -> tuple[int, int]:
    """Return (left, top) ROI origin; no player detection is inferred here."""
    from PIL import Image, ImageEnhance
    with Image.open(screenshot) as im:
        w, h = im.size
        if w >= h:  # full-screen landscape player
            left, top, right, bottom = int(w * .025), int(h * .055), int(w * .975), int(h * .59)
        else:  # Native portrait app displays a 16:9 video near top of screen.
            # Its lower 2/3 contains controls, reviews and unrelated text.
            left, top, right, bottom = int(w * .025), int(h * .075), int(w * .975), int(h * .26)
        roi = ImageEnhance.Contrast(im.crop((left, top, right, bottom)).convert("RGB")).enhance(1.55)
        roi.save(output)
    return left, top


class EpisodeOCRTracker:
    """First observation of a moving text item, with short-window de-duplication."""

    def __init__(self, *, repeat_window_ms: int = 8000, similarity: float = .94):
        self.repeat_window_ms = repeat_window_ms
        self.similarity = similarity
        self.items: list[SeenText] = []

    def ingest(self, observed_ms: int, rows: list[dict], screenshot: str):
        added = []
        for row in rows:
            text = str(row["text"]).strip()
            if not is_valid_danmaku_text(text):
                continue
            norm = normalize(text)
            bbox = tuple(row.get("bbox", (0, 0, 0, 0)))
            for index, prev in enumerate(self.items):
                prev_norm = normalize(prev.text)
                overlap = min(len(norm), len(prev_norm)) >= 4 and (norm in prev_norm or prev_norm in norm)
                close = SequenceMatcher(None, norm, prev_norm).ratio() >= self.similarity
                in_window = 0 <= observed_ms - prev.first_seen_ms <= self.repeat_window_ms
                # Text moves horizontally. Vertical position should stay stable;
                # substring matching repairs left/right clipped early sightings.
                same_lane = abs((bbox[1] + bbox[3]) - (prev.bbox[1] + prev.bbox[3])) <= 80
                if in_window and same_lane and (close or overlap):
                    if len(norm) > len(prev_norm) or (len(norm) == len(prev_norm) and float(row.get("confidence",0)) > prev.confidence):
                        self.items[index] = SeenText(text=text, first_seen_ms=prev.first_seen_ms,
                                                     confidence=float(row.get("confidence",0)), screenshot=screenshot,
                                                     bbox=bbox)
                    break
            else:
                item = SeenText(text=text, first_seen_ms=max(observed_ms, 0),
                                confidence=float(row.get("confidence", 0)), screenshot=screenshot,
                                bbox=bbox)
                self.items.append(item)
                added.append(item)
                continue
        return added


def ocr_frame(screenshot: Path, cropped: Path, *, elapsed_ms: int):
    left, top = crop_danmaku_zone(screenshot, cropped)
    rows = group_tesseract_tsv(tesseract_tsv(cropped))
    for row in rows:
        x0, y0, x1, y1 = row["bbox"]
        row["bbox"] = (x0 + left, y0 + top, x1 + left, y1 + top)
    return {"observed_ms": elapsed_ms, "rows": rows}
