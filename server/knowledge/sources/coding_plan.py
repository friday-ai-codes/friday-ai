"""chat CodingPlan → IngestionEvent normalizer（Plan 13-03 / INGEST-03）。

取材边界（OQ-3 规划定案，T-13-01 防线）：

- content **仅**由 ``title + "\\n\\n" + tech_plan`` 拼成——本模块对 conversation
  下的对话内容零接触面（不 import、不查询），提炼前的用户原文绝不入图；
- 不为 chat 创建 work_item 实体（自然语言需求无稳定 ID，归并是 Phase 14+ 课题），
  因此产出单事件、零边。

hook 只传 ID 契约：触发点只投递 ``IngestionRequest``，本 normalizer 在后台
worker 内按 source_id 重读源模型（select_related 防 async 隐式同步访问）。
"""

from __future__ import annotations

import structlog

from knowledge.ingestion import IngestionEvent, IngestionRequest
from knowledge.models import EntityKind, EntityOrigin

logger = structlog.get_logger(__name__)

__all__ = ["normalize"]


async def normalize(request: IngestionRequest) -> list[IngestionEvent]:
    """CodingPlan → 单 tech_plan 事件；源缺失（已删除场景）返回空列表不 raise。"""
    from chat.models import CodingPlan

    plan = (
        await CodingPlan.objects.select_related("conversation", "conversation__space")
        .filter(id=request.source_id)
        .afirst()
    )
    if plan is None:
        logger.warning(
            "knowledge_normalize_source_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return []

    first_line = plan.tech_plan.splitlines()[0] if plan.tech_plan else ""
    title = plan.title or first_line[:200]
    project_id = str(plan.conversation.space_id) if plan.conversation.space_id else None
    return [
        IngestionEvent(
            kind=EntityKind.TECH_PLAN,
            origin=EntityOrigin.CHAT,
            source_kind="coding_plan",
            source_id=str(plan.id),
            title=title,
            # OQ-3 锁定拼法：title + 空行 + tech_plan，别无其他来源
            content=f"{plan.title}\n\n{plan.tech_plan}",
            payload={
                "title": plan.title,
                "affected_files": plan.affected_files,
                "recommended_repository_ids": plan.recommended_repository_ids,
            },
            space_id=project_id,
            # 多仓方案无单一仓库归属
            repository_id=None,
            event_time=plan.updated_at,
        )
    ]
