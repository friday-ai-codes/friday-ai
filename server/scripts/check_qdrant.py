"""Quick Qdrant connectivity check.

URL comes from QDRANT_URL / QDRANT_HOST env (never hardcode internal hostnames).
"""

from __future__ import annotations

import os
import sys

import httpx

QDRANT_URL = (
    os.environ.get("QDRANT_URL")
    or os.environ.get("QDRANT_HOST")
    or "http://127.0.0.1:6333"
).rstrip("/")

endpoints = [
    ("GET", "/", "Root"),
    ("GET", "/readyz", "Ready check"),
    ("GET", "/collections", "List collections"),
]

if __name__ == "__main__":
    for method, path, label in endpoints:
        url = f"{QDRANT_URL}{path}"
        try:
            r = httpx.request(method, url, timeout=5)
            print(f"{label}: {r.status_code} - {r.text[:200]}")
        except Exception as e:
            print(f"{label}: ERROR - {e}", file=sys.stderr)
