"""Conservative public-page HTTP client with robots, delay, and retries."""
from __future__ import annotations
import logging
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .util import validate_public_http_url

LOG = logging.getLogger(__name__)
DEFAULT_UA = "AcademicMicroDramaCollector/1.0 (public pages; contact: configurable)"


class PublicClient:
    def __init__(self, allowed_hosts: set[str], delay: float = 2.0, user_agent: str = DEFAULT_UA):
        if delay < 1:
            raise ValueError("At least 1 second delay required")
        self.allowed_hosts = allowed_hosts
        self.delay = delay
        self.user_agent = user_agent
        self.last_access = 0.0
        self._robots = {}
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": user_agent, "Accept-Language": "zh-CN,zh;q=0.9", "Accept": "text/html,*/*;q=0.5"})
        self.s.mount("https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504], allowed_methods={"GET"}, respect_retry_after_header=True)))

    def _rate_limit(self):
        wait = self.delay - (time.monotonic() - self.last_access)
        if wait > 0:
            time.sleep(wait)
        self.last_access = time.monotonic()

    def _verify_robots(self, url):
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            self._rate_limit()
            res = self.s.get(origin + "/robots.txt", timeout=(10, 25), allow_redirects=False)
            if 300 <= res.status_code < 400:
                raise PermissionError('robots.txt redirected; policy could not be verified')
            if res.status_code == 404:
                self._robots[origin] = None
            else:
                res.raise_for_status()
                rp = RobotFileParser()
                rp.parse(res.text.splitlines())
                self._robots[origin] = rp
        rp = self._robots[origin]
        if rp is not None and not rp.can_fetch(self.user_agent, url):
            raise PermissionError(f"robots.txt disallows {url}")

    def get_html(self, url: str, max_bytes=12_000_000) -> str:
        validate_public_http_url(url, self.allowed_hosts)
        self._verify_robots(url)   # inaccessible robots -> fail closed
        self._rate_limit()
        r = self.s.get(url, timeout=(10, 40), allow_redirects=False, stream=True)
        if 300 <= r.status_code < 400:
            raise RuntimeError("Redirect requires independent permission check; stopping")
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "")
        if content_type and "html" not in content_type and "text/plain" not in content_type:
            raise ValueError(f"Unexpected HTML type {content_type}")
        chunks, n = [], 0
        for chunk in r.iter_content(chunk_size=1024 * 64):
            n += len(chunk)
            if n > max_bytes:
                raise ValueError("Response exceeds HTML size limit")
            chunks.append(chunk)
        data = b"".join(chunks)
        return data.decode(r.encoding or "utf-8", errors="replace")
