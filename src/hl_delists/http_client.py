"""Small HTTP client with a project User-Agent and a per-host pause."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

USER_AGENT = (
    "hl-delists/0.1 (+https://github.com/asierbayon/hl-delists; public-good delist calendar)"
)


class PoliteHttp:
    def __init__(self, min_interval: float = 1.0) -> None:
        self.min_interval = min_interval
        self._last_by_host: dict[str, float] = {}

    def get_text(self, url: str, accept: str = "*/*") -> str:
        return self._read(url, accept=accept, data=None).decode("utf-8", "replace")

    def get_json(self, url: str) -> object:
        body = self._read(url, accept="application/json", data=None)
        return json.loads(body.decode("utf-8"))

    def post_json(self, url: str, payload: dict) -> object:
        data = json.dumps(payload).encode("utf-8")
        body = self._read(url, accept="application/json", data=data)
        return json.loads(body.decode("utf-8"))

    def _read(self, url: str, *, accept: str, data: bytes | None) -> bytes:
        self._wait(url)
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": accept,
                "Content-Type": "application/json",
            },
            method="POST" if data is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504}:
                raise
            time.sleep(5)
            self._last_by_host[urlparse(url).netloc] = time.monotonic()
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read()

    def _wait(self, url: str) -> None:
        host = urlparse(url).netloc
        previous = self._last_by_host.get(host)
        now = time.monotonic()
        if previous is not None:
            remaining = self.min_interval - (now - previous)
            if remaining > 0:
                time.sleep(remaining)
        self._last_by_host[host] = time.monotonic()
