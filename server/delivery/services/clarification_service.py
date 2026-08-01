"""ClarificationService —— Clarification 唯一写入入口（CLARIFY-01，INV-6）。

承载 HITL 澄清回路的落库与状态变更（DOMAIN §6/§14），对齐
``ConvergenceSessionService`` 单一写入范式。**process-agnostic**：P3 起统一收口到结构化
轮次三方法，移除原与"多仓调研"耦合的 legacy 双写（``create_clarification`` /
``answer_clarification`` + ``affected_partials`` stale 重跑），使澄清对任意 ``process_type``
通用：

- ``create_round``：建 1 容器 + N 个 ``ClarificationQuestion`` 子题（``bulk_create``）。
- ``answer_round``：按题幂等作答 + 作答时一次性定格 ``recommendation_adopted`` 采纳信号
  （server 端计算，绝不接受调用方传入）；整轮答毕推进容器 + emit ``clarification.answered``。
- ``ahas_pending``：统一 pending 谓词，兼容无子题容器与结构化子题两形态。

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

logger = structlog.get_logger(__name__)

__all__ = ["ClarificationService"]


class ClarificationService:
    """Clarification 落库/状态变更唯一入口（INV-6 精神）。"""

    def __init__(
        self,
        *,
        session_service: Any = None,
    ) -> None:
        # 延迟默认构造避免 import 环（ConvergenceSessionService 同 app）
        if session_service is None:
            from delivery.services.convergence_session_service import (
                ConvergenceSessionService,
            )

            session_service = ConvergenceSessionService()
        self.session_service = session_service

    # ── CLARIFY-01 结构化澄清「轮次容器 + 多子题」写入入口（INV-6） ──────────────

    async def create_round(
        self,
        session: Any,
        questions: list[dict[str, Any]],
        *,
        origin_repo: str | None = None,
        round_no: int | None = None,
        plan_version_id: Any = None,
    ) -> Clarification | None:
        """建 1 个澄清轮次容器 + N 个 ClarificationQuestion 子题（结构化澄清唯一写入入口）。

        ``questions`` 为归一后的问题列表（见 ``normalize_clarification_questions`` 形态：
        ``{question, type, options, recommended}``）。容器以 ``question=""`` 占位保旧 NOT NULL
        列、真身在子题；子题按列表顺序 ``order`` 0-based 递增，``qtype`` 取 ``type``（缺省
        single），可携 ``origin_repo``（CLARIFY-03 透传）。全部写入只经本 service（INV-6），
        子题经 ``bulk_create`` 在 ``sync_to_async`` 同步块内一次性落库。

        **空问题守护（WR-02）**：``questions`` 为空时**不创建轮次**、返回 ``None``——空轮会落成
        一个永久无子题可作答的 pending 容器（``ahas_pending`` 旧单题分支恒判 pending）导致无限挂起。
        调用方据 ``None`` 不挂起（保 fail-soft）。
        """
        if not questions:
            self._safe_log(
                "clarification_round_skipped_empty",
                category="caller",
                component="delivery",
                session_id=str(getattr(session, "id", "")),
            )
            return None
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
        answered_count, adopted_count, round_completed = await self._answer_round_sync(
            round_id, answers
        )
        self._safe_log(
            "clarification_round_answered",
            category="caller",
            component="delivery",
            clarification_id=str(round_id),
            answered_count=answered_count,
            adopted_count=adopted_count,
            total=len(answers),
            round_completed=round_completed,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        clar = await Clarification.objects.filter(id=round_id).afirst()
        # 整轮答毕（容器本次推进 answered）→ emit clarification.answered（best-effort，
        # process-agnostic：不再携带任何 process 专属重跑面，仅含 clarification_id + 计数标量）。
        if round_completed:
            await self._emit_answered(round_id, answered_count, adopted_count)
        return clar if clar is not None else round_or_id

    async def _emit_answered(
        self, round_id: Any, answered_count: int, adopted_count: int
    ) -> None:
        """emit ``clarification.answered``（payload 仅标量，绝不含澄清正文），best-effort。

        async 安全：经 ``clarification.session_id`` 标量取会话（不裸 lazy-FK
        ``clarification.session``，规避 Phase 38 CR-01 类）；事件持久化失败不阻断作答主流程。
        """
        from delivery.models import ConvergenceSession

        session_id = await (
            Clarification.objects.filter(id=round_id).values_list("session_id", flat=True).afirst()
        )
        if session_id is None:
            return
        session = await ConvergenceSession.objects.filter(id=session_id).afirst()
        if session is None:
            return
        payload = {
            "clarification_id": str(round_id),
            "answered_count": answered_count,
            "adopted_count": adopted_count,
        }
        try:
            await self.session_service._emit_event(EVENT_CLARIFICATION_ANSWERED, session, payload)
        except Exception:  # noqa: BLE001 — 事件 best-effort，绝不阻断作答
            self._safe_log(
                "clarification_answered_emit_failed",
                category="caller",
                component="delivery",
                clarification_id=str(round_id),
            )

    @sync_to_async
    def _answer_round_sync(
        self, round_id: Any, answers: list[dict[str, Any]]
    ) -> tuple[int, int, bool]:
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
        round_completed = self._maybe_advance_container(round_id)
        return answered, adopted, round_completed

    def _maybe_advance_container(self, round_id: Any) -> bool:
        """轮内所有子题都已作答时，把容器 ``container_status`` 推进到 ``answered``（WR-01）。

        幂等：仅当容器**自身仍未答**（``answered_at IS NULL``）且**无任何 ``answered_at IS NULL``
        子题**时条件更新（兼容并发竞答 + 重复作答 no-op）。无子题的旧单题行不经本路径（结构化轮
        才有子题）。返回是否本次推进到 answered。

        幂等条件锚 ``answered_at`` 而非 ``container_status="pending"``：``container_status`` 是
        送达/展示态，会取到 ``delivery_failed``（RELY-02）等非 pending 值；锚它会让「卡没送达但
        用户从会话面答了」的轮永远推不到 answered。pending 的权威字段始终是 ``answered_at``。
        """
        has_unanswered = ClarificationQuestion.objects.filter(
            clarification_id=round_id, answered_at__isnull=True
        ).exists()
        if has_unanswered:
            return False
        has_children = ClarificationQuestion.objects.filter(clarification_id=round_id).exists()
        if not has_children:
            # 防御性：无子题容器不经本路径推进（结构化轮才有子题；空轮已由 create_round
            # 的 WR-02 守护拒建，正常不会出现）。
            return False
        updated = Clarification.objects.filter(id=round_id, answered_at__isnull=True).update(
            container_status="answered", answered_at=timezone.now()
        )
        return updated == 1

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
        """统一 pending 谓词：会话内是否仍有未答澄清（adapter / resume / 节点共用）。

        - **结构化轮**：轮内存在 ``answered_at IS NULL`` 的子题 → pending。
        - **无子题容器**（防御性）：容器 ``answered_at IS NULL`` 且**无任何子题** → 仍判
          pending（正常不出现，create_round 的 WR-02 守护拒建空轮；保留兜底防误放行）。
        """
        return await self._ahas_pending_sync(session_id)

    @sync_to_async
    def _ahas_pending_sync(self, session_id: Any) -> bool:
        child_pending = ClarificationQuestion.objects.filter(
            clarification__session_id=session_id, answered_at__isnull=True
        ).exists()
        if child_pending:
            return True
        # 无子题容器：未答且无任何子题（questions__isnull=True 表达「无子题」）
        childless_pending = Clarification.objects.filter(
            session_id=session_id, answered_at__isnull=True, questions__isnull=True
        ).exists()
        return childless_pending

    @staticmethod
    def _safe_log(event: str, **fields: Any) -> None:
        """best-effort 结构化生命周期埋点（绝不反噬业务，AGENTS.md 观测约束）。"""
        try:
            logger.info(event, **fields)
        except Exception:  # noqa: BLE001 — 观测失败吞掉，绝不阻断主流程
            pass
