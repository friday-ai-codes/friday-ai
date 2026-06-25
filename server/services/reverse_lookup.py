"""片段→需求反查服务（Phase 34 RREF-01）。

给定 code chunk / 模块（``(repository_id, file_path, line)`` 或 ``chunk_id``），反查关联的
需求（``work_item``）与文档（``document``），并给出多跳关联路径。链路（全部经既有只读接口，
不新建底层图谱/检索机制）：

    chunk ←MODIFIES_CHUNK code_change ←IMPLEMENTED_BY tech_plan ←HAS_PLAN work_item
    work_item →REFERENCES document

安全边界（沿用 v0.5 ``find_chunk_at`` 的 fail-closed 排除，DOMAIN §9.1）：
- ``(file_path, line)`` 入参经 ``find_chunk_at`` 定位 chunk，被排除文件返回空（不泄漏
  chunk/行位置/关联实体）。
- ``chunk_id`` 直接入参绕过 ``find_chunk_at``，故先由 ``ChunkRegistry`` 复判其 ``file_path``
  并经同一排除匹配器 fail-closed 复检，命中排除一律返回空（不绕过安全边界）。

视图语义（衔接 Phase 33 bi-temporal as-of）：默认当前视图（``as_of=None``），被置
``invalid_at`` 的过期 ``MODIFIES_CHUNK`` 边天然排除，历史失效关联不污染当前反查。

纯读纪律：全程只走图谱/注册表的只读查询接口，绝不新增或失效图谱边、绝不写实体；
任何分支缺料只产空集合，不抛。
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from knowledge.graph_store import graph_store
from knowledge.models import EdgeRelation
from services.exclusion import (
    build_matcher_for_repo,
    log_exclusion_blocked,
    normalize_rel_path,
)

logger = structlog.get_logger(__name__)

__all__ = ["reverse_lookup"]


def _empty_result() -> dict[str, Any]:
    return {
        "chunks": [],
        "related_work_items": [],
        "related_documents": [],
        "paths": [],
    }


async def reverse_lookup(
    repository_id: str,
    *,
    file_path: str | None = None,
    line: int | None = None,
    chunk_id: str | None = None,
    branch_name: str = "",
) -> dict[str, Any]:
    """片段→需求反查（纯读，fail-closed）。

    入参二选一：``(file_path, line)`` 或 ``chunk_id``；两者都缺则返回空结构。

    Returns:
        ``{"chunks": [...], "related_work_items": [...], "related_documents": [...],
        "paths": [...]}``（REST 与 MCP 同形契约）。
    """
    # 第一步：解析 chunk 列表（每条 fail-closed）
    if file_path is not None and line is not None:
        from services.chunk_lookup import find_chunk_at

        chunks = await find_chunk_at(repository_id, file_path, line, branch_name=branch_name)
    elif chunk_id is not None:
        chunks = await _resolve_chunk_by_id(repository_id, chunk_id)
    else:
        return _empty_result()

    if not chunks:
        return _empty_result()

    # 第二步：逐 chunk 反向多跳（默认 as_of=None 当前视图，过期边天然排除）
    code_change_ids: set[uuid.UUID] = set()
    paths: list[dict[str, Any]] = []
    work_item_ids: list[uuid.UUID] = []
    tech_plan_ids: set[uuid.UUID] = set()
    document_ids: list[uuid.UUID] = []
    seen_work_items: set[uuid.UUID] = set()
    seen_documents: set[uuid.UUID] = set()

    for chunk in chunks:
        chunk_uuid = uuid.UUID(str(chunk["chunk_id"]))
        in_edges = await graph_store.chunk_in_edges(chunk_uuid)
        for edge in in_edges:
            if edge.relation != EdgeRelation.MODIFIES_CHUNK:
                continue
            code_change_id = edge.source_id
            code_change_ids.add(code_change_id)
            # code_change ←IMPLEMENTED_BY tech_plan
            tp_edges = await graph_store.neighbors(
                code_change_id, relations=[EdgeRelation.IMPLEMENTED_BY], direction="in"
            )
            for tp_edge in tp_edges:
                tech_plan_id = tp_edge.source_id
                tech_plan_ids.add(tech_plan_id)
                # tech_plan ←HAS_PLAN work_item
                wi_edges = await graph_store.neighbors(
                    tech_plan_id, relations=[EdgeRelation.HAS_PLAN], direction="in"
                )
                for wi_edge in wi_edges:
                    work_item_id = wi_edge.source_id
                    if work_item_id not in seen_work_items:
                        seen_work_items.add(work_item_id)
                        work_item_ids.append(work_item_id)
                    # work_item →REFERENCES document
                    doc_edges = await graph_store.neighbors(
                        work_item_id, relations=[EdgeRelation.REFERENCES], direction="out"
                    )
                    related_docs = [d.target_id for d in doc_edges if d.target_id is not None]
                    for document_id in related_docs:
                        if document_id not in seen_documents:
                            seen_documents.add(document_id)
                            document_ids.append(document_id)
                        paths.append(
                            _build_path(
                                chunk_uuid, code_change_id, tech_plan_id, work_item_id, document_id
                            )
                        )
                    if not related_docs:
                        paths.append(
                            _build_path(
                                chunk_uuid, code_change_id, tech_plan_id, work_item_id, None
                            )
                        )

    # 同一 code_change 经多入参 chunk 命中、或同一 work_item 经多 tech_plan 抵达时会产生
    # 重复 path 项，按字段元组去重并保序（IN-02：不改变输出形态，仅去除语义重复）
    seen_paths: set[tuple[Any, ...]] = set()
    deduped_paths: list[dict[str, Any]] = []
    for p in paths:
        key = (
            p["chunk_id"],
            p["code_change_id"],
            p["tech_plan_id"],
            p["work_item_id"],
            p["document_id"],
        )
        if key not in seen_paths:
            seen_paths.add(key)
            deduped_paths.append(p)
    paths = deduped_paths

    # 第三步：hydrate 实体 + 组装
    # 仅 hydrate 需序列化的 id（work_item/document）；tech_plan/code_change 仅以 id 串入 paths，
    # 无需取回实体（IN-01：避免多余取回体量）
    entity_ids = set(work_item_ids) | set(document_ids)
    entities = await _hydrate_entities(entity_ids)

    related_work_items = [
        _serialize_work_item(entities[eid])
        for eid in work_item_ids
        if eid in entities and entities[eid]["kind"] == "work_item"
    ]
    related_documents = [
        _serialize_document(entities[eid])
        for eid in document_ids
        if eid in entities and entities[eid]["kind"] == "document"
    ]

    logger.info(
        "reverse_lookup_completed",
        repository_id=repository_id,
        chunk_count=len(chunks),
        work_item_count=len(related_work_items),
        document_count=len(related_documents),
    )
    return {
        "chunks": chunks,
        "related_work_items": related_work_items,
        "related_documents": related_documents,
        "paths": paths,
    }


def _build_path(
    chunk_uuid: uuid.UUID,
    code_change_id: uuid.UUID,
    tech_plan_id: uuid.UUID,
    work_item_id: uuid.UUID,
    document_id: uuid.UUID | None,
) -> dict[str, Any]:
    relations = [
        EdgeRelation.MODIFIES_CHUNK.value,
        EdgeRelation.IMPLEMENTED_BY.value,
        EdgeRelation.HAS_PLAN.value,
    ]
    if document_id is not None:
        relations.append(EdgeRelation.REFERENCES.value)
    return {
        "chunk_id": str(chunk_uuid),
        "code_change_id": str(code_change_id),
        "tech_plan_id": str(tech_plan_id),
        "work_item_id": str(work_item_id),
        "document_id": str(document_id) if document_id is not None else None,
        "relations": relations,
    }


async def _resolve_chunk_by_id(repository_id: str, chunk_id: str) -> list[dict[str, Any]]:
    """chunk_id 直接入参解析：查 ``ChunkRegistry`` 取 file_path，经排除匹配器 fail-closed 复判。

    构造异常 / 路径归一越界 / 命中排除规则一律埋点并返回 ``[]``（绝不放行），
    与 ``find_chunk_at`` 同口径，防止绕过 ``(file_path, line)`` 面的安全边界。
    """
    row = await _query_chunk_row(repository_id, chunk_id)
    if row is None:
        return []

    try:
        matcher = await build_matcher_for_repo(repository_id)
    except Exception as exc:  # noqa: BLE001 — 构造失败一律 fail-closed（对齐 chunk_lookup）
        logger.warning(
            "reverse_lookup_matcher_build_failed",
            repository_id=repository_id,
            error=str(exc),
        )
        log_exclusion_blocked(
            surface="reverse_lookup", repository_id=repository_id, rel_path=str(row["file_path"])
        )
        return []

    norm_path = normalize_rel_path(row["file_path"])
    if norm_path is None:
        return []
    if matcher.is_excluded(norm_path):
        log_exclusion_blocked(
            surface="reverse_lookup", repository_id=repository_id, rel_path=norm_path
        )
        return []
    return [row]


@sync_to_async
def _query_chunk_row(repository_id: str, chunk_id: str) -> dict[str, Any] | None:
    """同步 ORM：按 repository_id + chunk_id 取 chunk 行（经 sync_to_async 在异步上下文调用）。"""
    from code_relations.models import ChunkRegistry

    row = (
        ChunkRegistry.objects.filter(repository_id=repository_id, chunk_id=chunk_id)
        .values("chunk_id", "file_path", "line_start", "line_end", "chunk_index")
        .first()
    )
    if row is None:
        return None
    return {
        "chunk_id": str(row["chunk_id"]),
        "file_path": row["file_path"],
        "line_start": row["line_start"],
        "line_end": row["line_end"],
        "chunk_index": row["chunk_index"],
    }


@sync_to_async
def _hydrate_entities(entity_ids: set[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    """批量取实体身份字段（纯读 values 查询）。"""
    from knowledge.models import KnowledgeEntity

    if not entity_ids:
        return {}
    rows = KnowledgeEntity.objects.filter(id__in=list(entity_ids)).values(
        "id", "kind", "title", "source_kind", "source_id", "space_id"
    )
    return {row["id"]: row for row in rows}


def _serialize_work_item(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": str(entity["id"]),
        "title": entity["title"],
        "source_kind": entity["source_kind"],
        "source_id": entity["source_id"],
        "project_id": str(entity["space_id"]) if entity["space_id"] else None,
    }


def _serialize_document(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": str(entity["id"]),
        "title": entity["title"],
        "source_kind": entity["source_kind"],
        "source_id": entity["source_id"],
    }
