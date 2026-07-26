"""ClarifyAdapter —— clarifying 阶段 HITL 澄清回路真实实现（CLARIFY-01/02，DOMAIN §6/§14）。

替换骨架 ``SkeletonClarify``：**静态 policy 判「要不要问」→ LLM 判「问什么」**——
需澄清（policy needs==True）则调 ``agenerate_clarification_questions`` 产结构化多题，经
``ClarificationService.create_round`` 落多子题轮 + emit ``clarification.asked`` + 返回
``{"needs_clarification": True}``（engine 保持 clarifying 挂起，不进 researching）；不需澄清
返回 ``{"needs_clarification": False}``（engine 转移 clarified → researching）。

**fail-soft 回退（CLARIFY-02）**：LLM 返回 ``[]`` 或内部异常（``agenerate_clarification_questions``
已 best-effort 吞为 ``[]``）→ 回退现状粗单题（经 ``create_round`` 建 1 子题轮），记
``clarification_fallback_coarse_question``，**绝不抛、绝不让 engine.advance 通用 except 落
failed**（INV / T-90-03-02）。P3 起回退统一走结构化 ``create_round`` / ``answer_round``
（process-agnostic，不再用已删除的 legacy ``create_clarification`` / ``answer_clarification``）。

默认 policy ``default_needs_clarification``（可注入）：routing 无 high/medium 候选 **或**
decomposition 标 ambiguous → 需澄清。Clarification 落库只经 ``ClarificationService``（INV-6）；
emit 经 ``ConvergenceSessionService._emit_event`` best-effort（绝不阻断）。

**多轮 HITL 语义（CLARIFY-07，移除 90-03 CR-01 单轮硬限）**：每次 clarify 先按 pending 谓词短路
（``ahas_pending`` 统一兼容旧单题行 + 新结构化子题，T-90-03-04），再以已答轮数 ``round_count`` 决策：
- ``round_count >= _MAX_CLARIFY_ROUNDS``（默认 6）→ 带现有信息继续编排、不再发轮（best-effort log
  ``clarification_round_cap_reached``），防自伤无限挂起 / DoS（T-91-01-02）。
- 否则跑 policy「要不要问」；needs==True 则**带已答轮问答重判**「问什么」——把已答子题答复拼进
  ``agenerate_clarification_questions`` 的 requirement，确保答复改变重判输入、不同题死循环（Pitfall 2 /
  T-91-01-03）。生成非空 → ``create_round(round_no=round_count+1)`` 再发一轮；生成空时首轮 fail-soft 回退
  粗单题、多轮则视为信息足够放行 researching。

**async ORM 防裸 lazy-FK**（规避 Phase 38 CR-01 类）：用 ``session_id`` / ``.aexists`` /
``.values`` 标量，绝不裸访问 ``session.work_item`` 等同步 lazy-FK。
"""

from __future__ import annotations

from typing import Any, Callable

import structlog

from delivery.models import ConvergenceSession
from delivery.services import ClarificationService, ConvergenceSessionService
from delivery.services.event_taxonomy import EVENT_CLARIFICATION_ASKED
from services.process_runtime.clarification_questions import (
    agenerate_clarification_questions,
)

logger = structlog.get_logger(__name__)

__all__ = ["default_needs_clarification", "ClarifyAdapter"]

# needs-clarification policy：(session) -> (needs: bool, question: str, affected_task_ids: list)
NeedsClarificationPolicy = Callable[[ConvergenceSession], "tuple[bool, str, list]"]

# 可选的确定性问题组装器：(session, round_count) -> questions。返回非空则**取代** LLM 生成
# （feature list 强制确认场景用），返回空则回落既有 LLM 路径。
QuestionBuilder = Callable[..., "list[dict[str, Any]]"]

# 高/中置信集合（routing 候选有任一命中即视为可路由，无需澄清）
_CONFIDENT = {"high", "medium"}

# 多轮澄清上界（CLARIFY-07 / CONTEXT D Discretion，须 ≥5）。较宽松上界，实际极少触顶；
# 超界带现有信息继续编排、不再发轮，兜底防自伤无限挂起 / DoS（T-91-01-02）。
_MAX_CLARIFY_ROUNDS = 6


def default_needs_clarification(session: ConvergenceSession) -> tuple[bool, str, list]:
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
        session_service: ConvergenceSessionService | None = None,
        question_builder: QuestionBuilder | None = None,
    ) -> None:
        self.policy = policy or default_needs_clarification
        self.clarification_service = clarification_service or ClarificationService()
        self.session_service = session_service or ConvergenceSessionService()
        # None（默认）时行为与既有逐字一致：问什么全由 LLM 生成。
        self.question_builder = question_builder

    async def clarify(self, session: ConvergenceSession) -> dict:
        """多轮判定是否需澄清；需则带已答重判 LLM 产多题经 create_round 落库（CLARIFY-07）。"""
        from delivery.models import Clarification

        # 1. 已有 pending（未答）→ 保持挂起，不重复建（resume 幂等）。pending 判定收口到
        #    service 统一谓词 ahas_pending（兼容旧单题行 + 新结构化子题，T-90-03-04）。
        if await self.clarification_service.ahas_pending(session.id):
            return {"needs_clarification": True, "pending": True}

        # 2. 已答轮计数 + 上界兜底（CLARIFY-07，移除 CR-01 单轮 aexists 硬限）：达上界则带现有
        #    信息继续编排、不再发轮，防自伤无限挂起 / DoS（T-91-01-02）。日志仅记计数标量
        #    （不内联澄清正文，T-91-01-04）。
        round_count = await Clarification.objects.filter(session_id=session.id).acount()
        if round_count >= _MAX_CLARIFY_ROUNDS:
            logger.info(
                "clarification_round_cap_reached",
                category="sampling",
                component="process_runtime",
                session_id=str(session.id),
                round_count=round_count,
            )
            return {"needs_clarification": False}

        # 3. policy 判「要不要问」（答后信号未必变，故必须靠步骤 4 重判吃答案 + 上界兜底，而非
        #    单轮短路，否则同信号反复追问 = 无限挂起）。
        needs, question, _affected = self.policy(session)
        if not needs:
            return {"needs_clarification": False}

        # 3.5 确定性问题组装（feature list 强制确认）：builder 非空且产出非空时**取代** LLM
        #     生成——「确认关联仓库」这类问题不能由 LLM 决定问不问。builder 只在首轮产出
        #     （自身按 round_count 短路），故后续轮次自然回落下面的 LLM 重判路径，不会同题
        #     死循环。builder 异常 best-effort 吞掉，退回 LLM 路径（绝不阻断编排）。
        if self.question_builder is not None:
            try:
                built = self.question_builder(session, round_count=round_count)
            except Exception as exc:  # noqa: BLE001 — 组装失败退回 LLM 路径
                logger.warning(
                    "clarification_question_builder_failed",
                    category="sampling",
                    component="process_runtime",
                    session_id=str(session.id),
                    error=str(exc),
                )
                built = []
            if built:
                clar = await self.clarification_service.create_round(
                    session, built, origin_repo=None, round_no=round_count + 1
                )
                if clar is None:
                    return {"needs_clarification": False}
                await self._emit_asked(session, clar, question)
                return {"needs_clarification": True, "clarification_id": str(clar.id)}

        # 4. 带已答重判「问什么」：把已答轮问答喂进生成输入（答复改变重判输入，防同题死循环
        #    Pitfall 2 / T-91-01-03）。生成器 best-effort（lazy import SDK + 吞异常返回 []，绝不抛）。
        requirement = ""
        if isinstance(session.decomposition, dict):
            requirement = str(session.decomposition.get("requirement_text", "") or "")
        if round_count > 0:
            prior = await self._collect_prior_answers(session.id)
            if prior:
                requirement = (
                    f"{requirement}\n\n## 已澄清（请勿重复追问，据此判断是否仍需补充）\n{prior}"
                )
        questions = await agenerate_clarification_questions(
            requirement=requirement,
            routing=session.routing if isinstance(session.routing, dict) else None,
            recall_hits=(
                session.recall_context if isinstance(session.recall_context, list) else None
            ),
        )
        if questions:
            # 重判仍需澄清 → 经 create_round 落结构化多子题轮（INV-6 唯一写入入口），round_no 递增。
            clar = await self.clarification_service.create_round(
                session, questions, origin_repo=None, round_no=round_count + 1
            )
            # questions 非空 → create_round 不触发空问题守护（不会返回 None）；防御性 narrow：
            # 万一为 None 则放行不挂起（绝不让无子题空轮恒判 pending 无限挂起，WR-02 精神）。
            if clar is None:
                return {"needs_clarification": False}
            await self._emit_asked(session, clar, question)
            return {"needs_clarification": True, "clarification_id": str(clar.id)}

        # 5. 生成空（含内部异常已吞为 []）：
        #    - 首轮（round_count==0）→ fail-soft 回退现状粗单题（经 create_round 建 1 子题轮），
        #      绝不抛、绝不让 engine.advance 通用 except 落 failed（T-90-03-02）。
        #    - 多轮（已答 ≥1 轮）→ 重判信息足够，放行 researching、不再发轮（CLARIFY-07）。
        if round_count == 0:
            logger.info(
                "clarification_fallback_coarse_question",
                category="sampling",
                component="process_runtime",
                session_id=str(session.id),
            )
            clar = await self.clarification_service.create_round(
                session,
                [{"question": question, "type": "single", "options": [], "recommended": []}],
                round_no=round_count + 1,
            )
            # 粗问题非空 → create_round 不触发空轮守护；防御性 narrow：万一 None 则放行不挂起。
            if clar is None:
                return {"needs_clarification": False}
            await self._emit_asked(session, clar, question)
            return {"needs_clarification": True, "clarification_id": str(clar.id)}
        return {"needs_clarification": False}

    async def _collect_prior_answers(self, session_id: Any) -> str:
        """读已答子题答复组装为重判文本（喂进生成 prompt，防同题死循环 Pitfall 2）。

        async 防裸 lazy-FK：用 ``session_id`` 标量 + ``.values`` 取标量字段，绝不裸访问 FK。
        仅用于喂 LLM 重判输入，**不写日志**（澄清正文不内联日志，T-91-01-04）。
        """
        from delivery.models import ClarificationQuestion

        rows = [
            row
            async for row in ClarificationQuestion.objects.filter(
                clarification__session_id=session_id, answered_at__isnull=False
            )
            .order_by("clarification__round_no", "order")
            .values("question", "selected", "freeform_text")
        ]
        lines: list[str] = []
        for row in rows:
            selected = row.get("selected")
            freeform = str(row.get("freeform_text") or "").strip()
            parts: list[str] = []
            if selected not in (None, "", [], {}):
                if isinstance(selected, (list, tuple)):
                    parts.append("、".join(str(s) for s in selected))
                else:
                    parts.append(str(selected))
            if freeform:
                parts.append(freeform)
            answer_text = "；".join(parts) if parts else "(无答复)"
            lines.append(f"- {row.get('question', '')}：{answer_text}")
        return "\n".join(lines)

    async def _emit_asked(self, session: ConvergenceSession, clar: Any, question: str) -> None:
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
