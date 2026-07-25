"""交付知识 chat agent tool 输入契约（Phase 16-02）。

只声明 **Input**。输出侧的权威契约是 ``knowledge/exposure.py`` 的 serializer
（``serialize_search_results`` / ``serialize_timeline`` / ``serialize_related``），
它们随召回能力持续扩字段（vector_score、toc_path、code_changes、related_entities…）。

原先这里还有一组 Output 模型，但从未被 tool 引用，且已与 serializer 严重漂移——
``serialize_search_result`` 实产 15 个字段而 ``SearchResultItemOutput`` 只声明 8 个
且 ``extra="forbid"``。套上去只有两种结果：报错，或悄悄砍掉 7 个本该给 LLM 的字段。
与其维护一份跟不上的平行契约，不如让 serializer 单独持有输出形状。
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Direction = Literal["both", "out", "in"]


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


class GetEntityTimelineInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    entity_id: uuid.UUID
    include_superseded: bool = False
    as_of: str | None = None
    conversation_id: str = ""


class GetRelatedEntitiesInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    entity_id: uuid.UUID
    direction: Direction = "both"
    max_hops: int = Field(default=2, ge=1, le=3)
    as_of: str | None = None
    conversation_id: str = ""

