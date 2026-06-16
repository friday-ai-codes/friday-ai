"""ClarificationService —— Clarification 唯一写入入口（CLARIFY-01，INV-6）。

承载 HITL 澄清回路的落库与状态变更（DOMAIN §6/§14），对齐 ``PlanSessionService`` /
``ResearchService`` 单一写入范式：

- ``create_clarification``：建 pending ``Clarification``（``answered_at=None``）+ 设
  ``affected_partials`` M2M（回答后须重跑的 task）。
- ``answer_clarification``：条件更新 ``answer`` / ``answered_at``（仅 ``answered_at IS NULL``
  可答，重复答幂等 no-op，不二次覆盖首答）；对 ``affected_partials`` 对应
  ``RepoResearchTask`` 经 ``ResearchService.mark_stale`` 置 stale 重跑（§14 仅 affected
  重跑，其余 partial 复用）；无 affected_partials → 纯解除挂起（不触任何 task）。

INV-6：Clarification 落库/状态变更仅经本 service（grep 守护断言无旁路
``Clarification.objects.create`` / ``.save`` 出现在 service 外）。所有 ORM 写经
``sync_to_async`` 桥接，async 上下文禁裸 lazy-FK（用 ``*_id`` / ``.values_list``，
规避 Phase 38 CR-01 类）。
"""

from __future__ import annotations

from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from delivery.models import Clarification
from delivery.services.research_service import ResearchService

logger = structlog.get_logger(__name__)

__all__ = ["ClarificationService"]


class ClarificationService:
    """Clarification 落库/状态变更唯一入口（INV-6 精神）。"""

    def __init__(self, *, research_service: ResearchService | None = None) -> None:
        self.research_service = research_service or ResearchService()

    async def create_clarification(
        self, session: Any, question: str, affected_task_ids: list | None = None
    ) -> Clarification:
        """建 pending Clarification（answered_at=None）+ 设 affected_partials M2M。

        ``affected_task_ids`` 为 RepoResearchTask id 列表（回答后须重跑的 task），
        空则不关联（纯挂起后全量按现状继续）。
        """
        return await self._create_sync(session, question, affected_task_ids or [])

    @sync_to_async
    def _create_sync(
        self, session: Any, question: str, affected_task_ids: list
    ) -> Clarification:
        clar = Clarification.objects.create(session=session, question=question)
        if affected_task_ids:
            clar.affected_partials.set(affected_task_ids)
        return clar

    async def answer_clarification(self, clarification: Clarification, answer: str) -> Clarification:
        """写 answer/answered_at（幂等条件更新）+ 仅 affected_partials 经 stale 重跑。

        条件更新前置 ``answered_at IS NULL``（镜像 PlanSessionService 条件更新断言风格）：
        重复答幂等 no-op（不二次覆盖首答、不重复 stale）。命中首答后取 affected_partials
        对应 task → ``ResearchService.mark_stale``（仅触指定 task，绝不动其他）；无
        affected_partials → 纯解除挂起（不触任何 task）。
        """
        affected_ids = await self._answer_sync(clarification, answer)
        if affected_ids:
            await self.research_service.mark_stale(affected_ids)
        return clarification

    @sync_to_async
    def _answer_sync(self, clarification: Clarification, answer: str) -> list:
        now = timezone.now()
        updated = Clarification.objects.filter(
            id=clarification.id, answered_at__isnull=True
        ).update(answer=answer, answered_at=now)
        if updated != 1:
            # 幂等 no-op：已答，不二次覆盖首答、不重复 stale
            logger.info(
                "clarification_answer_noop_already_answered",
                clarification_id=str(clarification.id),
            )
            return []
        clarification.answer = answer
        clarification.answered_at = now
        # affected_partials 对应 task id（标量列表，不裸 lazy-FK）
        return list(clarification.affected_partials.values_list("id", flat=True))
