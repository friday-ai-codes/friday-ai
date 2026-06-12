"""交付知识 chat agent tool 输入/输出契约（Phase 16-02）。"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Direction = Literal["both", "out", "in"]


class ProvenanceOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    feishu_url: str | None = None
    mr_url: str | None = None
    session_link: str | None = None


class SearchDeliveryKnowledgeInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    project_ids: list[str] = Field(default_factory=list)
    repository_ids: list[str] = Field(default_factory=list)
    entity_kinds: list[str] = Field(default_factory=list)
    as_of: str | None = None
    include_superseded: bool = False
    conversation_id: str = ""


class SearchResultItemOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    entity_id: uuid.UUID
    kind: str
    title: str
    version: int
    score: float
    provenance: ProvenanceOutput
    llm_grade: str | None = None
    llm_reason: str | None = None


class SearchDeliveryKnowledgeOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    query: str
    results: list[SearchResultItemOutput]
    total: int
    as_of: str | None = None


class GetEntityTimelineInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    entity_id: uuid.UUID
    include_superseded: bool = False
    as_of: str | None = None
    conversation_id: str = ""


class TimelineNodeOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    entity_id: uuid.UUID
    version: int
    kind: str
    title: str
    summary: str


class GetEntityTimelineOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    entity_id: uuid.UUID
    nodes: list[TimelineNodeOutput]
    total: int


class GetRelatedEntitiesInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    entity_id: uuid.UUID
    direction: Direction = "both"
    max_hops: int = Field(default=2, ge=1, le=3)
    as_of: str | None = None
    conversation_id: str = ""


class RelatedEntityItemOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    entity_id: uuid.UUID
    kind: str
    relation: str
    depth: int
    provenance: ProvenanceOutput | None = None


class GetRelatedEntitiesOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    entity_id: uuid.UUID
    related: list[RelatedEntityItemOutput]
    total: int
    as_of: str | None = None
