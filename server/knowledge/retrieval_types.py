"""Phase 15 检索 DTO 唯一出口（RETR-06/07 结构化契约）。

REST/MCP/chat/workflow 入口（Phase 16）与内部 service 均使用本模块 dataclass，
禁止散落裸 dict 传递检索结果。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

__all__ = [
    "EntityMetadata",
    "ProvenanceLinks",
    "RelatedEntityDTO",
    "SearchResultDTO",
    "TimelineNodeDTO",
]

LlmGrade = Literal["duplicate", "related", "unrelated"]


@dataclass(frozen=True, slots=True)
class ProvenanceLinks:
    """出处链接集合（按 entity_kind 填充可用字段）。"""

    feishu_url: str | None = None
    mr_url: str | None = None
    session_link: str | None = None


@dataclass(frozen=True, slots=True)
class EntityMetadata:
    """检索结果实体 metadata（RETR-06 必填字段）。"""

    entity_id: uuid.UUID
    entity_kind: str
    version: int
    title: str
    valid_at: datetime | None
    invalid_at: datetime | None
    source_kind: str
    source_id: str
    origin: str
    event_time: datetime | None
    space_id: str | None
    repository_id: str | None
    provenance: ProvenanceLinks = field(default_factory=ProvenanceLinks)
    superseded_hint: str | None = None


@dataclass(frozen=True, slots=True)
class RelatedEntityDTO:
    """图关联实体（get_related / graph enrich 用）。"""

    entity_id: uuid.UUID
    entity_kind: str
    relation: str
    depth: int
    metadata: EntityMetadata | None = None


@dataclass(frozen=True, slots=True)
class TimelineNodeDTO:
    """迭代轨迹节点（get_timeline 纯 PG 输出）。"""

    entity_id: uuid.UUID
    version: int
    kind: str
    title: str
    summary: str
    valid_at: datetime | None
    invalid_at: datetime | None
    event_time: datetime | None
    provenance: ProvenanceLinks = field(default_factory=ProvenanceLinks)
    code_changes: tuple[EntityMetadata, ...] = ()


@dataclass(slots=True)
class SearchResultDTO:
    """相似检索单条结果（向量+图融合 + 可选 LLM 分级）。"""

    score: float
    vector_score: float
    recency_score: float
    entity: EntityMetadata
    related_entities: list[RelatedEntityDTO] = field(default_factory=list)
    llm_grade: LlmGrade | None = None
    llm_reason: str | None = None
    # PageIndex 章节路径（如 ["接口设计", "鉴权"]）：命中 chunk 所属章节链，
    # 空列表表示该版本无章节树或 chunk 未归属章节。
    toc_path: list[str] = field(default_factory=list)
