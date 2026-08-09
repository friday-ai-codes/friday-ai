"""只读 rename_preview 双源合并内核（Phase 126 / RENAME-01 / D-09..D-11）。

图半边：定义点 + 一跳 incoming callers（predecessors，RESEARCH A3）。
文本半边：由编排层经 ``grep_mirror`` + exclusion 喂入；本模块**禁止**裸扫。

⛔ 永不写工作树 / mirror；``applied`` 恒为 ``False``。
⛔ 不 import ``repo_router_v2``；零 ORM（编排在 ``code_graph_tools``）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

import networkx as nx

from common.logging import redact_secrets_in_text

COVERAGE_LIMITATIONS: Final[str] = (
    "动态引用/字符串模板/反射/getattr/配置拼路径等 v1 不保证命中"
)

DEFAULT_CONTEXT_LINES: Final[int] = 2
MAX_CONTEXT_LINES: Final[int] = 5
MAX_CONTEXT_CHARS: Final[int] = 240

CONFIDENCE_GRAPH: Final[str] = "graph"
CONFIDENCE_TEXT: Final[str] = "text_search"

__all__ = [
    "COVERAGE_LIMITATIONS",
    "CONFIDENCE_GRAPH",
    "CONFIDENCE_TEXT",
    "DEFAULT_CONTEXT_LINES",
    "MAX_CONTEXT_LINES",
    "clamp_context_lines",
    "collect_graph_edit_sites",
    "merge_dual_source_edits",
]


def clamp_context_lines(context_lines: int | None) -> int:
    """默认 2，上限 5（D-09 / T-126-03）。"""
    if context_lines is None:
        return DEFAULT_CONTEXT_LINES
    try:
        n = int(context_lines)
    except (TypeError, ValueError):
        return DEFAULT_CONTEXT_LINES
    return max(0, min(n, MAX_CONTEXT_LINES))


def collect_graph_edit_sites(
    graph: nx.MultiDiGraph,
    seed_symbol_id: str,
) -> list[dict[str, Any]]:
    """图半边站点：种子定义点 + 一跳 predecessors（A3）。"""
    if seed_symbol_id not in graph:
        return []

    sites: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    def _add(symbol_id: str, *, kind: str) -> None:
        attrs = graph.nodes[symbol_id]
        file_path = str(attrs.get("file_path") or "")
        line = int(attrs.get("start_line") or 0)
        if not file_path or line <= 0:
            return
        key = (file_path, line)
        if key in seen:
            return
        seen.add(key)
        sites.append(
            {
                "file_path": file_path,
                "line": line,
                "symbol_id": str(symbol_id),
                "name": str(attrs.get("name") or ""),
                "kind": kind,
            }
        )

    _add(seed_symbol_id, kind="definition")
    try:
        preds = list(graph.predecessors(seed_symbol_id))
    except nx.NetworkXError:
        preds = []
    for pred in preds:
        _add(str(pred), kind="caller")
    return sites


def _redact_context(text: str) -> str:
    clipped = (text or "")[:MAX_CONTEXT_CHARS]
    try:
        return redact_secrets_in_text(clipped)
    except Exception:  # noqa: BLE001 — 观测/脱敏永不反噬
        return clipped


def merge_dual_source_edits(
    *,
    graph_sites: Sequence[Mapping[str, Any]],
    text_matches: Sequence[Mapping[str, Any]],
    old_name: str,
    new_name: str,
    context_by_key: Mapping[tuple[str, int], str] | None = None,
) -> dict[str, Any]:
    """按 file:line 合并双源；同键以 graph 为准并可保留 sources（D-10）。

    返回片段含 ``applied: False`` / ``files`` / ``summary`` / ``coverage_limitations``。
    """
    ctx = context_by_key or {}
    by_key: dict[tuple[str, int], dict[str, Any]] = {}

    for site in graph_sites:
        file_path = str(site.get("file_path") or "")
        line = int(site.get("line") or 0)
        if not file_path or line <= 0:
            continue
        key = (file_path, line)
        context = ctx.get(key, "")
        by_key[key] = {
            "line": line,
            "confidence": CONFIDENCE_GRAPH,
            "sources": [CONFIDENCE_GRAPH],
            "context": _redact_context(context),
            "old_text": old_name,
            "new_text": new_name,
        }

    for match in text_matches:
        if str(match.get("kind") or "match") != "match":
            continue
        file_path = str(match.get("file_path") or "")
        line = int(match.get("line") or 0)
        if not file_path or line <= 0:
            continue
        key = (file_path, line)
        content = str(match.get("content") or "")
        if key in by_key:
            sources = list(by_key[key].get("sources") or [])
            if CONFIDENCE_TEXT not in sources:
                sources.append(CONFIDENCE_TEXT)
            by_key[key]["sources"] = sources
            by_key[key]["confidence"] = CONFIDENCE_GRAPH
            if not by_key[key].get("context") and content:
                by_key[key]["context"] = _redact_context(content)
            continue
        by_key[key] = {
            "line": line,
            "confidence": CONFIDENCE_TEXT,
            "sources": [CONFIDENCE_TEXT],
            "context": _redact_context(content or ctx.get(key, "")),
            "old_text": old_name,
            "new_text": new_name,
        }

    files_map: dict[str, list[dict[str, Any]]] = {}
    for (file_path, _line), edit in sorted(by_key.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        files_map.setdefault(file_path, []).append(edit)

    files = [{"file_path": fp, "edits": edits} for fp, edits in sorted(files_map.items())]
    graph_edits = sum(
        1 for f in files for e in f["edits"] if e["confidence"] == CONFIDENCE_GRAPH
    )
    text_search_edits = sum(
        1 for f in files for e in f["edits"] if e["confidence"] == CONFIDENCE_TEXT
    )
    total = graph_edits + text_search_edits
    return {
        "applied": False,
        "coverage_limitations": COVERAGE_LIMITATIONS,
        "files": files,
        "summary": {
            "total_edits": total,
            "files_affected": len(files),
            "graph_edits": graph_edits,
            "text_search_edits": text_search_edits,
        },
    }
