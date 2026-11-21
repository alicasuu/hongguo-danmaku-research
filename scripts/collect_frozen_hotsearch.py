#!/usr/bin/env python3
"""Polite, repeatable snapshot of a frozen Hongguo hot-search cohort.

Only public detail and one-segment /player/<series_id> pages are requested.
Never request disallowed /player/<series_id>/<episode_id> paths, login endpoints,
signed media, or protected data. No user credentials are needed or stored.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hongguo.network import PublicClient  # noqa: E402
from hongguo.public_research import extract_page  # noqa: E402


BASE = "https://hongguoduanju.com"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def as_utc(value: object) -> str:
    if value is None or value == "":
        return ""
    raw = str(value)
    if not raw.isdigit():
        raise ValueError("Source create_time was not a numeric Unix timestamp")
    return datetime.fromtimestamp(int(raw), timezone.utc).isoformat(timespec="seconds")


def collect(cohort: list[dict], out: Path, delay: float) -> dict:
    if len(cohort) != 10 or len({x["series_id"] for x in cohort}) != 10:
        raise ValueError("Frozen cohort must contain precisely ten distinct series")
    out.mkdir(parents=True, exist_ok=True)
    client = PublicClient({"hongguoduanju.com"}, delay=delay)
    catalog: list[dict] = []
    episodes: list[dict] = []
    metrics: list[dict] = []
    reviews: list[dict] = []
    media: list[dict] = []
    receipts: list[dict] = []
    failures: list[dict] = []

    for row in sorted(cohort, key=lambda r: int(r["rank"])):
        sid = row["series_id"]
        source = row["detail_url"]
        for kind, url in (("detail", source), ("player", f"{BASE}/player/{sid}")):
            try:
                html = client.get_html(url)
                collected_at = utcnow()
                payload = extract_page(html, url, kind, sid)
                catalog_value = payload["catalog"]
                if catalog_value["drama_id"] != sid:
                    raise ValueError("Server series ID did not match frozen cohort")
                if catalog_value["title"] != row["series_title"]:
                    raise ValueError("Server title did not match frozen cohort")

                receipts.append({
                    "series_id": sid,
                    "page_kind": kind,
                    "source_url": url,
                    "collected_at_utc": collected_at,
                    "response_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
                    "response_bytes": len(html.encode("utf-8")),
                    "reported_review_total": payload["reported_review_total"],
                    "embedded_review_preview_count": len(payload["reviews"]),
                    "review_coverage": "preview_only",
                })
                if kind == "detail":
                    episode_list = catalog_value["episodes"]
                    expected = int(catalog_value["episode_count"])
                    ids = [x["episode_id"] for x in episode_list]
                    ordinals = [x["episode_number"] for x in episode_list]
                    if len(episode_list) != expected:
                        raise ValueError(f"Episode ID coverage incomplete: {len(episode_list)}/{expected}")
                    if ordinals != list(range(1, expected + 1)):
                        raise ValueError("Episode ordinals are not consecutive")
                    if len(set(ids)) != expected:
                        raise ValueError("Duplicate episode IDs in public SSR")
                    catalog.append({
                        "rank": row["rank"],
                        "series_id": sid,
                        "series_title": catalog_value["title"],
                        "official_detail_url": source,
                        "synopsis": catalog_value["description"],
                        "genre": catalog_value["genre"],
                        "web_rank_category": row["category"],
                        "platform_classification": catalog_value["platform_classification"],
                        "completion_status": catalog_value.get("completion_status", "unverified"),
                        "listed_episode_count": expected,
                        "confirmed_source_episode_ids": len(episode_list),
                        "accessible_episode_count_reported": catalog_value.get("accessible_episode_count"),
                        "source_rank_label": catalog_value.get("source_rank_label"),
                        "collected_at_utc": collected_at,
                        "source_url": url,
                    })
                    for ep in episode_list:
                        episodes.append({
                            "rank": row["rank"],
                            "series_id": sid,
                            "series_title": catalog_value["title"],
                            "episode_no": ep["episode_number"],
                            "source_episode_id": ep["episode_id"],
                            "source_page": source,
                            "expected_duration_seconds": "",
                            "actual_media_duration_seconds": "",
                            "full_video_file": "",
                            "subtitle_file": "",
                            "full_video_verified": False,
                            "source_id_coverage": "all_listed_episode_ids",
                            "source_collected_at_utc": collected_at,
                        })
                    # Frozen ranking metrics have a distinct earlier observation time.
                    metrics.extend([
                        {
                            "series_id": sid, "episode_id": "", "episode_no": "",
                            "scope": "drama", "metric": metric, "value": value,
                            "raw_value": value, "precision": "ranking_display",
                            "observed_at_utc": row["baseline_captured_at_utc"],
                            "source_url": row["ranking_source"],
                        }
                        for metric, value in (
                            ("hot_search_rank", row["rank"]),
                            ("hot_search_count_wan", row["hot_search_count_wan"]),
                        )
                    ])
                elif payload["episode_id"]:
                    observed = payload["episode_id"]
                    matched = [ep for ep in episodes if ep["source_episode_id"] == observed and ep["series_id"] == sid]
                    if not matched or matched[0]["episode_no"] != 1:
                        raise ValueError("Player episode ID disagrees with catalog first episode")
                    m = payload["media"]
                    media.append({
                        "series_id": sid, "episode_no": 1, "source_episode_id": observed,
                        "expected_duration_seconds": m.get("expected_duration_seconds"),
                        "width_px": m.get("width"), "height_px": m.get("height"),
                        "protected_playback_flag": m.get("protected_playback_flag"),
                        "direct_file_url_exposed": m.get("direct_file_url_exposed"),
                        "verified_full_video": False,
                        "source_collected_at_utc": collected_at,
                        "source_url": url,
                    })
                    matched[0]["expected_duration_seconds"] = m.get("expected_duration_seconds") or ""

                for m in payload["metrics"]:
                    metrics.append({
                        "series_id": sid, "episode_id": m.get("episode_id") or "",
                        "episode_no": 1 if m.get("scope") == "episode" else "",
                        "scope": m["scope"], "metric": m["metric"], "value": m["value"],
                        "raw_value": m.get("raw_value"), "precision": m.get("precision", ""),
                        "observed_at_utc": collected_at, "source_url": url,
                    })
                for r in payload["reviews"]:
                    reviews.append({
                        "series_id": sid,
                        "episode_id": payload["episode_id"] if kind == "player" else "",
                        "episode_no": 1 if kind == "player" else "",
                        "record_type": payload["review_record_type"],
                        "source_index": r["source_index"],
                        "text": r["content"],
                        "posted_at_utc": as_utc(r.get("create_time")),
                        "like_count": r.get("digg_count"),
                        "rating": r.get("rating"),
                        "comment_id": r.get("comment_id") or "",
                        "parent_comment_id": r.get("parent_id") or "",
                        "collected_at_utc": collected_at,
                        "source_url": url,
                        "coverage": "partial_page_preview",
                        "is_native_timed_danmaku": False,
                    })
            except Exception as exc:
                failures.append({"series_id": sid, "page_kind": kind, "source_url": url, "error": str(exc)})
                print(f"WARN {sid} {kind}: {exc}", file=sys.stderr)

    write_csv(out / "series_catalog.csv",
              ["rank", "series_id", "series_title", "official_detail_url", "synopsis",
               "genre", "web_rank_category", "platform_classification", "completion_status",
               "listed_episode_count", "confirmed_source_episode_ids", "accessible_episode_count_reported",
               "source_rank_label", "collected_at_utc", "source_url"], catalog)
    write_csv(out / "episode_catalog.csv",
              ["rank", "series_id", "series_title", "episode_no", "source_episode_id",
               "source_page", "expected_duration_seconds", "actual_media_duration_seconds",
               "full_video_file", "subtitle_file", "full_video_verified",
               "source_id_coverage", "source_collected_at_utc"], episodes)
    write_csv(out / "interaction_snapshots.csv",
              ["series_id", "episode_id", "episode_no", "scope", "metric", "value",
               "raw_value", "precision", "observed_at_utc", "source_url"], metrics)
    write_csv(out / "public_review_previews.csv",
              ["series_id", "episode_id", "episode_no", "record_type", "source_index",
               "text", "posted_at_utc", "like_count", "rating", "comment_id",
               "parent_comment_id", "collected_at_utc", "source_url", "coverage",
               "is_native_timed_danmaku"], reviews)
    write_csv(out / "first_episode_video_metadata.csv",
              ["series_id", "episode_no", "source_episode_id", "expected_duration_seconds",
               "width_px", "height_px", "protected_playback_flag", "direct_file_url_exposed",
               "verified_full_video", "source_collected_at_utc", "source_url"], media)
    write_csv(out / "source_receipts.csv",
              ["series_id", "page_kind", "source_url", "collected_at_utc", "response_sha256",
               "response_bytes", "reported_review_total", "embedded_review_preview_count",
               "review_coverage"], receipts)
    summary = {
        "created_at_utc": utcnow(),
        "frozen_cohort_size": len(cohort),
        "dramas_with_validated_all_episode_ids": len(catalog),
        "real_source_episode_ids": len(episodes),
        "first_episode_video_metadata_records": len(media),
        "interaction_metric_rows": len(metrics),
        "public_review_preview_rows": len(reviews),
        "fully_verified_episode_files": 0,
        "verified_native_timed_danmaku_records_in_this_export": 0,
        "comment_replies_expanded": 0,
        "missing": {
            "full_copyright_approved_video_files": "not downloaded",
            "original_media_decode_and_duration_verification": "not performed",
            "native_danmaku_source_offsets_and_ids": "not available from public page",
            "all_episode_level_interaction": "public detail exposes drama data; first player exposes episode 1 only",
            "views_and_shares": "not available where source omits them",
            "historical_full_comments_and_reply_pagination": "only embedded preview",
            "v1_initial_ui_snapshot": "single Android UI collection only",
        },
        "failures": failures,
    }
    (out / "collection_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort-csv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--delay", type=float, default=2)
    args = parser.parse_args()
    with args.cohort_csv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    summary = collect(rows, args.out, args.delay)
    return 0 if summary["dramas_with_validated_all_episode_ids"] == 10 and len(summary["failures"]) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
