"""PlanOrchestrationEngine —— 可复用的方案编排状态推进器（ORCH-01）。

`ai_plan_research` 编排的引擎抽象：一个**状态驱动 step 推进器**，工作流与 Chat
共用同一底层（入口无关——engine 不耦合任何 workflow/chat IO，只接收 ``PlanSession``
+ 可注入 stage 依赖）。`advance(session)` 按 ``session.status`` 分派到对应 stage
handler，handler 完成后**经 ``PlanSessionService.transition`` 驱动转移**（engine
绝不直接 mutate ``session.status``，守 36-02 INV-6 守护，T-36-03-01）。

状态从 DB 行 resume（advance 按持久化 status 续推，不依赖内存态，T-36-03-03）。
本 phase 仅 ``_decompose`` 做最小真实实现；其余 stage handler 调注入依赖，骨架默认
实现显式 ``NotImplementedError``（带接入 phase TODO，38/39/40/41 逐步替换）。
"""

from __future__ import annotations

from typing import Any

import structlog

from delivery.models import PlanSession, PlanSessionStatus
from delivery.services import PlanSessionService

from services.plan_orchestration.protocols import (
    MergeProtocol,
    RecallProtocol,
    ResearchProtocol,
    RouterProtocol,
    SkeletonMerge,
    SkeletonRecall,
    SkeletonResearch,
    SkeletonRouter,
)

logger = structlog.get_logger(__name__)

__all__ = ["PlanOrchestrationEngine"]


class PlanOrchestrationEngine:
    """状态驱动的方案编排推进器（入口无关 + 可注入依赖）。"""

    def __init__(
        self,
        *,
        session_service: PlanSessionService | None = None,
        router: RouterProtocol | None = None,
        recall: RecallProtocol | None = None,
        research: ResearchProtocol | None = None,
        merge: MergeProtocol | None = None,
    ) -> None:
        # 依赖注入（入口无关）：缺省用骨架实现，38-41 注入真实/mock 替换。
        # engine 不接收任何 workflow/chat IO 对象（保持入口无关）。
        self.session_service = session_service or PlanSessionService()
        self.router = router or SkeletonRouter()
        self.recall = recall or SkeletonRecall()
        self.research = research or SkeletonResearch()
        self.merge = merge or SkeletonMerge()

    async def advance(self, session: PlanSession) -> PlanSession:
        """按 ``session.status`` 分派 stage handler 推进一步（状态驱动 resume）。

        终态（done/failed）直接返回（no-op）。stage 内不可恢复异常 → 经 transition
        落 ``failed``（结构化 error 含 stage/异常类型/消息），不向上抛 raw 异常。
        **例外**：骨架 stage 主动抛的 ``NotImplementedError`` 原样上抛（便于 38-41
        开发期暴露未接入，不被吞成 failed）。
        """
        status = session.status
        handlers = {
            PlanSessionStatus.DECOMPOSING: self._decompose,
            PlanSessionStatus.ROUTING: self._route,
            PlanSessionStatus.RECALLING: self._recall,
            PlanSessionStatus.CLARIFYING: self._clarify,
            PlanSessionStatus.RESEARCHING: self._research,
            PlanSessionStatus.MERGING: self._merge,
        }
        handler = handlers.get(status)
        if handler is None:
            # done / failed 终态：no-op，不转移
            return session

        try:
            await handler(session)
        except NotImplementedError:
            # 骨架 stage 未接入：原样上抛，不吞成 failed（开发期显式暴露）
            raise
        except Exception as exc:
            error = {
                "stage": str(status),
                "exception": type(exc).__name__,
                "message": str(exc),
            }
            await self.session_service.transition(session, "fail", error=error)
        return session

    async def _decompose(self, session: PlanSession) -> None:
        """**最小真实实现**：拆需求文本 + include_repos → 结构化 decomposition。

        本 phase 取 session.decomposition 既有输入（requirement_text/include_repos），
        无 work_item 文本源时回退占位。segments 做最小切分（按非空行）。
        TODO(Phase 38+)：真实业务线/模块/前后端拆分。
        """
        existing = session.decomposition or {}
        requirement_text = existing.get("requirement_text", "")
        if not requirement_text and session.work_item_id is not None:
            requirement_text = await self._work_item_title(session)
        include_repos = existing.get("include_repos", [])
        segments = [line.strip() for line in requirement_text.splitlines() if line.strip()]
        decomposition: dict[str, Any] = {
            "requirement_text": requirement_text,
            "include_repos": include_repos,
            "segments": segments,
        }
        await self.session_service.transition(session, "decomposed", decomposition=decomposition)

    async def _route(self, session: PlanSession) -> None:
        """路由 stage：调注入 router → transition routed（→ recalling）。

        TODO(Phase 38)：RepoRouterV2 真实路由（候选仓 + confidence 写 decomposition）。
        """
        await self.router.route(session)
        await self.session_service.transition(session, "routed")

    async def _recall(self, session: PlanSession) -> None:
        """召回 stage：调注入 recall → transition recalled（→ clarifying）。

        TODO(Phase 38)：DeliveryKnowledgeSearchService 历史/相似召回上下文注入。
        """
        await self.recall.recall(session)
        await self.session_service.transition(session, "recalled")

    async def _clarify(self, session: PlanSession) -> None:
        """澄清 stage：本 phase 无澄清逻辑，最小 pass-through → researching。

        TODO(Phase 41)：Clarification 回路（有待澄清则 needs_clarification 自挂起）。
        """
        await self.session_service.transition(session, "clarified")

    async def _research(self, session: PlanSession) -> None:
        """调研 stage：调注入 research → transition research_complete（→ merging）。

        本 phase 简化为 dispatch 后直接 research_complete；真实 fan-out/barrier 留 Phase 39。
        TODO(Phase 39)：filter_then_container fan-out + BarrierManager。
        """
        await self.research.dispatch(session)
        await self.session_service.transition(session, "research_complete")

    async def _merge(self, session: PlanSession) -> None:
        """融合 stage：调注入 merge → transition merged（→ done）。

        TODO(Phase 40)：架构师融合 + PlanValidator（失败按报告回退 clarifying/researching）。
        """
        await self.merge.merge(session)
        await self.session_service.transition(session, "merged")

    async def _work_item_title(self, session: PlanSession) -> str:
        """惰性取关联 work_item.title 作为需求文本回退源（async ORM）。"""
        from delivery.models import WorkItem

        work_item = await WorkItem.objects.filter(id=session.work_item_id).afirst()
        return work_item.title if work_item is not None else ""
