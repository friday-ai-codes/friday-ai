"""交付知识 DTO 序列化共享出口（Phase 16 EXPO）。

MCP / chat / workflow / REST 四入口复用，避免字段漂移。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from django.utils import dateparse

from knowledge.graph_store import require_aware
from knowledge.retrieval_types import (
    EntityMetadata,
    ProvenanceLinks,
    RelatedEntityDTO,
    SearchResultDTO,
    TimelineNodeDTO,
)

__all__ = [
    "format_search_results_markdown",
    "parse_as_of",
    "serialize_entity_metadata",
    "serialize_related",
    "serialize_search_result",
    "serialize_search_results",
    "serialize_timeline",
]


def parse_as_of(raw: str | None) -> datetime | None:
    """解析可选 as_of ISO8601 字符串；拒绝 naive / 非法格式。"""
    if raw is None or raw == "":
        return None
    dt = dateparse.parse_datetime(str(raw))
    if dt is None:
        raise ValueError(f"as_of 不是合法 ISO8601: {raw!r}")
    return require_aware(dt, "as_of")


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _serialize_provenance(provenance: ProvenanceLinks) -> dict[str, Any]:
    return _jsonable(
        {
            "feishu_url": provenance.feishu_url,
            "mr_url": provenance.mr_url,
            "session_link": provenance.session_link,
        }
    )


def serialize_entity_metadata(meta: EntityMetadata) -> dict[str, Any]:
    return _jsonable(
        {
            "entity_id": meta.entity_id,
            "kind": meta.entity_kind,
            "version": meta.version,
            "title": meta.title,
            "valid_at": meta.valid_at,
            "invalid_at": meta.invalid_at,
            "source_kind": meta.source_kind,
            "source_id": meta.source_id,
            "origin": meta.origin,
            "event_time": meta.event_time,
            "project_id": meta.space_id,
            "repository_id": meta.repository_id,
            "provenance": _serialize_provenance(meta.provenance),
            "superseded_hint": meta.superseded_hint,
        }
    )


def serialize_search_result(result: SearchResultDTO) -> dict[str, Any]:
    return _jsonable(
        {
            "entity_id": result.entity.entity_id,
            "kind": result.entity.entity_kind,
            "title": result.entity.title,
            "version": result.entity.version,
            "score": result.score,
            "vector_score": result.vector_score,
            "recency_score": result.recency_score,
            "provenance": _serialize_provenance(result.entity.provenance),
            "llm_grade": result.llm_grade,
            "llm_reason": result.llm_reason,
            "toc_path": result.toc_path,
            "related_entities": [serialize_related_item(r) for r in result.related_entities],
        }
    )


def serialize_search_results(results: list[SearchResultDTO]) -> list[dict[str, Any]]:
    return [serialize_search_result(r) for r in results]


def serialize_timeline(nodes: list[TimelineNodeDTO]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in nodes:
        out.append(
            _jsonable(
                {
                    "entity_id": node.entity_id,
                    "version": node.version,
                    "kind": node.kind,
                    "title": node.title,
                    "summary": node.summary,
                    "valid_at": node.valid_at,
                    "invalid_at": node.invalid_at,
                    "event_time": node.event_time,
                    "provenance": _serialize_provenance(node.provenance),
                    "code_changes": [serialize_entity_metadata(cc) for cc in node.code_changes],
                }
            )
        )
    return out


def serialize_related_item(item: RelatedEntityDTO) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "entity_id": item.entity_id,
        "kind": item.entity_kind,
        "relation": item.relation,
        "depth": item.depth,
    }
    if item.metadata is not None:
        payload["metadata"] = serialize_entity_metadata(item.metadata)
    return _jsonable(payload)


def serialize_related(related: list[RelatedEntityDTO]) -> list[dict[str, Any]]:
    return [serialize_related_item(r) for r in related]


def format_search_results_markdown(
    results: list[SearchResultDTO],
    *,
    as_of: datetime | None = None,
) -> str:
    """将检索结果格式化为 markdown 段落，供 workflow/chat 注入。"""
    if not results:
        return ""
    lines = ["## 相似历史交付"]
    if as_of is not None:
        lines.append(f"\n> 历史视点：{as_of.isoformat()}\n")
    for result in results:
        entity = result.entity
        prov = entity.provenance
        links: list[str] = []
        if prov.feishu_url:
            links.append(f"[飞书]({prov.feishu_url})")
        if prov.mr_url:
            links.append(f"[MR]({prov.mr_url})")
        if prov.session_link:
            links.append(f"[会话]({prov.session_link})")
        prov_text = " · ".join(links) if links else "无出处链接"
        grade = f" / LLM: {result.llm_grade}" if result.llm_grade else ""
        lines.append(
            f"- **{entity.title}** ({entity.entity_kind}, score={result.score:.2f}{grade})\n"
            f"  - 出处：{prov_text}"
        )
    return "\n".join(lines)
