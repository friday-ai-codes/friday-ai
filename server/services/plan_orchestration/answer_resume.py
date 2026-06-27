"""入口无关的共享「作答 + 续推」回流 helper（CLARIFY-06，91-01 地基）。

抽出飞书回调（91-03）与会话 endpoint（91-04）逐处同构的「写答案 → 续驱 engine」回流，
让两入口**同源**调用同一份逻辑（落 CONTEXT「工作流 + 会话同源，不造两套」），薄封装：

1. ``ClarificationService.answer_round``（按题幂等作答 + 定格采纳信号，INV-6 唯一写入入口）。
2. ``build_orchestration_engine``（engine 缺省时构造，chat 入口形态、无 node_execution_id）。
3. ``adrive_plan_session_to_pause_or_terminal``（续驱到重挂起短路点或终态）。

设计要点：
- **入口无关**：``engine`` 缺省 = chat 入口（``build_orchestration_engine()``）；工作流入口可
  传带 ``node_execution_id`` 的 engine 直接复用。**入口私有重调度（节点重入 / chat barrier
  回灌 / marker 写入）留各调用方**，本 helper 不碰。
- **INV-6**：写入只经 ``ClarificationService.answer_round``，helper 内绝不直接写 delivery 表
  （无任何 ORM create / update / save 旁路写）。
- **async 防裸 lazy-FK**：由 ``clar.session_id`` 标量取会话，不裸访问 ``clar.session``。
- **观测 best-effort**：进出口 ``answer_round_and_resume_started/completed``（category=caller、
  component=plan_orchestration、duration_ms），日志失败吞掉绝不反噬；业务异常**不**吞（让调用方
  fail-soft 包裹）。
"""

from __future__ import annotations

import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["aanswer_round_and_resume"]


def _safe_log(event: str, **fields: Any) -> None:
    """best-effort 结构化埋点（观测失败吞掉，绝不反噬业务）。"""
    try:
        logger.info(event, **fields)
    except Exception:  # noqa: BLE001 — 观测 best-effort，绝不阻断主流程
        pass


async def aanswer_round_and_resume(
    clarification_or_id: Any,
    answers: list[dict[str, Any]],
    *,
    engine: Any = None,
    clarification_service: Any = None,
) -> Any:
    """对一轮澄清作答并续驱其 ``PlanSession`` 到重挂起短路点或终态后返回该 session。

    入口无关：``engine`` 缺省 = chat 入口（``build_orchestration_engine()``）；工作流入口可传带
    ``node_execution_id`` 的 engine 直接复用。``clarification_service`` 缺省 ``ClarificationService()``，
    可注入复用（测试 / 调用方共享实例）。

    流程：① ``answer_round`` 按题幂等写入 ``selected/freeform`` 并定格采纳信号；② 由 ``clar.session_id``
    标量解析 ``PlanSession``（解析不出 → 返回 ``None``）；③ engine 缺省则构造；④ ``adrive`` 续驱返回。

    **入口私有重调度（节点重入 / chat barrier 回灌 / marker 写入）留各调用方**，本 helper 不驱动。
    """
    # 函数内 lazy import 规避 import 环（barrel 在模块加载期 re-export 本模块）
    from delivery.models import PlanSession
    from delivery.services import ClarificationService

    from .entrypoint import build_orchestration_engine
    from .resume import adrive_plan_session_to_pause_or_terminal

    started = time.perf_counter()
    _safe_log(
        "answer_round_and_resume_started",
        category="caller",
        component="plan_orchestration",
        answer_count=len(answers),
    )

    clarification_service = clarification_service or ClarificationService()
    clar = await clarification_service.answer_round(clarification_or_id, answers)

    # async 防裸 lazy-FK：用 session_id 标量解析会话。轮缺失（TOCTOU：并发删除/过期）时
    # answer_round 返回裸 id 而非模型实例，``getattr`` 取不到 session_id → 干净返回 None
    # （与 docstring「解析不出 → 返回 None」一致，不抛 AttributeError）。
    session_id = getattr(clar, "session_id", None)
    if session_id is None:
        _safe_log(
            "answer_round_and_resume_completed",
            category="caller",
            component="plan_orchestration",
            resolved_session=False,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return None
    session = await PlanSession.objects.filter(id=session_id).afirst()
    if session is None:
        _safe_log(
            "answer_round_and_resume_completed",
            category="caller",
            component="plan_orchestration",
            resolved_session=False,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return None

    engine = engine or build_orchestration_engine()
    session = await adrive_plan_session_to_pause_or_terminal(engine, session)

    _safe_log(
        "answer_round_and_resume_completed",
        category="caller",
        component="plan_orchestration",
        resolved_session=True,
        session_id=str(getattr(session, "id", "")),
        session_status=str(getattr(session, "status", "")),
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return session
