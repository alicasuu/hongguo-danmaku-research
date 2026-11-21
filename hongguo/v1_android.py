"""Hongguo V1: frozen-catalog, one-pass, UI-only evidence collection.

This module does not access app-private data or the network. UI text is evidence,
never proof that a metric is available if it was not actually visible.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from xml.etree import ElementTree as ET

from .v1_ocr import EpisodeOCRTracker, group_tesseract_tsv, ocr_frame, tesseract_tsv

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "data" / "frozen"
CSV_HEADERS = {
    "episodes": ["snapshot","series_id","series_title","episode_no","source_episode_id","captured_at_utc","status","failure_reason","verified_title","verified_episode","ui_episode_label","full_video_file","actual_media_duration_seconds","expected_duration_seconds","full_video_verified","video_sha256","ui_xml_file","raw_ui_text_file"],
    "danmaku": ["snapshot","series_id","episode_no","source_episode_id","text","video_offset_ms_estimated","timestamp_source","timestamp_uncertainty_ms","message_id","posted_at_utc","captured_at_utc","ocr_confidence","screenshot_file","bbox","evidence_type"],
    "metrics": ["snapshot","series_id","episode_no","metric_scope","metric_name","raw_display","numeric_value","captured_at_utc","source","ui_xml_file","status"],
    "comments": ["snapshot","series_id","episode_no","text","posted_at_raw","like_count_raw","parent_comment_id","comment_id","captured_at_utc","source","ui_xml_file","partial_preview"],
}


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def load_frozen():
    with (FROZEN / "series_catalog_2026-11-21.csv").open(encoding="utf-8-sig") as f:
        series = list(csv.DictReader(f))
    with (FROZEN / "episode_catalog_2026-11-21.csv").open(encoding="utf-8-sig") as f:
        episodes = list(csv.DictReader(f))
    if len(series) != 10 or len(episodes) != 999:
        raise ValueError(f"Unexpected frozen inventory: {len(series)} series, {len(episodes)} episodes")
    ranks = [int(s["rank"]) for s in series]
    if ranks != list(range(1, 11)):
        raise ValueError("Frozen series rank must be exactly 1..10")
    expected = [(int(s["rank"]), s["series_id"], s["series_title"]) for s in series]
    order = [(int(e["rank"]), e["series_id"], e["series_title"]) for e in episodes]
    if sorted(set(order)) != expected:
        raise ValueError("Episodes contain unknown/missing series")
    if order != sorted(order, key=lambda key: key[0]):
        raise ValueError("Episodes must be ordered by frozen series rank")
    for s in series:
        eps = [e for e in episodes if e["series_id"] == s["series_id"]]
        numbers = [int(e["episode_no"]) for e in eps]
        if numbers != list(range(1, int(s["listed_episode_count"]) + 1)):
            raise ValueError(f"Non-contiguous frozen episode sequence: {s['series_title']}")
        if any(not e["source_episode_id"] for e in eps):
            raise ValueError(f"Empty frozen episode ID for {s['series_title']}")
    return series, episodes


def parse_ui(xml_text: str):
    try:
        return list(ET.fromstring(xml_text).iter("node"))
    except ET.ParseError:
        return []


def node_bounds(node):
    numbers = [int(n) for n in re.findall(r"\d+", node.get("bounds", ""))]
    if len(numbers) != 4 or numbers[2] <= numbers[0] or numbers[3] <= numbers[1]:
        return None  # Do not tap invisible zero-area native controls.
    return tuple(numbers)


def node_text(node):
    return (node.get("text") or node.get("content-desc") or "").strip()


def matched_node(nodes, label, *, exact=True):
    matches = [n for n in nodes if node_text(n) == label] if exact else [n for n in nodes if label in node_text(n)]
    return next((n for n in matches if node_bounds(n)), None)


def native_search_icon_bounds(xml_text: str):
    """Target only Hongguo's observed native magnifier control."""
    for node in parse_ui(xml_text):
        if node.get("resource-id", "").endswith(":id/search_image_icon_container"):
            bounds = node_bounds(node)
            if bounds is not None:
                return bounds
    return None


def chinese_number(raw):
    raw = raw.replace(",", "").strip()
    match = re.search(r"([\d.]+)\s*([万亿]?)", raw)
    if not match:
        return ""
    factor = {"": 1, "万": 10000, "亿": 100000000}[match.group(2)]
    return str(int(float(match.group(1)) * factor))


def search_result_ocr_candidates(image: Path, title: str, *, min_result_y=400):
    """Search cards are drawn visually and often omitted from UIAutomator XML.

    We explicitly exclude the search textbox (which echoes our own query),
    so a matched result must be independently seen below the search bar.
    """
    lines = group_tesseract_tsv(tesseract_tsv(image), confidence_floor=30)
    key = re.sub(r"[，。\s:：、·—]+", "", title)
    prefix = key[:max(4, min(len(key), 6))]
    result = []
    for row in lines:
        x0, y0, x1, y1 = row["bbox"]
        normalized = re.sub(r"[，。\s:：、·—]+", "", row["text"])
        if y0 >= min_result_y and prefix in normalized:
            result.append({**row, "center": ((x0+x1)//2, (y0+y1)//2),
                           "match_kind":"visible_result_title_prefix"})
    return result


def visible_navigation_ocr(image: Path):
    """Find only known app-navigation labels, never print viewer comments."""
    labels = ("找剧", "搜剧", "剧场", "搜索", "首页", "同意并继续", "Got it")
    result = []
    # Running Tesseract on a 1080x2400 dynamic video often times out. Search
    # only the top entry bar and bottom tab strip, preserving original pixels.
    from PIL import Image
    from tempfile import TemporaryDirectory
    with Image.open(image) as full:
        width, height = full.size
        zones = [(0, min(height, 850)), (max(0, height-500), height)]
        with TemporaryDirectory() as tmp:
            for zone_index, (top, bottom) in enumerate(zones):
                crop = Path(tmp) / f"nav{zone_index}.png"
                full.crop((0, top, width, bottom)).save(crop)
                try:
                    rows = group_tesseract_tsv(tesseract_tsv(crop, timeout=12),
                                               confidence_floor=34, allow_short=True)
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    continue
                for row in rows:
                    normalized = re.sub(r"[，。\s:：、·—]+", "", row["text"])
                    for label in labels:
                        # Whole-row boxes covering multiple tabs are unsafe.
                        if normalized == label:
                            x0, y0, x1, y1 = row["bbox"]
                            result.append({"label":label,
                                           "bbox":[x0,y0+top,x1,y1+top],
                                           "center":[(x0+x1)//2,(y0+y1)//2+top]})
                if any(item["label"] in ("找剧", "搜剧", "搜索") for item in result):
                    break
    return result



def native_navigation_context(xml_text: str, label: str):
    """Return a safe tap target plus non-sensitive UI control metadata."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None, [], []
    parent_of = {id(child): parent for parent in root.iter() for child in parent}
    target = next((n for n in root.iter("node")
                   if node_text(n) == label and node_bounds(n) is not None), None)
    chain = []
    candidate = target
    selected_bounds = None
    while candidate is not None and len(chain) < 8:
        bounds = node_bounds(candidate)
        chain.append({"bounds":candidate.get("bounds", ""),
                      "clickable":candidate.get("clickable", ""),
                      "class":candidate.get("class", ""),
                      "resource_id":candidate.get("resource-id", "")})
        if candidate is not target and candidate.get("clickable") == "true" and bounds:
            x0, y0, x1, y1 = bounds
            if x1-x0 <= 980 and y1-y0 <= 550:
                selected_bounds = bounds
                break
        candidate = parent_of.get(id(candidate))
    top_clickables = []
    for node in root.iter("node"):
        bounds = node_bounds(node)
        if not bounds or bounds[1] > 480 or node.get("clickable") != "true":
            continue
        top_clickables.append({"bounds":node.get("bounds", ""),
                               "class":node.get("class", ""),
                               "resource_id":node.get("resource-id", "")})
    return (selected_bounds or (node_bounds(target) if target is not None else None)), chain, top_clickables[:28]


class Android:
    def __init__(self, *, adb="adb", ime=True):
        self.adb = adb
        self.ime = ime
        self.danmaku_enabled = False

    def run(self, *args, timeout=35, binary=False, check=True):
        cmd = [self.adb, *args]
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
        if check and proc.returncode != 0:
            raise RuntimeError(f"adb failed ({' '.join(cmd)}): {proc.stderr[-400:]!r}")
        return proc.stdout if binary else proc.stdout.decode("utf-8", errors="replace")

    def tap(self, x, y):
        self.run("shell", "input", "tap", str(x), str(y))

    def back(self):
        self.run("shell", "input", "keyevent", "KEYCODE_BACK")

    def swipe(self, x0=540, y0=1890, x1=540, y1=800, ms=400):
        self.run("shell", "input", "swipe", str(x0), str(y0), str(x1), str(y1), str(ms))

    def xml(self):
        path = "/sdcard/window-v1.xml"
        try:
            self.run("shell", "uiautomator", "dump", path, timeout=18, check=False)
            return self.run("shell", "cat", path, timeout=10, check=False)
        except (subprocess.TimeoutExpired, RuntimeError):
            # Native video/consent overlays can block accessibility dumps.
            # Return no nodes and let screenshot OCR navigate the current UI;
            # never reuse stale XML from an earlier screen.
            return ""

    def screenshot(self, path: Path):
        blob = self.run("exec-out", "screencap", "-p", timeout=20, binary=True)
        if blob[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("adb screenshot missing PNG header")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)

    def click_label(self, label, *, exact=True):
        node = matched_node(parse_ui(self.xml()), label, exact=exact)
        if node is None:
            return False
        x0, y0, x1, y1 = node_bounds(node)
        self.tap((x0 + x1) // 2, (y0 + y1) // 2)
        return True

    def foreground(self):
        text = self.run("shell", "dumpsys", "activity", "activities", check=False)
        return bool(re.search(r"topResumedActivity=[^\n]*com\.phoenix\.read/", text))

    def enter_title(self, title):
        if not self.ime:
            raise RuntimeError("Chinese input requires ADBKeyBoard Unicode IME")
        import base64
        b64 = base64.b64encode(title.encode("utf-8")).decode("ascii")
        self.run("shell", "am", "broadcast", "-a", "ADB_CLEAR_TEXT")
        self.run("shell", "am", "broadcast", "-a", "ADB_INPUT_B64", "--es", "msg", b64)


def exact_search(app: Android, title: str, evidence: Path, *, wait=20):
    """Search by exact Chinese title, avoiding dynamic hot list entirely."""
    app.run("shell", "monkey", "-p", "com.phoenix.read", "-c", "android.intent.category.LAUNCHER", "1", check=False)
    time.sleep(5)
    if not app.foreground():
        raise RuntimeError("Hongguo is not the active Android app")
    evidence.mkdir(parents=True, exist_ok=True)
    # In the observed app, first launch may be an immersive *player*, not the
    # searchable theater tab. Dismiss Android's verified full-screen tutorial.
    intro_xml = app.xml()
    if "Viewing full screen" in intro_xml and "Got it" in intro_xml:
        app.click_label("Got it")
        time.sleep(2)
    # Navigate by currently observed controls, since the freshly installed app
    # may launch on different tabs or an immersive video between CI runs.
    custom_search = False
    for attempt in range(12):
        if not app.foreground():
            app.run("shell", "monkey", "-p", "com.phoenix.read", "-c",
                    "android.intent.category.LAUNCHER", "1", check=False)
            time.sleep(8)
        xml_text = app.xml()
        nodes = parse_ui(xml_text)
        screenshot = evidence / f"search_nav_{attempt:02d}.png"
        try:
            app.screenshot(screenshot)
            xml_has_actionable_nav = any(
                node_text(n) in ("找剧", "搜剧", "剧场", "搜索") and node_bounds(n) is not None
                for n in nodes)
            # Native UI navigation is authoritative and much faster; use OCR
            # only when the UI hierarchy has no independently tappable control.
            visual_navigation = [] if xml_has_actionable_nav else visible_navigation_ocr(screenshot)
        except Exception:
            visual_navigation = []
        if "Viewing full screen" in xml_text and "Got it" in xml_text:
            app.click_label("Got it")
            time.sleep(2)
            continue
        edit = next((n for n in nodes if n.get("class", "").endswith("EditText") and node_bounds(n)), None)
        if edit is not None:
            break
        submit = matched_node(nodes, "搜索")
        if submit is not None:
            sx0, sy0, sx1, sy1 = node_bounds(submit)
            if sx0 > 700 and sy1 < 450:
                # Actual observed search screen: the right-side TextView
                # "搜索" at [954,171][1038,233] is SUBMIT, not text entry.
                # Focus the left search bar *before* pressing this button.
                custom_search = True
                break
        # Verified in live Android UI: this toolbar child is the actual
        # search magnifier. "找剧" below it is only a theater category tab.
        search_icon_bounds = native_search_icon_bounds(xml_text)
        if search_icon_bounds is not None:
            x0, y0, x1, y1 = search_icon_bounds
            print(json.dumps({"v1_native_search_icon":"search_image_icon_container",
                              "bounds":list(search_icon_bounds)}, ensure_ascii=False), flush=True)
            app.tap((x0+x1)//2, (y0+y1)//2)
            time.sleep(3)
            # The resulting search screen is often canvas-rendered and has
            # no EditText nodes; its top-left query bar is handled below.
            custom_search = True
            break
        # UIAutomator sometimes yields zero nodes in Hongguo's immersive UI;
        # only known navigation labels seen on the screen are actionable.
        visual_submit = next((v for v in visual_navigation if v["label"] == "搜索"
                              and v["center"][0] > 750 and v["center"][1] < 450), None)
        if visual_submit:
            custom_search = True
            break
        # Publish only navigation labels, not any onscreen audience messages.
        safe_labels = {"搜索", "剧场", "排行榜", "首页", "短剧", "找剧", "搜剧", "同意并继续", "Got it"}
        observed = sorted(set(node_text(n) for n in nodes if node_text(n) in safe_labels))
        search_controls = [{"class":n.get("class", ""), "bounds":n.get("bounds", ""),
                            "resource_id":n.get("resource-id", ""), "clickable":n.get("clickable", "")}
                           for n in nodes if node_text(n) == "搜索"][:3]
        find_drama = matched_node(nodes, "找剧")
        if find_drama is None:
            find_drama = matched_node(nodes, "搜剧")
        theater = matched_node(nodes, "剧场")
        visual_find = next((v for v in visual_navigation if v["label"] in ("找剧", "搜剧")
                            and v["center"][1] < 950), None)
        visual_theater = next((v for v in visual_navigation if v["label"] == "剧场"
                               and v["center"][1] > 1600), None)
        action = ("find_drama" if find_drama is not None else "theater_tab" if theater is not None else
                  "ocr_find_drama" if visual_find else "ocr_theater_tab" if visual_theater else
                  "wait_for_native_ui" if attempt < 2 else "back_to_home" if attempt % 3 == 2 else
                  "theater_coordinate_fallback")
        native_nav_controls = [
            {"label":node_text(n), "bounds":n.get("bounds", ""),
             "enabled":n.get("enabled", ""), "clickable":n.get("clickable", ""),
             "resource_id":n.get("resource-id", "")}
            for n in nodes if node_text(n) in ("找剧", "搜剧", "剧场", "搜索")
        ][:10]
        print(json.dumps({"v1_search_navigation_attempt":attempt, "action":action,
                          "visible_navigation_labels":observed,
                          "visual_navigation":visual_navigation[:8],
                          "native_navigation_controls":native_nav_controls,
                          "search_controls":search_controls, "ui_nodes":len(nodes),
                          "app_foreground":app.foreground()}, ensure_ascii=False), flush=True)
        if find_drama is not None or theater is not None:
            target = find_drama if find_drama is not None else theater
            label = node_text(target)
            target_bounds, native_chain, top_clickables = native_navigation_context(xml_text, label)
            print(json.dumps({"v1_native_navigation_target":label,
                              "safe_control_ancestors":native_chain[:7],
                              "top_clickable_controls":top_clickables[:28]},
                             ensure_ascii=False), flush=True)
            x0, y0, x1, y1 = target_bounds if target_bounds else node_bounds(target)
            app.tap((x0+x1)//2, (y0+y1)//2)
        elif visual_find or visual_theater:
            target = visual_find or visual_theater
            app.tap(*target["center"])
        elif action == "back_to_home":
            app.back()
        elif action == "theater_coordinate_fallback":
            app.tap(410, 2270)
        time.sleep(5)
    else:
        # Keep private evidence for precise offline debugging; no screenshot
        # or raw UI text is exported to public repository or Actions artifacts.
        (evidence / "search_navigation_failure.xml").write_text(app.xml(), encoding="utf-8")
        app.screenshot(evidence / "search_navigation_failure.png")
        try:
            from PIL import Image
            with Image.open(evidence / "search_navigation_failure.png") as screenshot:
                screenshot.thumbnail((540, 1200))
                screenshot.convert("RGB").save(evidence / "search_navigation_failure_preview.jpg",
                                               "JPEG", quality=55, optimize=True)
        except Exception:
            pass
        raise RuntimeError("Native Find Drama/search field unavailable after 12 verified navigation checks")
    nodes = parse_ui(app.xml())
    edit = next((n for n in nodes if n.get("class", "").endswith("EditText") and node_bounds(n)), None)
    if edit is None and custom_search:
        # Search submit label is normally at right; the left half of its top
        # bar hosts the custom text entry. Verify the echoed query below.
        app.tap(350, 185)
    elif edit is not None:
        x0, y0, x1, y1 = node_bounds(edit)
        app.tap((x0+x1)//2, (y0+y1)//2)
    else:
        raise RuntimeError("Search input disappeared before typing")
    app.enter_title(title)
    time.sleep(2)
    if edit is None:
        input_xml = app.xml()
        app.screenshot(evidence / "search_input.png")
        visible_rows = group_tesseract_tsv(tesseract_tsv(evidence / "search_input.png"), confidence_floor=30)
        title_prefix = re.sub(r"[，。\s:：、·—]+", "", title)[:6]
        echo_visible = title in input_xml or any(
            title_prefix in re.sub(r"[，。\s:：、·—]+", "", row["text"]) and row["bbox"][1] < 450
            for row in visible_rows)
        print(json.dumps({"v1_custom_search_input":"focused_top_bar", "query_echo_verified":echo_visible},
                         ensure_ascii=False), flush=True)
        if not echo_visible:
            raise RuntimeError("Custom search field did not visibly echo exact frozen title")
    app.click_label("搜索", exact=True) or app.run("shell", "input", "keyevent", "KEYCODE_ENTER")
    time.sleep(wait)
    result_xml = app.xml()
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "search_results.xml").write_text(result_xml, encoding="utf-8")
    app.screenshot(evidence / "search_results.png")
    if title in result_xml and app.click_label(title):
        candidate_source = "uiautomator_xml_exact_title"
    else:
        # In the observed Hongguo search page, posters/titles are canvas-drawn;
        # UIAutomator exposes only the search EditText and search toolbar.
        candidates = search_result_ocr_candidates(evidence / "search_results.png", title)
        (evidence / "search_candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
        if not candidates:
            raise RuntimeError("No independent matching search-result card in XML/OCR")
        x, y = candidates[0]["center"]
        app.tap(x, y)
        candidate_source = "onscreen_result_ocr_prefix"
    time.sleep(12)
    opened = app.xml()
    (evidence / "search_opened.xml").write_text(opened, encoding="utf-8")
    app.screenshot(evidence / "search_opened.png")
    verified = title in opened
    if not verified:
        # A player may hide title text behind controls; screenshot OCR is an
        # independent second signal, but a prefix alone is not full verification.
        visible = group_tesseract_tsv(tesseract_tsv(evidence / "search_opened.png"), confidence_floor=30)
        verified = any(title in line["text"] for line in visible)
    (evidence / "search_verification.json").write_text(json.dumps({"series_title":title,
        "candidate_source":candidate_source, "full_title_independently_verified":verified},ensure_ascii=False,indent=2),encoding="utf-8")
    return verified


def enable_danmaku(app: Android, evidence: Path):
    """Enable the native overlay *only* when its real UI control is seen."""
    if app.danmaku_enabled:
        return True
    app.tap(540, 1100)  # reveal native playback toolbar
    time.sleep(1)
    app.tap(1000, 192)  # native options entry (on 1080x2400 reference device)
    time.sleep(2)
    xml_text = app.xml()
    (evidence / "danmaku_settings.xml").write_text(xml_text, encoding="utf-8")
    nodes = parse_ui(xml_text)
    label = matched_node(nodes, "弹幕")
    if label is None:
        app.back()
        raise RuntimeError("Danmaku setting missing; cannot attribute on-screen text to real danmaku")
    bounds = node_bounds(label)
    if not bounds:
        app.back()
        raise RuntimeError("Danmaku setting has no reliable location")
    if any(node_text(node) == "弹幕设置" for node in nodes):
        # Verified in the 2026-11-21 player UI: this additional options row
        # appears only after the danmaku switch has been enabled.
        app.danmaku_enabled = True
        app.back()
        app.tap(540, 1100)
        return True
    # Native switch is immediately right of the 2026-11-21 observed label.
    x = min(bounds[2] + 50, 1000)
    y = (bounds[1] + bounds[3]) // 2
    app.tap(x, y)
    time.sleep(1)
    app.screenshot(evidence / "danmaku_on.png")
    app.danmaku_enabled = True
    app.back()
    time.sleep(1)
    app.tap(540, 1100)  # resume if options pause playback
    return True


def select_episode(app: Android, number: int, evidence: Path):
    """Require a visibly matching episode label, never assume an unverified swipe."""
    if not (app.click_label("选集", exact=False) or app.click_label("剧集", exact=False)):
        nodes = parse_ui(app.xml())
        all_episodes = next((node for node in nodes if re.search(r"(?:全|共)\s*\d+\s*集", node_text(node)) and node_bounds(node)), None)
        if all_episodes is None:
            raise RuntimeError("Episode selector absent in UI hierarchy")
        x0, y0, x1, y1 = node_bounds(all_episodes)
        app.tap((x0+x1)//2, (y0+y1)//2)
    time.sleep(2)
    target = f"第{number}集"
    for attempt in range(60):
        xml_text = app.xml()
        nodes = parse_ui(xml_text)
        node = matched_node(nodes, target)
        if node is None:
            node = matched_node(nodes, str(number))
        if node is not None:
            x0, y0, x1, y1 = node_bounds(node)
            app.tap((x0+x1)//2, (y0+y1)//2)
            time.sleep(3)
            actual = app.xml()
            (evidence / f"episode_{number}_opened.xml").write_text(actual, encoding="utf-8")
            if target not in actual:
                screenshot = evidence / f"episode_{number}_opened.png"
                app.screenshot(screenshot)
                text = "".join(item["text"] for item in group_tesseract_tsv(tesseract_tsv(screenshot), confidence_floor=30))
                if target not in text:
                    raise RuntimeError(f"Tapped episode {number}, but player did not display its episode label")
            return target
        if attempt == 59:
            break
        app.swipe()
        time.sleep(.3)
    raise RuntimeError(f"Episode {number} not independently visible in episode selector")


def capture_visible_metadata(xml_text: str, episode: dict, captured_at: str, path: str):
    nodes = parse_ui(xml_text)
    labels = [node_text(node) for node in nodes if node_text(node)]
    base = {"snapshot": "V1_initial", "series_id": episode["series_id"], "episode_no": episode["episode_no"]}
    metrics = []
    patterns = {"点赞": "likes", "收藏": "favorites", "评论": "comments", "评分": "rating", "热度": "heat", "播放": "views", "分享": "shares"}
    for label in labels:
        for key, name in patterns.items():
            if key not in label:
                continue
            # UI only: scope is unknown unless a verified per-episode panel is open.
            metrics.append({**base, "metric_scope":"unknown", "metric_name":name,
                            "raw_display":label, "numeric_value":chinese_number(label),
                            "captured_at_utc":captured_at, "source":"uiautomator_xml",
                            "ui_xml_file":path, "status":"observed_raw_unverified_scope"})
    return metrics


def capture_comments_panel(app: Android, episode: dict, evidence: Path):
    """Preserve native comment hierarchy; only emit corroborated text children."""
    # Comment button is a visible UI label/control, not a global guessed tap.
    if not app.click_label("评论", exact=False):
        return []
    time.sleep(2)
    panel = app.xml()
    panel_file = evidence / "comments_preview.xml"
    panel_file.write_text(panel, encoding="utf-8")
    app.screenshot(evidence / "comments_preview.png")
    app.back()
    nodes = parse_ui(panel)
    if not any("评论" in node_text(node) for node in nodes):
        return []
    # UI XML often lacks stable IDs or semantically separated comment bodies.
    # Do not invent comment content or reply relationships from generic labels.
    return []


def append_rows(path: Path, kind: str, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = CSV_HEADERS[kind]
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def inspect_video(path: Path):
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                           "-of", "default=nokey=1:noprint_wrappers=1", str(path)], capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def capture_episode(app: Android, episode: dict, output: Path, capture_seconds: float, interval: float):
    sid, num = episode["series_id"], int(episode["episode_no"])
    evidence = output / "evidence" / sid / f"{num:03d}"
    evidence.mkdir(parents=True, exist_ok=True)
    snapshot_at = utcnow()
    xml_text = app.xml()
    xml_file = evidence / "player.xml"
    xml_file.write_text(xml_text, encoding="utf-8")
    metrics = capture_visible_metadata(xml_text, episode, snapshot_at, str(xml_file.relative_to(ROOT)) if xml_file.is_relative_to(ROOT) else str(xml_file))
    # Exact title is visible on some player views only after tapping the screen.
    # Never convert title uncertainty into a verified episode.
    if not app.foreground():
        raise RuntimeError("App lost foreground while entering episode")
    enable_danmaku(app, evidence)
    duration = min(max(capture_seconds, 1.0), 179.0)
    raw_video = evidence / "recording.mp4"
    adb_proc = subprocess.Popen([app.adb, "shell", "screenrecord", "--bit-rate", "1200000",
                                 "--time-limit", str(int(duration + 1)), "/sdcard/v1_capture.mp4"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    tracker = EpisodeOCRTracker()
    screenshots = []
    capture_start = time.monotonic()
    frames = 0
    while time.monotonic() - capture_start < duration:
        current = time.monotonic()
        frame_file = evidence / f"frame_{frames:05d}.png"
        elapsed_ms = int((current - capture_start) * 1000)
        try:
            app.screenshot(frame_file)
            screenshots.append((frame_file, elapsed_ms, utcnow()))
        except Exception:
            pass
        frames += 1
        remaining = interval - (time.monotonic() - current)
        if remaining > 0:
            time.sleep(remaining)
    adb_proc.wait(timeout=duration + 60)
    app.run("pull", "/sdcard/v1_capture.mp4", str(raw_video), timeout=70, check=False)
    app.run("shell", "rm", "-f", "/sdcard/v1_capture.mp4", check=False)
    actual = inspect_video(raw_video) if raw_video.exists() else None
    expected = float(episode["expected_duration_seconds"]) if episode.get("expected_duration_seconds") else None
    video_ok = bool(actual and expected and abs(actual - expected) <= 3 and duration >= expected - 2)
    danmaku = []
    frame_times = {}
    for frame_file, elapsed_ms, observed_at in screenshots:
        cropped = frame_file.with_name(frame_file.stem + "_roi.png")
        try:
            parsed = ocr_frame(frame_file, cropped, elapsed_ms=elapsed_ms)
            tracker.ingest(parsed["observed_ms"], parsed["rows"], str(frame_file))
            frame_times[str(frame_file)] = observed_at
        except Exception as err:
            (evidence / "ocr_errors.log").open("a", encoding="utf-8").write(f"{frame_file.name}: {err}\n")
        cropped.unlink(missing_ok=True)
    # Save only the most legible frame for each candidate. CSV evidence paths
    # MUST point to files that actually exist, including after de-dup upgrades.
    keep_frames = {item.screenshot for item in tracker.items}
    for frame_file, _, _ in screenshots:
        if str(frame_file) not in keep_frames:
            frame_file.unlink(missing_ok=True)
    for found in tracker.items:
        if not Path(found.screenshot).exists():
            continue
        danmaku.append({"snapshot":"V1_initial", "series_id":sid, "episode_no":num,
                        "source_episode_id":episode["source_episode_id"], "text":found.text,
                        "video_offset_ms_estimated":found.first_seen_ms,
                        "timestamp_source":"ocr_estimated", "timestamp_uncertainty_ms":int(max(1000, interval * 1000)),
                        "message_id":"", "posted_at_utc":"", "captured_at_utc":frame_times.get(found.screenshot, utcnow()),
                        "ocr_confidence":found.confidence, "screenshot_file":found.screenshot,
                        "bbox":json.dumps(found.bbox), "evidence_type":"on_screen_ocr_candidate"})
    sha = hashlib.sha256(raw_video.read_bytes()).hexdigest() if raw_video.exists() else ""
    capture_comments_panel(app, episode, evidence)
    return {"status":"sampled_unverified" if not video_ok else "full_screen_recording_verified",
            "verified_title":"", "verified_episode":str(num), "ui_episode_label":f"第{num}集",
            "full_video_file":str(raw_video), "actual_media_duration_seconds":actual or "",
            "expected_duration_seconds":expected or "", "full_video_verified":video_ok,
            "video_sha256":sha, "ui_xml_file":str(xml_file), "raw_ui_text_file":str(xml_file)}, danmaku, metrics


def save_atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def audit(output: Path, checkpoint: dict):
    counts = {}
    for kind in CSV_HEADERS:
        path = output / f"{kind}.csv"
        with path.open(encoding="utf-8") as f:
            counts[kind] = sum(1 for _ in csv.DictReader(f))
    with (output / "episodes.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    report = {"snapshot":"V1_initial", "generated_at_utc":utcnow(), "frozen_series":10,
              "frozen_episodes":999, "attempted_episodes":len(rows),
              "recorded_full_episodes":sum(e["full_video_verified"].lower() == "true" for e in rows),
              "ocr_danmaku_candidates":counts["danmaku"], "comments":counts["comments"],
              "metrics_observed":counts["metrics"], "row_counts":counts,
              "all_attempted":len(rows) == 999, "all_successfully_collected":len(rows) == 999 and all(row["status"] != "failed" for row in rows),
              "note":"OCR offset is sampled time, not official platform timestamp; OCR may include false positives and misses. Empty fields are deliberately not fabricated.",
              "videos_in_repository":False, "checkpoint_next_index":checkpoint.get("next_index")}
    save_atomic_json(output / "V1_audit.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Frozen Hongguo V1 initial single-pass UI acquisition")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "v1_initial")
    parser.add_argument("--max-episodes", type=int, default=20)
    parser.add_argument("--capture-seconds", type=float, default=115.0)
    parser.add_argument("--interval-seconds", type=float, default=.75)
    parser.add_argument("--verify-inventory-only", action="store_true")
    parser.add_argument("--no-ime", action="store_true")
    args = parser.parse_args(argv)
    series, episodes = load_frozen()
    if args.verify_inventory_only:
        print(json.dumps({"series":len(series), "episodes":len(episodes), "status":"valid"}))
        return 0
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {"snapshot":"V1_initial", "next_index":0, "attempts":0}
    if checkpoint.get("snapshot") != "V1_initial":
        raise ValueError("Unexpected checkpoint schema/snapshot")
    for kind in CSV_HEADERS:
        append_rows(output / f"{kind}.csv", kind, [])
    app = Android(ime=not args.no_ime)
    current_series = None
    count = 0
    while checkpoint["next_index"] < len(episodes) and count < args.max_episodes:
        index = checkpoint["next_index"]
        ep = episodes[index]
        num = int(ep["episode_no"])
        started = utcnow()
        row = {"snapshot":"V1_initial", "series_id":ep["series_id"], "series_title":ep["series_title"],
               "episode_no":num, "source_episode_id":ep["source_episode_id"], "captured_at_utc":started}
        danmaku, metrics = [], []
        try:
            evidence = output / "evidence" / ep["series_id"] / f"{num:03d}"
            evidence.mkdir(parents=True, exist_ok=True)
            if current_series != ep["series_id"]:
                visible_title = exact_search(app, ep["series_title"], evidence)
                if not visible_title:
                    raise RuntimeError("Player opened but exact title not independently verified in XML")
                current_series = ep["series_id"]
            ui_episode_label = select_episode(app, num, evidence)
            row["verified_title"] = ep["series_title"]
            row["ui_episode_label"] = ui_episode_label
            expected = float(ep["expected_duration_seconds"]) if ep["expected_duration_seconds"] else args.capture_seconds
            data, danmaku, metrics = capture_episode(app, ep, output, min(args.capture_seconds, max(1, expected)), args.interval_seconds)
            row.update(data)
            row["verified_title"] = ep["series_title"]
        except Exception as err:
            row.update(status="failed", failure_reason=f"{type(err).__name__}: {err}", full_video_verified=False)
            current_series = None
        append_rows(output / "episodes.csv", "episodes", [row])
        append_rows(output / "danmaku.csv", "danmaku", danmaku)
        append_rows(output / "metrics.csv", "metrics", metrics)
        checkpoint["next_index"] += 1
        checkpoint["attempts"] += 1
        checkpoint["last_episode_status"] = row["status"]
        checkpoint["updated_at_utc"] = utcnow()
        save_atomic_json(checkpoint_path, checkpoint)
        count += 1
        print(json.dumps({"progress":f"{checkpoint['next_index']}/999", "status":row["status"], "danmaku":len(danmaku), "error":row.get("failure_reason","")}, ensure_ascii=False), flush=True)
    report = audit(output, checkpoint)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
