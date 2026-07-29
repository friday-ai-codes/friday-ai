"""ProcessEngine —— 数据化 stage graph 推进器（Chassis v2 · P2，泛化自 PlanOrchestrationEngine）。

入口无关的**状态驱动 step 推进器**：``advance(session)`` 按 ``session.current_stage`` 取
``ProcessDefinition`` 的 stage handler 跑一步 → 按 handler 返回的 ``StageOutcome.event``
经 ``ConvergenceSessionService.transition`` 查 stage graph 转移落库（engine 绝不直接 mutate
``session.status`` / ``current_stage``）。

设计要点：
- **进程无关**：engine 不耦合任何具体流程；流程由 ``process_type`` 注册的 stage graph 决定。
- **可注入依赖**：``deps`` 为任意 namespace（如 technical_plan 注入 router/recall/research/
  merge/clarify adapters；echo 无需依赖），handler 自取所需。
- **状态从 DB resume**：``advance`` 按持久化 ``current_stage`` 续推，不依赖内存态。
- **pausable 短路**：pausable stage 命中挂起条件时 handler 返回 self-loop event，transition
  置 ``status = wait_status``；驱动 helper（``resume.py``）据 status 短路返回。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from delivery.models import ConvergenceSessionStatus

logger = structlog.get_logger(__name__)

__all__ = ["ProcessEngine", "StageOutcome"]

_TERMINAL = {ConvergenceSessionStatus.DONE, ConvergenceSessionStatus.FAILED}


@dataclass
class StageOutcome:
    """stage handler 的产出：转移 event + 可选 stage_state 增量 / 产物版本 / 错误。

    - ``event``：stage graph 转移 event（查 ``StageDef.transitions``）。
    - ``stage_state_update``：合并进 ``session.stage_state`` 的增量 dict（None 不改）。
    - ``current_artifact_version``：本步产出的 ``ArtifactVersion`` id（merge 段产出主产物时）。
    - ``error``：落终态 ``__failed__`` 时的结构化错误（仅 fail/exhausted 路径）。
    """

    event: str
    stage_state_update: dict | None = None
    current_artifact_version: Any = None
    error: dict | None = field(default=None)


class ProcessEngine:
    """数据化 stage graph 推进器（入口无关 + 可注入依赖）。"""

    def __init__(self, *, session_service: Any = None, deps: Any = None) -> None:
        from delivery.services import ConvergenceSessionService

        self.session_service = session_service or ConvergenceSessionService()
        # 任意 namespace：technical_plan 注入 adapters，echo 为 None。
        self.deps = deps

    async def advance(self, session: Any) -> Any:
        """按 ``session.current_stage`` 取 handler 跑一步并经 transition 推进（状态驱动 resume）。

        终态（done/failed）直接返回。handler 内不可恢复异常 → 经 transition 落 ``fail``
        （结构化 error 含 stage/异常类型/消息）。**例外**：``NotImplementedError`` 原样上抛
        （开发期显式暴露未接入 stage）。
        """
        from services.process_runtime.registry import get_process_definition

        if session.status in _TERMINAL:
            return session

        definition = get_process_definition(session.process_type)
        if definition is None:
            await self.session_service.transition(
                session,
                "fail",
                error={"reason": "unknown_process_type", "process_type": session.process_type},
            )
            return session

        stage_key = session.current_stage or definition.initial_stage
        stage_def = definition.stage(stage_key)
        if stage_def is None:
            await self.session_service.transition(
                session,
                "fail",
                error={"reason": "unknown_stage", "stage": stage_key},
            )
            return session

        try:
            outcome = await stage_def.handler(session, self)
        except NotImplementedError:
            raise
        except Exception as exc:  # noqa: BLE001 — stage 内不可恢复异常 → 落 fail 终态
            error = {
                "stage": stage_key,
                "exception": type(exc).__name__,
                "message": str(exc),
            }
            await self.session_service.transition(session, "fail", error=error)
            return session

        # 增量交给 service 在写入事务内锁行合并：self-loop 转移（pausable stage 的挂起边）
        # 下 `current_stage` 的 CAS 对两个并发写者同时成立，在这里用内存里的 `session`
        # 预合并会让后写者整份覆盖先写者的 stage_state（排除集/确认门标记会被回退）。
        from delivery.services.convergence_session_service import ConcurrentTransitionError

        try:
            await self.session_service.transition(
                session,
                outcome.event,
                stage_state_update=outcome.stage_state_update or None,
                current_artifact_version=outcome.current_artifact_version,
                error=outcome.error,
            )
        except ConcurrentTransitionError:
            # 良性并发：barrier/回调侧已推进同一 session（self-loop CAS 命中 0 行）。绝不让其
            # 落到 fail（否则覆盖并发正确推进的状态，属状态损坏）。
            logger.info(
                "stage_already_advanced_concurrently",
                category="sampling",
                component="process_runtime",
                session_id=str(session.id),
                stage=stage_key,
            )
        return session
