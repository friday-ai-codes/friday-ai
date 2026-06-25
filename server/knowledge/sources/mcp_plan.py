"""McpWorkItemTechnicalPlan → [work_item 锚, tech_plan] 双事件 normalizer（Plan 13-03 / INGEST-05）。

- work_item 锚实体：source_id 按 natural key 规则表锁定的三元组拼接
  ``{feishu_project_key}:{work_item_type}:{work_item_id}``，content 为轻量锚
  （name + description；Phase 14 INGEST-04 同 key 重摄为全量快照）；
- tech_plan 实体：content 取 artifact.markdown，payload 摘要自
  plan_body / repository_tasks / feishu_document_url；
- work_item —HAS_PLAN→ tech_plan 出边经 ``generate_entity_id`` 唯一入口派生
  目标 id（exclusive：同 relation 单 target 语义）。

事件顺序锁定：work_item 锚在前（摄取核心阶段 B 统一处理边，两端实体均已持久化，
顺序只影响可读性，但与 PLAN 行为断言保持一致）。
"""

from __future__ import annotations

import structlog

from knowledge.ingestion import EdgeSpec, IngestionEvent, IngestionRequest
from knowledge.models import EdgeRelation, EntityKind, EntityOrigin, generate_entity_id

logger = structlog.get_logger(__name__)

__all__ = ["normalize"]


async def normalize(request: IngestionRequest) -> list[IngestionEvent]:
    """McpWorkItemTechnicalPlan → 双事件；源缺失返回空列表，锚缺料只产出 tech_plan。"""
    from mcp_tools.models import McpWorkItemTechnicalPlan

    artifact = (
        await McpWorkItemTechnicalPlan.objects.select_related("context", "space")
        .filter(id=request.source_id)
        .afirst()
    )
    if artifact is None:
        logger.warning(
            "knowledge_normalize_source_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return []

    project_id = str(artifact.space_id) if artifact.space_id else None
    tech_plan_event = IngestionEvent(
        kind=EntityKind.TECH_PLAN,
        origin=EntityOrigin.MCP,
        source_kind="mcp_technical_plan",
        source_id=str(artifact.id),
        title=artifact.title,
        content=artifact.markdown,
        payload={
            "plan_body": artifact.plan_body,
            "repository_tasks": artifact.repository_tasks,
            "feishu_document_url": artifact.feishu_document_url,
        },
        space_id=project_id,
        repository_id=None,
        event_time=artifact.created_at,
    )

    context = artifact.context
    if context is None:
        # 防御：锚缺料则不建锚（FK 语义下不应发生，但缺锚不应拖垮方案入图）
        logger.warning(
            "knowledge_normalize_anchor_context_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return [tech_plan_event]

    work_item_event = IngestionEvent(
        kind=EntityKind.WORK_ITEM,
        origin=EntityOrigin.MCP,
        source_kind="feishu_work_item",
        # natural key 规则表（knowledge/models.py generate_entity_id docstring）锁定格式
        source_id=f"{artifact.feishu_project_key}:{artifact.work_item_type}:{artifact.work_item_id}",
        title=context.name,
        content=f"{context.name}\n\n{context.description or ''}",
        payload={
            "name": context.name,
            "work_item_status": context.work_item_status,
            "feishu_project_key": artifact.feishu_project_key,
            "work_item_type": artifact.work_item_type,
            "work_item_id": artifact.work_item_id,
        },
        space_id=project_id,
        repository_id=None,
        event_time=artifact.created_at,
        edges=(
            EdgeSpec(
                relation=EdgeRelation.HAS_PLAN,
                target_entity_id=generate_entity_id(
                    "tech_plan", "mcp_technical_plan", str(artifact.id)
                ),
                exclusive=True,
            ),
        ),
    )
    return [work_item_event, tech_plan_event]
