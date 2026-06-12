"""检索命中 chunk → 章节路径回溯 + tree-walk 上下文扩展（PageIndex 化）。

- resolve_toc_paths：批量把 VectorHit 映射到其所属章节路径
  （新 point payload 带 chunk_index；旧 point 用 version.qdrant_point_ids
  的位置反推 index，向后兼容无需重建向量）。
- get_chunk_tree_context：tree-walk——命中章节的父节点摘要 + 相邻章节标题，
  供消费方按需拼接补充上下文（context-aware retrieval）。
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from knowledge.toc_tree import find_node_path_for_chunk
from knowledge.vector_recall import VectorHit

logger = structlog.get_logger(__name__)

__all__ = ["resolve_toc_paths", "get_chunk_tree_context"]


def _resolve_chunk_index(
    hit: VectorHit, point_ids: list[str]
) -> int | None:
    chunk_index = hit.payload.get("chunk_index")
    if isinstance(chunk_index, int):
        return chunk_index
    try:
        return point_ids.index(hit.point_id)
    except ValueError:
        return None


async def resolve_toc_paths(hits: list[VectorHit]) -> dict[str, list[str]]:
    """批量解析命中 chunk 的章节路径；key 为 point_id。

    任一环节缺数据（无 toc_tree / index 反推失败）该 hit 返回 []，不影响检索。
    """
    version_ids: set[str] = set()
    for hit in hits:
        vid = str(hit.payload.get("version_id", ""))
        if vid:
            version_ids.add(vid)
    if not version_ids:
        return {}

    from knowledge.models import KnowledgeEntityVersion

    def _load() -> dict[str, tuple[list[dict[str, Any]], list[str]]]:
        out: dict[str, tuple[list[dict[str, Any]], list[str]]] = {}
        for row in KnowledgeEntityVersion.objects.filter(
            id__in=[uuid.UUID(v) for v in version_ids]
        ).values("id", "toc_tree", "qdrant_point_ids"):
            out[str(row["id"])] = (
                row["toc_tree"] or [],
                [str(p) for p in (row["qdrant_point_ids"] or [])],
            )
        return out

    try:
        version_map = await sync_to_async(_load, thread_sensitive=False)()
    except Exception:  # noqa: BLE001 — 章节路径是增强信息，失败不阻塞检索
        logger.warning("toc_path_resolve_failed", exc_info=True)
        return {}

    result: dict[str, list[str]] = {}
    for hit in hits:
        vid = str(hit.payload.get("version_id", ""))
        entry = version_map.get(vid)
        if not entry:
            continue
        toc_tree, point_ids = entry
        if not toc_tree:
            continue
        chunk_index = _resolve_chunk_index(hit, point_ids)
        if chunk_index is None:
            continue
        path = find_node_path_for_chunk(toc_tree, chunk_index)
        if path:
            result[hit.point_id] = path
    return result


def get_chunk_tree_context(
    toc_tree: list[dict[str, Any]], chunk_index: int
) -> dict[str, Any]:
    """tree-walk 上下文扩展：命中章节的父摘要 + 相邻章节标题。

    Returns:
        {"node_path": [...], "parent_summary": str, "siblings": [str]}；
        chunk 未归属章节时返回空骨架。
    """
    target_path = find_node_path_for_chunk(toc_tree, chunk_index)
    if not target_path:
        return {"node_path": [], "parent_summary": "", "siblings": []}

    parent_summary = ""
    siblings: list[str] = []
    nodes = toc_tree
    parent: dict[str, Any] | None = None
    for title in target_path:
        match = next(
            (n for n in nodes if str(n.get("title", "")) == title), None
        )
        if match is None:
            break
        parent_summary = str(parent.get("summary", "")) if parent else ""
        siblings = [
            str(n.get("title", "")) for n in nodes if n is not match
        ]
        parent = match
        nodes = match.get("children", [])

    return {
        "node_path": target_path,
        "parent_summary": parent_summary,
        "siblings": siblings[:10],
    }
