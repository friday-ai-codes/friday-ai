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
from delivery.services.event_taxonomy import (
    EVENT_KNOWLEDGE_RECALLING,
    EVENT_REPO_ROUTING,
)
from services.plan_orchestration.protocols import (
    ClarifyProtocol,
    MergeProtocol,
    RecallProtocol,
    ResearchProtocol,
    RouterProtocol,
    SkeletonClarify,
    SkeletonMerge,
    SkeletonRecall,
    SkeletonResearch,
    SkeletonRouter,
)

logger = structlog.get_logger(__name__)

__all__ = ["PlanOrchestrationEngine"]

# 融合验证失败的限次回退上限（CONTEXT 决策：默认 1 次重试，超限落 failed 终态防无限循环）。
# 与 ArchitectMergeAdapter.MAX_MERGE_RETRIES 语义一致；engine 据 adapter 返回的 attempt 判限次。
MAX_MERGE_RETRIES = 1


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
        clarify: ClarifyProtocol | None = None,
    ) -> None:
        # 依赖注入（入口无关）：缺省用骨架实现，38-41 注入真实/mock 替换。
        # engine 不接收任何 workflow/chat IO 对象（保持入口无关）。
        self.session_service = session_service or PlanSessionService()
        self.router = router or SkeletonRouter()
        self.recall = recall or SkeletonRecall()
        self.research = research or SkeletonResearch()
        self.merge = merge or SkeletonMerge()
        self.clarify = clarify or SkeletonClarify()

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
        """**LLM 跨仓拆分 + fail-soft 回退**（DECOMP-01）：需求文本 → 结构化 decomposition。

        取 session.decomposition 既有输入（requirement_text/include_repos），无 work_item
        文本源时回退占位。调 ``agenerate_decomposition_segments`` 用 LLM 把需求跨业务线/
        模块/前后端拆为结构化 ``segments``（list[dict]）；helper best-effort 返回 ``None``
        （LLM 失败/缺 default_model/解析空）时**回退按非空行切分**（list[str]，保持现状
        行为，下游 routing 契约不变）。

        守护：helper 已自包 ``except Exception`` 返回 None（不在此再 try 包裹），
        ``_decompose`` 恒走 ``transition("decomposed")`` —— decompose 任何路径绝不落
        FAILED（RESEARCH Anti-Pattern 1）；始终保留 requirement_text/include_repos
        两契约键（Anti-Pattern 2）；不直接 mutate session.status（只经 transition，
        Anti-Pattern 3 / T-36-03-01）。
        """
        from services.plan_orchestration.decompose_segments import (
            agenerate_decomposition_segments,
        )

        existing = session.decomposition or {}
        requirement_text = existing.get("requirement_text", "")
        if not requirement_text and session.work_item_id is not None:
            requirement_text = await self._work_item_title(session)
        include_repos = existing.get("include_repos", [])

        result = await agenerate_decomposition_segments(
            requirement_text=requirement_text, include_repos=include_repos
        )
        segments: list[Any]
        if result:
            segments = result
        else:
            # fail-soft 回退：LLM 不可用（None/空）→ 按非空行切分（现状 list[str] 行为）
            segments = [line.strip() for line in requirement_text.splitlines() if line.strip()]
            logger.info(
                "plan_decompose_fallback_splitlines",
                category="sampling",
                component="plan_orchestration",
                segment_count=len(segments),
            )
        decomposition: dict[str, Any] = {
            "requirement_text": requirement_text,
            "include_repos": include_repos,
            "segments": segments,
        }
        await self.session_service.transition(session, "decomposed", decomposition=decomposition)

    async def _route(self, session: PlanSession) -> None:
        """路由 stage（ROUTE-01 已接入）：调注入 router 取候选仓 → 落库 → 发事件。

        1. ``result = await self.router.route(session)`` 取候选仓 + confidence（精简 dict）。
        2. 经 ``transition(session, "routed", routing=result)`` 把 result 落
           ``PlanSession.routing`` 并按 §14 routed 行转移 routing → recalling（engine
           不直接写 status，T-36-03-01）。
        3. 产出 §15 ``repo.routing`` trace 事件（payload `{candidates:[{repo_id,
           confidence}]}`，不含 reasoning 等推理细节 INV-5）经 ``_emit_event`` 钩子；
           真实 sink Phase 41 收口。``result`` 经 ``isinstance(result, dict)`` 防御取值
           （与 ``_recall`` 对称：注入/未来 router 返回非 dict 时不在转移已落库后崩 trace）。
        """
        result = await self.router.route(session)
        await self.session_service.transition(session, "routed", routing=result)
        candidates = (result.get("candidates") or []) if isinstance(result, dict) else []
        trace = {
            "candidates": [
                {"repo_id": c.get("repo_id"), "confidence": c.get("confidence")} for c in candidates
            ]
        }
        await self.session_service._emit_event(EVENT_REPO_ROUTING, session, trace)

    async def _recall(self, session: PlanSession) -> None:
        """召回 stage（RECALL-01 已接入）：调注入 recall 取召回上下文 → 落库 → 发事件。

        1. ``result = await self.recall.recall(session)`` 取召回命中（`{hits, query, kinds}`）。
        2. 经 ``transition(session, "recalled", recall_context=hits)`` 把命中列表落
           ``PlanSession.recall_context`` 并按 §14 recalled 行转移 recalling → clarifying
           （engine 不直接写 status，T-36-03-01）。
        3. 产出 §15 ``knowledge.recalling`` trace 事件（payload `{query, kinds, hits}`，
           hits 仅计数、不外泄命中明细 INV-5）经 ``_emit_event`` 钩子；真实 sink Phase 41
           收口。``result`` 防御取值（注入 mock 可能返回精简 dict 或 list）。
        """
        result = await self.recall.recall(session)
        hits = result.get("hits", []) if isinstance(result, dict) else (result or [])
        await self.session_service.transition(session, "recalled", recall_context=hits)
        trace = {
            "query": result.get("query", "") if isinstance(result, dict) else "",
            "kinds": result.get("kinds", []) if isinstance(result, dict) else [],
            "hits": len(hits),
        }
        await self.session_service._emit_event(EVENT_KNOWLEDGE_RECALLING, session, trace)

    async def _clarify(self, session: PlanSession) -> None:
        """澄清 stage（CLARIFY-01 已接入）：调注入 ClarifyProtocol 据判定做 §14 转移。

        1. ``result = await self.clarify.clarify(session)`` 判定是否需澄清（adapter 已建
           pending Clarification + emit clarification.asked 副作用，engine 仅 transition）。
        2. ``needs_clarification`` 真 → ``transition("needs_clarification")``（clarifying→
           clarifying 自挂起，§14「有待澄清」行），**不进 researching**；工作流入口节点据
           pending clarification 挂 waiting_event 等用户答复。
        3. 否（无待澄清/全部已答）→ ``transition("clarified")``（clarifying→researching，
           §14「无待澄清/全部已答」行）。

        engine **绝不直接 mutate session.status**（守 T-36-03-01 纯度守护）；adapter 真实
        实现抛异常时由 advance 通用 except 落 failed（与其他 stage 一致）。
        ``ConcurrentTransitionError`` 沿 ``_research``/``_merge`` 范式视为良性 no-op（防御）。
        """
        from delivery.services.plan_session_service import ConcurrentTransitionError

        result = await self.clarify.clarify(session)
        needs = result.get("needs_clarification") if isinstance(result, dict) else False
        try:
            if needs:
                await self.session_service.transition(session, "needs_clarification")
            else:
                await self.session_service.transition(session, "clarified")
        except ConcurrentTransitionError:
            logger.info("clarify_already_advanced_concurrently", session_id=str(session.id))

    async def _research(self, session: PlanSession) -> None:
        """调研 stage（RESEARCH-01/02/03 已接入）：dispatch 触发 fan-out，barrier 驱动转移。

        1. ``await self.research.dispatch(session)``（39-03 adapter：filter + fan-out + 建
           task + 派容器 + 轻量合成）。
        2. ``amaybe_complete_research``：若所有 RepoResearchTask 已终态（如全为轻量仓 /
           无需深入仓）→ 经 service 推 research_complete（researching→merging）。
        3. 仍有 pending/running 深入仓在途 → ``transition(research_dispatched)``
           （researching 自留等待，§14 fan-out 等待行）；后续由容器回调（39-04
           ``_handle_research_completion`` → ``amaybe_complete_research``）驱动
           research_complete（对齐既有 AICodingNode waiting_event/callback resume 范式）。

        engine **绝不直接 mutate session.status**——只经 ``session_service.transition``
        （T-36-03-01 purity guard）。状态全持久化在 RepoResearchTask/PlanSession，可 resume。
        """
        from delivery.services.plan_session_service import ConcurrentTransitionError
        from services.plan_orchestration.research_aggregation import (
            amaybe_complete_research,
        )

        await self.research.dispatch(session)
        try:
            completed = await amaybe_complete_research(
                session, session_service=self.session_service
            )
            if not completed:
                await self.session_service.transition(session, "research_dispatched")
        except ConcurrentTransitionError:
            # WR-03 良性并发：容器回调侧 barrier 已把 session 推进（research_complete→
            # merging），engine 内存态 from_status=researching 的条件更新命中 0 行 → 视为
            # 成功 no-op。**绝不**让该异常落到 advance 的通用 except → fail（否则 _fail
            # 会把回调正确推进的 merging 错误覆盖回 failed，属状态损坏）。
            logger.info("research_already_advanced_by_barrier", session_id=str(session.id))

    async def _merge(self, session: PlanSession) -> None:
        """融合 stage（MERGE-01/02/03 已接入）：调注入 merge adapter 据结果做 §14 转移。

        三分支（adapter 已落 canonical/ArchitectMerge 副作用，engine 仅 transition）：

        1. ``"passed"`` → ``transition("merged")``（merging→done，§14「融合+validator
           通过 → done」行）。
        2. ``"failed"`` 且 ``attempt < MAX_MERGE_RETRIES`` → 按 ``back_target`` 回退
           （§14「PlanValidator 失败 → clarifying 或 researching 按报告回退重跑」）：
           ``"researching"`` → ``transition("validation_failed_reresearch")``；否则
           ``transition("validation_failed_reclarify")``。
        3. ``"failed"`` 且 ``attempt >= MAX_MERGE_RETRIES`` → ``transition("fail")``
           落 failed 终态（防无限循环，CONTEXT「默认 1 次重试，超限 failed」）。

        engine **绝不直接 mutate session.status**（守 T-36-03-01 纯度守护）；adapter 已
        graceful（不抛），故本 handler 不再吞异常。``result`` 经 ``isinstance`` 防御取值
        （与 ``_route``/``_recall`` 对称）。``ConcurrentTransitionError`` 沿 ``_research``
        范式视为良性 no-op（merging 通常无并发 barrier，但防御性处理）。
        """
        from delivery.services.plan_session_service import ConcurrentTransitionError

        result = await self.merge.merge(session)
        status = result.get("validation_status") if isinstance(result, dict) else None
        attempt = result.get("attempt", 0) if isinstance(result, dict) else 0
        try:
            if status == "passed":
                await self.session_service.transition(session, "merged")
            elif attempt >= MAX_MERGE_RETRIES:
                # 限次回退耗尽：落 failed 终态（防无限循环）
                error = {
                    "stage": str(PlanSessionStatus.MERGING),
                    "reason": "merge_validation_exhausted",
                    "report": result.get("report", {}) if isinstance(result, dict) else {},
                }
                await self.session_service.transition(session, "fail", error=error)
            else:
                back_target = (
                    result.get("back_target", "clarifying")
                    if isinstance(result, dict)
                    else "clarifying"
                )
                if back_target == "researching":
                    await self.session_service.transition(session, "validation_failed_reresearch")
                else:
                    await self.session_service.transition(session, "validation_failed_reclarify")
        except ConcurrentTransitionError:
            # merging 段并发推进良性 no-op（对齐 _research）：绝不让其落到 advance 通用
            # except → fail（否则覆盖并发正确推进的状态，属状态损坏）。
            logger.info("merge_already_advanced_concurrently", session_id=str(session.id))

    async def _work_item_title(self, session: PlanSession) -> str:
        """惰性取关联 work_item.title 作为需求文本回退源（async ORM）。"""
        from delivery.models import WorkItem

        work_item = await WorkItem.objects.filter(id=session.work_item_id).afirst()
        return work_item.title if work_item is not None else ""
