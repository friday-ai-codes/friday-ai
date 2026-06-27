"""ClarifyAdapter —— clarifying 阶段 HITL 澄清回路真实实现（CLARIFY-01/02，DOMAIN §6/§14）。

替换骨架 ``SkeletonClarify``：**静态 policy 判「要不要问」→ LLM 判「问什么」**——
需澄清（policy needs==True）则调 ``agenerate_clarification_questions`` 产结构化多题，经
``ClarificationService.create_round`` 落多子题轮 + emit ``clarification.asked`` + 返回
``{"needs_clarification": True}``（engine 保持 clarifying 挂起，不进 researching）；不需澄清
返回 ``{"needs_clarification": False}``（engine 转移 clarified → researching）。

**fail-soft 回退（CLARIFY-02）**：LLM 返回 ``[]`` 或内部异常（``agenerate_clarification_questions``
已 best-effort 吞为 ``[]``）→ 回退现状粗单题（经 ``create_clarification`` 建单题行），记
``clarification_fallback_coarse_question``，**绝不抛、绝不让 engine.advance 通用 except 落
failed**（INV / T-90-03-02）。回退用 legacy 单题行（无子题）与 legacy ``answer_clarification``
作答路径配套，保 CR-01 单轮短路零回归。

默认 policy ``default_needs_clarification``（可注入）：routing 无 high/medium 候选 **或**
decomposition 标 ambiguous → 需澄清。Clarification 落库只经 ``ClarificationService``（INV-6）；
emit 经 ``PlanSessionService._emit_event`` best-effort（绝不阻断）。

**单轮 HITL 语义（CR-01）**：policy 仅在「本 session 尚无任何 Clarification」（首轮）时跑。
若已存在 Clarification 轮且无 pending → 视为澄清满足、直接放行 researching（§14「全部已答 →
researching」），**不再重跑静态 policy**——否则因 routing/decomposition 信号答后不变会反复追问、
永远离不开 clarifying（无限挂起）。pending 判定收口到 ``ClarificationService.ahas_pending``
统一谓词（兼容旧单题行 + 新结构化子题），避免逻辑漂移（T-90-03-04）。

**async ORM 防裸 lazy-FK**（规避 Phase 38 CR-01 类）：用 ``session_id`` / ``.aexists`` /
``.values`` 标量，绝不裸访问 ``session.work_item`` 等同步 lazy-FK。
"""

from __future__ import annotations

from typing import Any, Callable

import structlog

from delivery.models import PlanSession
from delivery.services import ClarificationService, PlanSessionService
from delivery.services.event_taxonomy import EVENT_CLARIFICATION_ASKED
from services.plan_orchestration.clarification_questions import (
    agenerate_clarification_questions,
)

logger = structlog.get_logger(__name__)

__all__ = ["default_needs_clarification", "ClarifyAdapter"]

# needs-clarification policy：(session) -> (needs: bool, question: str, affected_task_ids: list)
NeedsClarificationPolicy = Callable[[PlanSession], "tuple[bool, str, list]"]

# 高/中置信集合（routing 候选有任一命中即视为可路由，无需澄清）
_CONFIDENT = {"high", "medium"}


def default_needs_clarification(session: PlanSession) -> tuple[bool, str, list]:
    """默认 needs-clarification policy（CONTEXT Claude's Discretion，可注入替换）。

    判定规则：
    - routing 候选中无任一 confidence ∈ {high, medium} → 需澄清（请补充涉及的仓库/模块）。
    - decomposition 标 ``ambiguous`` 真 → 需澄清（取 decomposition 提示）。
    - 否则不需澄清。

    affected_task_ids 默认空——澄清答复后由 answer 端决定影响面（空表示纯解除挂起后
    全量按现状继续）。
    """
    routing = session.routing if isinstance(session.routing, dict) else {}
    candidates = routing.get("candidates", []) or []
    has_confident = any(
        isinstance(c, dict) and (c.get("confidence") or "").lower() in _CONFIDENT
        for c in candidates
    )
    if not has_confident:
        return True, "未能高/中置信路由到候选仓，请补充涉及的仓库/模块", []

    decomposition = session.decomposition if isinstance(session.decomposition, dict) else {}
    if decomposition.get("ambiguous"):
        question = str(decomposition.get("ambiguous_hint") or "需求存在歧义，请补充澄清")
        return True, question, []

    return False, "", []


class ClarifyAdapter:
    """澄清 stage 依赖真实实现（满足 ClarifyProtocol，CLARIFY-01）。"""

    def __init__(
        self,
        *,
        policy: NeedsClarificationPolicy | None = None,
        clarification_service: ClarificationService | None = None,
        session_service: PlanSessionService | None = None,
    ) -> None:
        self.policy = policy or default_needs_clarification
        self.clarification_service = clarification_service or ClarificationService()
        self.session_service = session_service or PlanSessionService()

    async def clarify(self, session: PlanSession) -> dict:
        """判定是否需澄清；需则 LLM 产多题经 create_round 落库（[]→fail-soft 回退单题）。"""
        from delivery.models import Clarification

        # 1. 已有 pending（未答）→ 保持挂起，不重复建（resume 幂等）。pending 判定收口到
        #    service 统一谓词 ahas_pending（兼容旧单题行 + 新结构化子题，T-90-03-04）。
        if await self.clarification_service.ahas_pending(session.id):
            return {"needs_clarification": True, "pending": True}

        # 2. §14「全部已答 → researching」单轮 HITL 语义（CR-01 无限挂起修复）：
        #    本 session 已存在 Clarification 轮且经步骤 1 确认当前无 pending —— 说明一轮澄清
        #    已完成。此时直接放行进 researching，**不再重跑静态 policy**。默认 policy 的判定
        #    信号（routing 无 high/medium、decomposition.ambiguous）不因用户答复而改变，若每次
        #    答后重跑 policy 仍判「需澄清」便会反复新建 Clarification → 永远离不开 clarifying，
        #    违反 §14「全部已答 → researching」。已答即视为澄清满足，放行下游。
        if await Clarification.objects.filter(session_id=session.id).aexists():
            return {"needs_clarification": False}

        # 3. 首轮（本 session 尚无任何 Clarification）→ 静态 policy 判「要不要问」
        needs, question, affected_task_ids = self.policy(session)
        if not needs:
            return {"needs_clarification": False}

        # 静态 policy 判「要问」后，LLM 判「问什么」：基于需求 + 路由候选 + 召回上下文产出
        # 结构化多题（best-effort，生成器已 lazy import SDK + 吞异常返回 []，绝不抛）。
        requirement = ""
        if isinstance(session.decomposition, dict):
            requirement = str(session.decomposition.get("requirement_text", "") or "")
        questions = await agenerate_clarification_questions(
            requirement=requirement,
            routing=session.routing if isinstance(session.routing, dict) else None,
            recall_hits=(
                session.recall_context if isinstance(session.recall_context, list) else None
            ),
        )
        if questions:
            # LLM 产多题 → 经 create_round 落结构化多子题轮（INV-6 唯一写入入口）。
            clar = await self.clarification_service.create_round(
                session, questions, origin_repo=None
            )
        else:
            # fail-soft：LLM 返回 []（含内部异常已吞）→ 回退现状粗单题（legacy 单题行），
            # 绝不抛、绝不让 engine.advance 通用 except 落 failed（T-90-03-02）。
            logger.info(
                "clarification_fallback_coarse_question",
                category="sampling",
                component="plan_orchestration",
                session_id=str(session.id),
            )
            clar = await self.clarification_service.create_clarification(
                session, question, affected_task_ids
            )
        await self._emit_asked(session, clar, question)
        return {"needs_clarification": True, "clarification_id": str(clar.id)}

    async def _emit_asked(self, session: PlanSession, clar: Any, question: str) -> None:
        """emit clarification.asked（payload {clarification_id, question}），best-effort。"""
        payload = {"clarification_id": str(clar.id), "question": question}
        try:
            await self.session_service._emit_event(EVENT_CLARIFICATION_ASKED, session, payload)
        except Exception:  # noqa: BLE001 — 事件 best-effort，绝不阻断挂起
            logger.warning(
                "clarification_asked_emit_failed",
                session_id=str(session.id),
                clarification_id=str(clar.id),
            )
