"""ConvergenceSessionService —— ConvergenceSession 状态变更唯一写入入口（Chassis v2 · P2，INV-6）。

泛化自 ``PlanSessionService``：转移目标**从 stage graph（``ProcessDefinition``）查**，不再写死
``_ALLOWED`` 常量。``transition(session, event)`` 据 ``session.process_type`` + ``current_stage``
查 ``StageDef.transitions[event]`` 得目标 stage（或 ``__done__`` / ``__failed__`` sentinel），
以「DB 行 ``current_stage == from_stage``」为前置条件做 CAS 原子更新（WR-01 防 TOCTOU）。

- 合法转移：更新 ``current_stage`` + ``status`` + 持久化 ``stage_state`` / ``current_artifact_version``
  + 调 ``_emit_event`` 钩子。
- 非法转移（event 不在 stage transitions）：``raise ValueError``（status 不变、DB 不写）。
- ``fail`` 事件特判（不进 stage graph）：任意 stage → ``failed`` + 落结构化 ``error``。

status 派生规则（与 stage 身份正交）：
- target == ``__done__`` → ``done``；target == ``__failed__`` → ``failed``。
- target == from_stage（self-loop）→ pausable stage 取 ``wait_status``，否则 ``running``。
- target 为其它 stage（forward）→ ``running`` + ``current_stage = target``。

状态全持久化在 DB 行，``ProcessEngine`` 可从任意状态 resume。ORM 写经 ``sync_to_async`` 桥接。
"""

from __future__ import annotations

from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionEvent,
    ConvergenceSessionStatus,
)
from delivery.services.event_taxonomy import EVENT_PROCESS_SESSION_FAILED

logger = structlog.get_logger(__name__)

__all__ = ["ConcurrentTransitionError", "ConvergenceSessionService"]

# 区分「不改 current_artifact_version」与「显式置 None」的 sentinel
_UNSET: Any = object()


class ConcurrentTransitionError(RuntimeError):
    """并发/陈旧状态转移被拒（WR-01）。

    ``transition`` 以「DB 行 current_stage == 预期 from_stage」为条件原子更新；条件不满足
    （影响行数 != 1）即说明 DB 行已被并发/陈旧推进改写或行不存在——拒绝盲写覆盖，抛本异常
    （保 resume 安全：两个并发 advance 不能同时成功推进同一转移）。
    """


class ConvergenceSessionService:
    """ConvergenceSession 状态变更唯一入口（INV-6 精神）。"""

    async def create_session(
        self,
        process_type: str,
        entrypoint: str,
        *,
        work_item: Any = None,
        stage_state: dict | None = None,
        created_by: Any = None,
        conversation_id: Any = None,
        node_execution_id: Any = None,
        initiated_by_user_id: str = "",
        event_time: Any = None,
    ) -> ConvergenceSession:
        """建 ConvergenceSession（status=created，current_stage=initial_stage）。

        ``entrypoint`` 须为 ``ConvergenceSessionEntrypoint`` 合法值，否则 ``raise ValueError``。
        ``process_type`` 须注册于 ``ProcessTypeRegistry``，否则 ``raise ValueError``。
        """
        from services.process_runtime.registry import get_process_definition

        if entrypoint not in ConvergenceSessionEntrypoint.values:
            raise ValueError(
                f"非法 entrypoint={entrypoint!r}；合法值={list(ConvergenceSessionEntrypoint.values)}"
            )
        definition = get_process_definition(process_type)
        if definition is None:
            raise ValueError(f"未注册的 process_type={process_type!r}")
        return await self._create_session_sync(
            process_type=process_type,
            entrypoint=entrypoint,
            initial_stage=definition.initial_stage,
            work_item=work_item,
            stage_state=stage_state or {},
            created_by=created_by,
            conversation_id=conversation_id,
            node_execution_id=node_execution_id,
            initiated_by_user_id=initiated_by_user_id or "",
            event_time=event_time,
        )

    @sync_to_async
    def _create_session_sync(
        self,
        *,
        process_type: str,
        entrypoint: str,
        initial_stage: str,
        work_item: Any,
        stage_state: dict,
        created_by: Any,
        conversation_id: Any,
        node_execution_id: Any,
        initiated_by_user_id: str,
        event_time: Any,
    ) -> ConvergenceSession:
        return ConvergenceSession.objects.create(
            process_type=process_type,
            entrypoint=entrypoint,
            current_stage=initial_stage,
            status=ConvergenceSessionStatus.CREATED,
            work_item=work_item,
            stage_state=stage_state,
            created_by=created_by,
            conversation_id=conversation_id,
            node_execution_id=node_execution_id,
            initiated_by_user_id=initiated_by_user_id,
            event_time=event_time,
        )

    async def transition(
        self,
        session: ConvergenceSession,
        event: str,
        *,
        stage_state: dict | None = None,
        current_artifact_version: Any = _UNSET,
        error: dict | None = None,
        event_time: Any = None,
    ) -> ConvergenceSession:
        """**状态唯一变更入口**：据 stage graph 查转移目标并 CAS 推进。

        ``event == "fail"``：任意 stage → ``failed`` + 落 ``error``（结构化）。其余事件查
        ``StageDef.transitions[event]``；不在其中 → ``raise ValueError``。
        """
        if event == "fail":
            return await self._fail(session, error)

        from services.process_runtime.registry import (
            STAGE_DONE,
            STAGE_FAILED,
            get_process_definition,
        )

        definition = get_process_definition(session.process_type)
        if definition is None:
            raise ValueError(f"未注册的 process_type={session.process_type!r}")
        from_stage = session.current_stage or definition.initial_stage
        stage_def = definition.stage(from_stage)
        if stage_def is None:
            raise ValueError(f"未知 stage={from_stage!r}（process_type={session.process_type})")
        target = stage_def.transitions.get(event)
        if target is None:
            raise ValueError(
                f"非法状态转移：stage={from_stage} event={event}；"
                f"该 stage 合法 event={sorted(stage_def.transitions)}"
            )

        if target == STAGE_DONE:
            new_stage, new_status = from_stage, ConvergenceSessionStatus.DONE
        elif target == STAGE_FAILED:
            new_stage, new_status = from_stage, ConvergenceSessionStatus.FAILED
        elif target == from_stage:
            new_stage = from_stage
            new_status = (
                stage_def.wait_status
                if stage_def.pausable
                else ConvergenceSessionStatus.RUNNING
            )
        else:
            new_stage, new_status = target, ConvergenceSessionStatus.RUNNING

        await self._apply_transition_sync(
            session,
            from_stage=from_stage,
            new_stage=new_stage,
            new_status=str(new_status),
            stage_state=stage_state,
            current_artifact_version=current_artifact_version,
            error=error if target == STAGE_FAILED else None,
            event_time=event_time,
        )
        await self._emit_event(event, session, {})
        return session

    @sync_to_async
    def _apply_transition_sync(
        self,
        session: ConvergenceSession,
        *,
        from_stage: str,
        new_stage: str,
        new_status: str,
        stage_state: dict | None,
        current_artifact_version: Any,
        error: dict | None,
        event_time: Any,
    ) -> None:
        """以 ``current_stage == from_stage`` 为前置条件的原子更新（WR-01 防 TOCTOU）。"""
        update_values: dict[str, Any] = {
            "current_stage": new_stage,
            "status": new_status,
            "updated_at": timezone.now(),
        }
        if stage_state is not None:
            update_values["stage_state"] = stage_state
        if current_artifact_version is not _UNSET:
            update_values["current_artifact_version_id"] = current_artifact_version
        if error is not None:
            update_values["error"] = error
        if event_time is not None:
            update_values["event_time"] = event_time

        updated = ConvergenceSession.objects.filter(
            id=session.id, current_stage=from_stage
        ).update(**update_values)
        if updated != 1:
            raise ConcurrentTransitionError(
                f"并发/陈旧状态转移被拒：session={session.id} "
                f"expected_from={from_stage} to={new_stage}"
                "（DB 行 current_stage 已被并发推进改写或行不存在）"
            )
        session.current_stage = new_stage
        session.status = new_status
        if stage_state is not None:
            session.stage_state = stage_state
        if current_artifact_version is not _UNSET:
            session.current_artifact_version_id = current_artifact_version
        if error is not None:
            session.error = error
        if event_time is not None:
            session.event_time = event_time

    async def _fail(
        self, session: ConvergenceSession, error: Any
    ) -> ConvergenceSession:
        """``fail`` 特判：任意非终态 stage → failed + 落结构化 error。

        终态守护：已 done/failed 的会话再 fail 为幂等 no-op（保留首因）。CAS 命中 0 行
        （并发已推进到别的 stage）→ 不盲写覆盖，re-fetch 同步内存态后放弃 fail。
        """
        if session.status in (
            ConvergenceSessionStatus.DONE,
            ConvergenceSessionStatus.FAILED,
        ):
            logger.info(
                "convergence_session_fail_noop_terminal",
                category="sampling",
                component="convergence_session_service",
                session_id=str(session.id),
                status=session.status,
            )
            return session
        structured = error if isinstance(error, dict) else {"message": str(error)}
        applied = await self._fail_sync(session, structured)
        if not applied:
            await self._refresh_status_sync(session)
            logger.info(
                "convergence_session_fail_skip_concurrent_advance",
                category="sampling",
                component="convergence_session_service",
                session_id=str(session.id),
                current_stage=session.current_stage,
                status=session.status,
            )
            return session
        await self._emit_event(EVENT_PROCESS_SESSION_FAILED, session, {})
        return session

    @sync_to_async
    def _fail_sync(self, session: ConvergenceSession, error: dict[str, Any]) -> bool:
        """以 ``current_stage == 内存 from_stage`` 为前置条件的原子 fail 更新（WR-03 防盲写覆盖）。"""
        from_stage = session.current_stage
        updated = ConvergenceSession.objects.filter(
            id=session.id, current_stage=from_stage
        ).update(
            status=ConvergenceSessionStatus.FAILED,
            error=error,
            updated_at=timezone.now(),
        )
        if updated != 1:
            return False
        session.status = ConvergenceSessionStatus.FAILED
        session.error = error
        return True

    @sync_to_async
    def _refresh_status_sync(self, session: ConvergenceSession) -> None:
        """从 DB 重读 status/current_stage 同步内存态（fail 被并发推进拒绝后）。"""
        fresh = (
            ConvergenceSession.objects.filter(id=session.id)
            .values("status", "current_stage")
            .first()
        )
        if fresh is not None:
            session.status = fresh["status"]
            session.current_stage = fresh["current_stage"]

    async def _emit_event(
        self, event_name: str, session: ConvergenceSession, payload: dict[str, Any]
    ) -> None:
        """事件钩子：持久化统一信封行 ``ConvergenceSessionEvent``（best-effort，绝不抛）。"""
        logger.info(
            "convergence_session_event",
            category="sampling",
            component="convergence_session_service",
            event_name=event_name,
            session_id=str(session.id),
            status=session.status,
        )
        try:
            await self._persist_event(event_name, session, payload)
        except Exception as exc:  # noqa: BLE001 — best-effort：事件持久化失败绝不阻断转移
            logger.warning(
                "convergence_session_event_persist_failed",
                event_name=event_name,
                session_id=str(session.id),
                error=str(exc),
            )

    @sync_to_async
    def _persist_event(
        self, event_name: str, session: ConvergenceSession, payload: dict[str, Any]
    ) -> None:
        ConvergenceSessionEvent.objects.create(
            session=session,
            event=event_name,
            work_item=session.work_item_id,
            payload=payload or {},
        )
