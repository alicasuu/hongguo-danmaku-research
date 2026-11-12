"""Small dependency-free utilities."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def json_str(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def file_sha256(path: str | Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def stable_hash(*parts: object) -> str:
    return hashlib.sha256("\0".join(str(x or "") for x in parts).encode("utf-8")).hexdigest()


def clean_text(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def metric_number(value: object) -> float | None:
    """Convert labelled Chinese count, without conflating heat with views."""
    if value is None or str(value).strip() in ("", "—", "-", "N/A"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace(",", "").replace(" ", "")
    m = re.search(r"(\d+(?:\.\d+)?)(亿|千万|百万|万|千|k|K|M|B)?", s)
    if not m:
        return None
    mult = {"亿": 1e8, "千万": 1e7, "百万": 1e6, "万": 1e4, "千": 1e3, "k": 1e3, "K": 1e3, "M": 1e6, "B": 1e9}.get(m.group(2), 1)
    return float(m.group(1)) * mult


def validate_public_http_url(url: str, allowed_hosts: set[str], *, https_only: bool = True):
    u = urlsplit(url)
    if u.scheme not in ({"https"} if https_only else {"https", "http"}):
        raise ValueError("Unsupported URL scheme; HTTPS required")
    if not u.hostname or u.username or u.password or u.port:
        raise ValueError("Invalid public URL; credentials and custom ports not allowed")
    host = u.hostname.lower().rstrip(".")
    if host not in allowed_hosts:
        raise ValueError(f"Host {host!r} is not in your approved allowlist")
    return url


def is_truthy(x: object) -> bool:
    return str(x).strip().lower() in {"1", "yes", "true", "y"}
