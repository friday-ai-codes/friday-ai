"""Graph query 跨消费面 canonical manifest 与稳定 hash。"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "graph-query.v1.json"
)


@lru_cache(maxsize=1)
def graph_query_manifest() -> dict[str, Any]:
    """返回独立副本，避免消费面意外改写进程级 canonical 数据。"""
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def graph_query_manifest_hash() -> str:
    return hashlib.sha256(_MANIFEST_PATH.read_bytes()).hexdigest()


__all__ = ["graph_query_manifest", "graph_query_manifest_hash"]
