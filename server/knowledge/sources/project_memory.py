"""项目记忆正文 → knowledge document 投影 normalizer（CTX-01/02）。

镜像 ``sources/project_doc.py`` 范式：把 **active** ``ProjectMemory`` 条目正文摄取进
``delivery_knowledge``——产 ``KnowledgeEntity(kind=document, source_kind="project_memory")``
+ ``记忆→REFERENCES→项目图谱节点`` 出边（KLINK-01：项目↔知识；可索引 + 关联扩充）。

「项目上下文逻辑隔离」口径（A1 锁定）：复用既有 ``delivery_knowledge`` collection，用新
``source_kind="project_memory"`` + 既有 ``EntityKind.DOCUMENT`` 做逻辑隔离；visibility 隔离由
``space_id`` 维度承载，读侧（Plan 02）按项目 visibility 过滤召回。

降级语义（fail-soft，缺段不缺实体）：
- 记忆不存在 → 返回空列表（warning，绝不抛）；
- 记忆已 ``superseded``（非 active）→ 返回空列表（不摄取已废弃记忆）。

**脱敏不可绕过**：正文经 ``redact_secrets_in_text`` 脱敏后才入图（记忆写时已脱敏，此处双保险）。
观测：``project_memory_rag_normalize_started/completed`` + ``duration_ms`` + 正文长度 + 事件数
（category=sampling, component=knowledge）；日志只记 id/计数/长度，绝不记正文。
"""

from __future__ import annotations

import time

import structlog

from common.logging import redact_secrets_in_text
from knowledge.ingestion import EdgeSpec, IngestionEvent, IngestionRequest
from knowledge.models import EdgeRelation, EntityKind, EntityOrigin

logger = structlog.get_logger(__name__)

__all__ = ["normalize"]


def _doc_title(body: str, fallback: str) -> str:
    """取正文首个 markdown 标题作 title；缺正文降级用 fallback（镜像 artifact source）。"""
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()[:500]
        return stripped[:500]
    return fallback[:500]


async def normalize(request: IngestionRequest) -> list[IngestionEvent]:
    """ProjectMemory UUID → 单 document 事件；记忆不存在或非 active 返回空。"""
    from initiatives.models import ProjectMemory, ProjectMemoryStatus
    from initiatives.services.knowledge_graph import ProjectKnowledgeGraphService

    started = time.perf_counter()
    logger.info(
        "project_memory_rag_normalize_started",
        source_id=request.source_id,
        trigger=request.trigger,
        component="knowledge",
        category="sampling",
    )

    memory = (
        await ProjectMemory.objects.select_related("project", "project__space")
        .filter(id=request.source_id)
        .afirst()
    )
    if memory is None:
        logger.warning(
            "project_memory_rag_source_missing",
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return []
    if memory.status != ProjectMemoryStatus.ACTIVE:
        # 已 superseded 记忆不摄取（active 才是当前态项目上下文）。
        logger.info(
            "project_memory_rag_skipped_non_active",
            memory_id=str(memory.id),
            status=memory.status,
            trigger=request.trigger,
            component="knowledge",
            category="sampling",
        )
        return []

    project = memory.project
    # 脱敏不可绕过：正文入图前经 redact_secrets_in_text（双保险）。
    body = redact_secrets_in_text(memory.content or "")

    # 项目图谱节点（KLINK-01 锚）：记忆→REFERENCES→项目节点出边需目标实体先存在。
    project_node_id = await ProjectKnowledgeGraphService().ensure_project_node(project)

    event = IngestionEvent(
        kind=EntityKind.DOCUMENT,
        origin=EntityOrigin.PROJECT,
        source_kind="project_memory",
        source_id=str(memory.id),
        title=_doc_title(body, f"记忆 {memory.id}"),
        content=body,
        payload={"project_id": str(project.id), "memory_id": str(memory.id)},
        space_id=str(project.space_id) if project.space_id else None,
        repository_id=None,
        event_time=memory.updated_at,
        edges=(EdgeSpec(relation=EdgeRelation.REFERENCES, target_entity_id=project_node_id),),
    )

    logger.info(
        "project_memory_rag_normalize_completed",
        memory_id=str(memory.id),
        content_length=len(body),
        event_count=1,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
        trigger=request.trigger,
        component="knowledge",
        category="sampling",
    )
    return [event]
