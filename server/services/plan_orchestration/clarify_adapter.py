"""ClarifyAdapter —— clarifying 阶段 HITL 澄清回路真实实现（CLARIFY-01，DOMAIN §6/§14）。

替换骨架 ``SkeletonClarify``：按 **needs-clarification policy** 判定是否需澄清——
需澄清则建 pending ``Clarification`` + emit ``clarification.asked`` + 返回
``{"needs_clarification": True}``（engine 保持 clarifying 挂起，不进 researching）；
否则返回 ``{"needs_clarification": False}``（engine 转移 clarified → researching）。

默认 policy ``default_needs_clarification``（可注入）：routing 无 high/medium 候选 **或**
decomposition 标 ambiguous → 需澄清。Clarification 落库只经 ``ClarificationService``（INV-6）；
emit 经 ``PlanSessionService._emit_event`` best-effort（绝不阻断）。

**async ORM 防裸 lazy-FK**（规避 Phase 38 CR-01 类）：用 ``session_id`` / ``.aexists`` /
``.values`` 标量，绝不裸访问 ``session.work_item`` 等同步 lazy-FK。
"""

from __future__ import annotations

from typing import Any, Callable

import structlog

from delivery.models import PlanSession
from delivery.services import ClarificationService, PlanSessionService
from delivery.services.event_taxonomy import EVENT_CLARIFICATION_ASKED

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
        question = str(
            decomposition.get("ambiguous_hint") or "需求存在歧义，请补充澄清"
        )
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
        """判定是否需澄清；需则建 pending Clarification + emit asked；返回判定 dict。"""
        from delivery.models import Clarification

        # 1. 已有 pending（未答）→ 保持挂起，不重复建（resume 幂等）
        has_pending = await Clarification.objects.filter(
            session_id=session.id, answered_at__isnull=True
        ).aexists()
        if has_pending:
            return {"needs_clarification": True, "pending": True}

        # 2. 无 pending → 跑 policy
        needs, question, affected_task_ids = self.policy(session)
        if not needs:
            return {"needs_clarification": False}

        clar = await self.clarification_service.create_clarification(
            session, question, affected_task_ids
        )
        await self._emit_asked(session, clar, question)
        return {"needs_clarification": True, "clarification_id": str(clar.id)}

    async def _emit_asked(self, session: PlanSession, clar: Any, question: str) -> None:
        """emit clarification.asked（payload {clarification_id, question}），best-effort。"""
        payload = {"clarification_id": str(clar.id), "question": question}
        try:
            await self.session_service._emit_event(
                EVENT_CLARIFICATION_ASKED, session, payload
            )
        except Exception:  # noqa: BLE001 — 事件 best-effort，绝不阻断挂起
            logger.warning(
                "clarification_asked_emit_failed",
                session_id=str(session.id),
                clarification_id=str(clar.id),
            )
