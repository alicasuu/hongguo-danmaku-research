"""Public SSR parsing; intentionally never calls signed App endpoints."""
from __future__ import annotations
import json
import re
from html import unescape
from urllib.parse import quote, parse_qs, urlparse
from bs4 import BeautifulSoup
from .util import clean_text

BASE = "https://hongguoduanju.com"
RANKS = {"hot-drama", "hot-real-drama", "hot-ai-drama", "hot-comic-drama"}


def parse_embedded_objects(html: str) -> list:
    objects = []
    # SSR may appear as an assignment inside ordinary JS or script strings.
    decoder = json.JSONDecoder()
    for m in re.finditer(r"_ROUTER_DATA\s*(?:=|:)", html):
        start = html.find("{", m.end())
        if start < 0 or start - m.end() > 300:
            continue
        try:
            val, _ = decoder.raw_decode(html[start:])
            if isinstance(val, dict):
                objects.append(val)
        except json.JSONDecodeError:
            pass
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", attrs={"data-fn-args": True}):
        try:
            obj = json.loads(unescape(script.get("data-fn-args", "")))
            objects.append(_decode_nested(obj))
        except json.JSONDecodeError:
            pass
    for script in soup.find_all("script", attrs={"type": "application/json"}):
        try:
            objects.append(_decode_nested(json.loads(script.get_text())))
        except json.JSONDecodeError:
            pass
    return objects


def _decode_nested(x, depth=0):
    if depth >= 7:
        return x
    if isinstance(x, str) and x.lstrip().startswith(("{", "[")):
        try:
            return _decode_nested(json.loads(x), depth + 1)
        except json.JSONDecodeError:
            return x
    if isinstance(x, list):
        return [_decode_nested(y, depth + 1) for y in x]
    if isinstance(x, dict):
        return {k: _decode_nested(v, depth + 1) for k, v in x.items()}
    return x


def recursive_find(x, key):
    if isinstance(x, dict):
        if key in x:
            return x[key]
        for value in x.values():
            y = recursive_find(value, key)
            if y is not None:
                return y
    if isinstance(x, list):
        for value in x:
            y = recursive_find(value, key)
            if y is not None:
                return y
    return None


def _first(raw: dict, *keys):
    for key in keys:
        val = raw.get(key)
        if val is not None and val != "":
            return val
    return None


def _sid_from_url(url):
    if not url:
        return None
    return parse_qs(urlparse(url).query).get("series_id", [None])[0]


def normalize_drama(raw: dict, rank: int | None = None):
    raw = raw.get("seriesInfo") or raw.get("series_info") or raw.get("series") or raw
    sid = _first(raw, "seriesId", "series_id", "seriesID", "book_id", "id") or _sid_from_url(raw.get("url"))
    title = _first(raw, "title", "series_name", "name", "book_name")
    if not sid or not title:
        return None
    tags = _first(raw, "tags", "categories", "genre", "genres") or []
    if isinstance(tags, list):
        tags = [x.get("name") or x.get("tag_name") if isinstance(x, dict) else x for x in tags]
        tags = ", ".join(clean_text(v) for v in tags if v)
    return {
        "drama_id": str(sid), "title": clean_text(title),
        "rank": _first(raw, "rank", "position", "rankNo") or rank,
        "heat_label": _first(raw, "heatText", "hotScoreText", "heat", "hot_score") or "",
        "likes_label": _first(raw, "likeText", "like_count_text", "like") or "",
        "favorites_label": _first(raw, "favoriteText", "favorite_count_text", "favorite") or "",
        "rating_label": _first(raw, "scoreText", "rating", "score") or "",
        "views_label": "",  # Rank heat MUST NOT be relabelled as plays.
        "comments_label": _first(raw, "commentText", "comment_count_text") or "",
        "shares_label": _first(raw, "shareText", "share_count_text") or "",
        "genre": str(tags or ""), "description": str(_first(raw, "description", "intro", "series_intro") or ""),
        "episode_count": _first(raw, "episodeCount", "episode_cnt", "total_episodes"),
        "status": str(_first(raw, "status", "completion_status", "finish_status") or "unknown"),
        "creator": str(_first(raw, "creator", "author") or ""),
        "ai_classification": "ai_category" if "ai" in str(_first(raw, "rank_section", "type") or "").lower() else "unknown",
        "url": BASE + "/detail?series_id=" + quote(str(sid)),
    }


def parse_rank(html: str, limit: int = 10):
    for obj in parse_embedded_objects(html):
        # Often content.rankList; verify each item before accepting.
        for key in ("rankList", "rank_list", "rankData"):
            data = recursive_find(obj, key)
            if isinstance(data, dict):
                data = data.get("list") or data.get("items") or data.get("rankList")
            if isinstance(data, list):
                results = [normalize_drama(x, i) for i, x in enumerate(data, 1) if isinstance(x, dict)]
                results = [x for x in results if x]
                if results:
                    results.sort(key=lambda x: int(x["rank"]) if str(x["rank"]).isdigit() else 10**9)
                    return _dedup(results)[:limit]
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for article in soup.select('article[aria-labelledby^="rank-title-"]'):
        title_id = article.get("aria-labelledby", "")
        title = article.find(id=title_id)
        if title is None:
            continue
        sid = title_id.removeprefix("rank-title-")
        rank = article.select_one('[class*="badge-number-"]')
        heat = article.select_one('[class*="metrics-"]')
        normalized = normalize_drama({"seriesId": sid, "title": title.get_text(" ", strip=True), "heatText": heat.get_text(" ", strip=True) if heat else ""},
                                      rank=int(rank.get_text(strip=True)) if rank and rank.get_text(strip=True).isdigit() else len(out) + 1)
        if normalized:
            out.append(normalized)
    # Conservative fallback on public links that expose series ID; order is DOM order.
    if not out:
        for a in soup.select('a[href*="series_id="]'):
            title = clean_text(a.get_text(" ", strip=True))
            sid = _sid_from_url(a.get("href"))
            if sid and title and len(title) < 120:
                obj = normalize_drama({"seriesId": sid, "title": title}, len(out) + 1)
                if obj:
                    out.append(obj)
    return _dedup(out)[:limit]


def _dedup(items):
    unique = {}
    for item in items:
        unique.setdefault(item["drama_id"], item)
    return list(unique.values())


def parse_detail(html: str):
    """Return metadata plus episode IDs only when explicitly present in SSR.

    If IDs are not exposed, no episode rows are fabricated.
    """
    info = None
    for obj in parse_embedded_objects(html):
        for k in ("seriesDetail", "series_detail", "bookDetail"):
            val = recursive_find(obj, k)
            if isinstance(val, dict):
                info = val
                break
        if info:
            break
    if not info:
        return None
    d = normalize_drama(info)
    if not d:
        return None
    vids = _first(info, "vid_list", "episodeVideoIds", "video_ids", "episode_ids") or []
    episodes = []
    if isinstance(vids, list):
        for i, v in enumerate(vids, 1):
            if isinstance(v, dict):
                eid = _first(v, "video_id", "vid", "episodeId", "id")
                n = _first(v, "episode_number", "index", "episodeNo") or i
            else:
                eid, n = v, i
            if eid:
                episodes.append({"episode_id": str(eid), "episode_number": int(n), "duration_seconds": None})
    d["episodes"] = episodes
    return d
