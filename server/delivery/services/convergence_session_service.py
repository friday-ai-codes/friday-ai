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

from agents.core.events import PROCESS_EVENT
from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionEvent,
    ConvergenceSessionStatus,
)
from delivery.services.event_taxonomy import EVENT_PROCESS_SESSION_FAILED, build_envelope
from delivery.services.process_event_wire import sanitize_process_event_payload

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
        """事件钩子：持久化统一信封行 ``ConvergenceSessionEvent``（best-effort，绝不抛）。

        Phase 110-01：持久化之后追加一次 best-effort SSE fan-out（chat 入口的秒级直播）。
        这里是编排事件的**唯一**推送出口（INV-6）——7 个 stage handler 与各 adapter 的
        emit 点零改动即自动获得推送；挂在各 handler 里则每加一个阶段都要记得补推，是
        必然漂移的形态。
        """
        logger.info(
            "convergence_session_event",
            category="sampling",
            component="convergence_session_service",
            event_name=event_name,
            session_id=str(session.id),
            status=session.status,
        )
        row = None
        try:
            row = await self._persist_event(event_name, session, payload)
        except Exception as exc:  # noqa: BLE001 — best-effort：事件持久化失败绝不阻断转移
            logger.warning(
                "convergence_session_event_persist_failed",
                event_name=event_name,
                session_id=str(session.id),
                error=str(exc),
            )
        # 🔴 落库失败即不推：没有权威 ts 可对齐的事件推出去只会变成一条永远无法被运行时
        # 快照补齐、也永远无法被前端去重键命中的孤儿事件。
        if row is not None:
            await self._fanout_process_event(event_name, session, payload, row)

    async def _fanout_process_event(
        self,
        event_name: str,
        session: ConvergenceSession,
        payload: dict[str, Any],
        row: ConvergenceSessionEvent,
    ) -> None:
        """把已落库的事件推上当前 chat graph 的 custom 流（best-effort，整体吞异常）。

        取不到 writer 就是**没有推送目标**——workflow / MCP 入口与容器回调续驱（不在任何
        graph 运行上下文内）三种情形都自动落进静默跳过分支，无需自建注册表、无需把 writer
        一路透传穿过 engine / adapter。
        """
        try:
            # workflow / MCP 入口无 chat 会话可推：早退（与写库无关，故放在函数体前部）。
            conversation_id = getattr(session, "conversation_id", None)
            if not conversation_id:
                return

            # 函数内 import：不给 delivery 层加一个模块级的 langgraph 依赖。
            from langgraph.config import get_stream_writer

            writer = get_stream_writer()

            envelope = build_envelope(event_name, session, sanitize_process_event_payload(payload))
            # 🔴 用落库行的 ts 覆盖 build_envelope 自取的那个：后者是它自己调
            # timezone.now() 得到的瞬时值，与 ConvergenceSessionEvent.ts 默认值分属两次
            # 求值（且 _persist_event 有 sync_to_async 线程跳变），必然不等。若不对齐，
            # 前端按 (event, ts, …) 去重时 SSE 那条与快照那条会被当成两条不同事件，
            # 调研完成数 / 融合轮次 / 澄清轮次这类计数会成倍虚高——症状看起来像前端算错了。
            envelope["ts"] = row.ts.isoformat()

            writer({"type": PROCESS_EVENT, "data": envelope})

            # 高频路径（一次编排数十条）：debug + sampling，绝不为每条事件打 INFO。
            logger.debug(
                "process_event_fanout",
                category="sampling",
                component="convergence_session_service",
                event_name=event_name,
                session_id=str(session.id),
                conversation_id=str(conversation_id),
            )
        except Exception:  # noqa: BLE001 — 观测代码绝不反噬业务：编排跑通比进度可见重要
            # 🔴 必须是 blanket Exception，不得「收紧」成 except RuntimeError：
            # get_stream_writer() 的实现是 get_config()[CONF][CONFIG_KEY_RUNTIME]，
            # 「压根没有 runnable context」抛 RuntimeError，而「有 runnable context 但不是
            # langgraph runtime」（例如一条普通 LangChain runnable 链）抛 KeyError。
            # 收紧后，后一条路径会把异常放出去、直接打断编排主流程。
            # 这里也不打 warning：取不到 writer 是正常态（workflow / MCP / 回调续驱三种
            # 入口都取不到），为它打日志等于给正常路径刷噪音。
            pass

    @sync_to_async
    def _persist_event(
        self, event_name: str, session: ConvergenceSession, payload: dict[str, Any]
    ) -> ConvergenceSessionEvent:
        """落库并**返回该行**——出网信封的权威 ts 由它回填（见 ``_fanout_process_event``）。

        注意落库的 ``payload`` 仍是**未净化**的原文：留痕面与出网面是两个面，原文只入
        事件表供 superuser 排障。
        """
        return ConvergenceSessionEvent.objects.create(
            session=session,
            event=event_name,
            work_item=session.work_item_id,
            payload=payload or {},
        )
