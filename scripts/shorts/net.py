"""Shared HTTP concerns.

The browser user-agent below had been copy-pasted into four modules. That is
not merely untidy: it is a value with a REASON — Cloudflare answers default
library agents with 403 "error code: 1010", which is why every outbound fetch
here must look like a browser. Four copies means four places to fix when a
publisher tightens its rules, and three of them will be missed.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Optional

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 "
              "Safari/537.36")


def request(url: str, *, headers: Optional[dict] = None) -> urllib.request.Request:
    """A request that reads as a browser, with caller headers layered on."""
    h = {"User-Agent": BROWSER_UA}
    h.update(headers or {})
    return urllib.request.Request(url, headers=h)


def get_bytes(url: str, *, headers: Optional[dict] = None,
              timeout: int = 30) -> bytes:
    with urllib.request.urlopen(request(url, headers=headers), timeout=timeout) as r:
        return r.read()


def get_json(url: str, *, headers: Optional[dict] = None,
             timeout: int = 30) -> Any:
    h = {"Accept": "application/json"}
    h.update(headers or {})
    return json.loads(get_bytes(url, headers=h, timeout=timeout))
