"""ClarificationService —— Clarification 唯一写入入口（CLARIFY-01，INV-6）。

承载 HITL 澄清回路的落库与状态变更（DOMAIN §6/§14），对齐 ``PlanSessionService`` /
``ResearchService`` 单一写入范式：

- ``create_clarification``：建 pending ``Clarification``（``answered_at=None``）+ 设
  ``affected_partials`` M2M（回答后须重跑的 task）。
- ``answer_clarification``：条件更新 ``answer`` / ``answered_at``（仅 ``answered_at IS NULL``
  可答，重复答幂等 no-op，不二次覆盖首答）；对 ``affected_partials`` 对应
  ``RepoResearchTask`` 经 ``ResearchService.mark_stale`` 置 stale 重跑（§14 仅 affected
  重跑，其余 partial 复用）；无 affected_partials → 纯解除挂起（不触任何 task）。

结构化澄清（CLARIFY-01，轮次容器 + 多子题）唯一写入入口：

- ``create_round``：建 1 容器 + N 个 ``ClarificationQuestion`` 子题（``bulk_create``）。
- ``answer_round``：按题幂等作答 + 作答时一次性定格 ``recommendation_adopted`` 采纳信号
  （server 端计算，绝不接受调用方传入）。
- ``ahas_pending``：统一 pending 谓词，兼容旧单题行与新结构化子题两形态。

INV-6：Clarification / ClarificationQuestion 落库/状态变更仅经本 service（grep 守护断言无旁路
``Clarification.objects.create`` / ``.save`` 出现在 service 外）。所有 ORM 写经
``sync_to_async`` 桥接，async 上下文禁裸 lazy-FK（用 ``*_id`` / ``.values_list``，
规避 Phase 38 CR-01 类）。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from delivery.models import Clarification, ClarificationQuestion
from delivery.services.event_taxonomy import EVENT_CLARIFICATION_ANSWERED
from delivery.services.research_service import ResearchService

logger = structlog.get_logger(__name__)

__all__ = ["ClarificationService"]


class ClarificationService:
    """Clarification 落库/状态变更唯一入口（INV-6 精神）。"""

    def __init__(
        self,
        *,
        research_service: ResearchService | None = None,
        session_service: Any = None,
    ) -> None:
        self.research_service = research_service or ResearchService()
        # 延迟默认构造避免 import 环（PlanSessionService 同 app）
        if session_service is None:
            from delivery.services.plan_session_service import PlanSessionService

            session_service = PlanSessionService()
        self.session_service = session_service

    async def create_clarification(
        self, session: Any, question: str, affected_task_ids: list | None = None
    ) -> Clarification:
        """建 pending Clarification（answered_at=None）+ 设 affected_partials M2M。

        ``affected_task_ids`` 为 RepoResearchTask id 列表（回答后须重跑的 task），
        空则不关联（纯挂起后全量按现状继续）。
        """
        return await self._create_sync(session, question, affected_task_ids or [])

    @sync_to_async
    def _create_sync(self, session: Any, question: str, affected_task_ids: list) -> Clarification:
        clar = Clarification.objects.create(session=session, question=question)
        if affected_task_ids:
            clar.affected_partials.set(affected_task_ids)
        return clar

    async def answer_clarification(
        self, clarification: Clarification, answer: str
    ) -> Clarification:
        """写 answer/answered_at（幂等条件更新）+ 仅 affected_partials 经 stale 重跑。

        条件更新前置 ``answered_at IS NULL``（镜像 PlanSessionService 条件更新断言风格）：
        重复答幂等 no-op（不二次覆盖首答、不重复 stale、不重复 emit）。命中首答后取
        affected_partials 对应 task → ``ResearchService.mark_stale``（仅触指定 task，绝不动
        其他）+ emit ``clarification.answered``（best-effort）；无 affected_partials → 纯解除
        挂起（不触任何 task）但仍 emit answered。
        """
        answered, affected_ids = await self._answer_sync(clarification, answer)
        if not answered:
            return clarification
        if affected_ids:
            await self.research_service.mark_stale(affected_ids)
        await self._emit_answered(clarification, answer, affected_ids)
        return clarification

    @sync_to_async
    def _answer_sync(self, clarification: Clarification, answer: str) -> tuple[bool, list]:
        now = timezone.now()
        updated = Clarification.objects.filter(
            id=clarification.id, answered_at__isnull=True
        ).update(answer=answer, answered_at=now)
        if updated != 1:
            # 幂等 no-op：已答，不二次覆盖首答、不重复 stale/emit
            logger.info(
                "clarification_answer_noop_already_answered",
                clarification_id=str(clarification.id),
            )
            return False, []
        clarification.answer = answer
        clarification.answered_at = now
        # affected_partials 对应 task id（标量列表，不裸 lazy-FK）
        return True, list(clarification.affected_partials.values_list("id", flat=True))

    async def _emit_answered(
        self, clarification: Clarification, answer: str, affected_ids: list
    ) -> None:
        """emit clarification.answered（payload {clarification_id, answer, affected_partials}），best-effort。

        async 安全：经 ``session_id`` 取 PlanSession（不裸 lazy-FK ``clarification.session``，
        规避 Phase 38 CR-01 类）。事件持久化失败不阻断 answer 主流程。
        """
        from delivery.models import PlanSession

        session = await PlanSession.objects.filter(id=clarification.session_id).afirst()
        if session is None:
            return
        payload = {
            "clarification_id": str(clarification.id),
            "answer": answer,
            "affected_partials": [str(tid) for tid in affected_ids],
        }
        try:
            await self.session_service._emit_event(EVENT_CLARIFICATION_ANSWERED, session, payload)
        except Exception:  # noqa: BLE001 — 事件 best-effort，绝不阻断 answer
            logger.warning(
                "clarification_answered_emit_failed",
                clarification_id=str(clarification.id),
            )

    # ── CLARIFY-01 结构化澄清「轮次容器 + 多子题」写入入口（INV-6） ──────────────

    async def create_round(
        self,
        session: Any,
        questions: list[dict[str, Any]],
        *,
        origin_repo: str | None = None,
        round_no: int | None = None,
        plan_version_id: Any = None,
    ) -> Clarification:
        """建 1 个澄清轮次容器 + N 个 ClarificationQuestion 子题（结构化澄清唯一写入入口）。

        ``questions`` 为归一后的问题列表（见 ``normalize_clarification_questions`` 形态：
        ``{question, type, options, recommended}``）。容器以 ``question=""`` 占位保旧 NOT NULL
        列、真身在子题；子题按列表顺序 ``order`` 0-based 递增，``qtype`` 取 ``type``（缺省
        single），可携 ``origin_repo``（CLARIFY-03 透传）。全部写入只经本 service（INV-6），
        子题经 ``bulk_create`` 在 ``sync_to_async`` 同步块内一次性落库。
        """
        started = time.perf_counter()
        clar = await self._create_round_sync(
            session, questions, origin_repo, round_no, plan_version_id
        )
        self._safe_log(
            "clarification_round_created",
            category="caller",
            component="delivery",
            clarification_id=str(clar.id),
            session_id=str(getattr(session, "id", "")),
            question_count=len(questions),
            round_no=round_no,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return clar

    @sync_to_async
    def _create_round_sync(
        self,
        session: Any,
        questions: list[dict[str, Any]],
        origin_repo: str | None,
        round_no: int | None,
        plan_version_id: Any,
    ) -> Clarification:
        clar = Clarification.objects.create(
            session=session,
            question="",  # 占位保旧 NOT NULL 列；结构化真身在子题
            origin_repo=origin_repo,
            round_no=round_no,
            plan_version_id=plan_version_id,
            container_status="pending",
        )
        children = [
            ClarificationQuestion(
                clarification=clar,
                order=idx,
                question=str(q.get("question", "")),
                qtype=str(q.get("type", "single")),
                options=q.get("options") or [],
                recommended=q.get("recommended") if q.get("recommended") is not None else [],
                origin_repo=origin_repo,
            )
            for idx, q in enumerate(questions)
        ]
        if children:
            ClarificationQuestion.objects.bulk_create(children)
        return clar

    async def answer_round(self, round_or_id: Any, answers: list[dict[str, Any]]) -> Clarification:
        """按题作答 + 作答时一次性定格 ``recommendation_adopted``（采纳信号）。

        ``answers`` 为 ``[{question_id, selected, freeform_text}]``。每题幂等条件更新
        （仅 ``answered_at IS NULL`` 可答，重复作答 no-op 不二次覆盖首答）。采纳信号
        **只在 server 端作答时计算、绝不接受调用方传入**（T-90-02-02）：

        - single：``selected == recommended[0]``（recommended 存 ``[str]`` 或 ``str``）→ True/False。
        - multi：``set(selected) == set(recommended)`` 全等 → True；否则 False（CONTEXT 未指定
          子集采纳语义，全等最无歧义）。
        - 无 recommended 或纯 freeform（selected 为空）→ ``None``（不计入采纳率分母）。

        返回轮次容器（``round_or_id`` 可为容器实例或其 id）。
        """
        started = time.perf_counter()
        round_id = getattr(round_or_id, "id", round_or_id)
        answered_count, adopted_count = await self._answer_round_sync(answers)
        self._safe_log(
            "clarification_round_answered",
            category="caller",
            component="delivery",
            clarification_id=str(round_id),
            answered_count=answered_count,
            adopted_count=adopted_count,
            total=len(answers),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        clar = await Clarification.objects.filter(id=round_id).afirst()
        return clar if clar is not None else round_or_id

    @sync_to_async
    def _answer_round_sync(self, answers: list[dict[str, Any]]) -> tuple[int, int]:
        answered = 0
        adopted = 0
        for ans in answers:
            ok, was_adopted = self._answer_question(
                ans.get("question_id"),
                ans.get("selected"),
                ans.get("freeform_text"),
            )
            if ok:
                answered += 1
                if was_adopted:
                    adopted += 1
        return answered, adopted

    def _answer_question(
        self, question_id: Any, selected: Any, freeform_text: Any
    ) -> tuple[bool, bool | None]:
        """单题幂等作答 + 采纳信号定格（同步，须在 sync_to_async 块内调用）。

        返回 ``(是否首答成功, recommendation_adopted)``；非首答（已答/不存在）→ ``(False, None)``。
        """
        q = ClarificationQuestion.objects.filter(id=question_id, answered_at__isnull=True).first()
        if q is None:
            # 幂等 no-op：题不存在或已答，不二次覆盖首答
            return False, None

        rec = q.recommended or []
        if not rec or selected in (None, "", [], {}):
            # 无推荐项 或 纯 freeform（无 selected）→ 不计入采纳率分母
            adopted: bool | None = None
        elif q.qtype == "multi":
            want = rec if isinstance(rec, (list, tuple)) else [rec]
            adopted = set(selected or []) == set(want)
        else:
            want_single = rec[0] if isinstance(rec, (list, tuple)) else rec
            adopted = selected == want_single

        updated = ClarificationQuestion.objects.filter(
            id=question_id, answered_at__isnull=True
        ).update(
            selected=selected,
            freeform_text=freeform_text or "",
            answered_at=timezone.now(),
            recommendation_adopted=adopted,
        )
        if updated != 1:
            # 并发竞答兜底：条件更新未命中视为 no-op（不重复计数）
            return False, None
        return True, adopted

    async def ahas_pending(self, session_id: Any) -> bool:
        """统一 pending 谓词：会话内是否仍有未答澄清（兼容旧单题行 + 新结构化子题）。

        两形态收口为单一判定（90-03 adapter / resume / e2e 共用，避免逻辑漂移）：

        - **新结构化**：轮内存在 ``answered_at IS NULL`` 的子题 → pending。
        - **旧单题行**（Pitfall 2）：容器 ``answered_at IS NULL`` 且**无任何子题** → 仍判
          pending，否则历史挂起会被误放行。
        """
        return await self._ahas_pending_sync(session_id)

    @sync_to_async
    def _ahas_pending_sync(self, session_id: Any) -> bool:
        child_pending = ClarificationQuestion.objects.filter(
            clarification__session_id=session_id, answered_at__isnull=True
        ).exists()
        if child_pending:
            return True
        # 旧单题行：无子题且容器未答（questions__isnull=True 表达「无子题」）
        legacy_pending = Clarification.objects.filter(
            session_id=session_id, answered_at__isnull=True, questions__isnull=True
        ).exists()
        return legacy_pending

    @staticmethod
    def _safe_log(event: str, **fields: Any) -> None:
        """best-effort 结构化生命周期埋点（绝不反噬业务，AGENTS.md 观测约束）。"""
        try:
            logger.info(event, **fields)
        except Exception:  # noqa: BLE001 — 观测失败吞掉，绝不阻断主流程
            pass
