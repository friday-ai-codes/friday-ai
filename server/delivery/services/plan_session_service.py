"""PlanSessionService —— PlanSession 状态变更唯一写入入口（ORCH-02，INV-6 精神）。

状态机驱动按 DOMAIN §14 转移表的白名单字典 ``_ALLOWED``（``{from_status:
{event: to_status}}``）校验：合法转移更新 status + 持久化中间产物 JSON + 调
``_emit_event`` 钩子；非法转移 ``raise ValueError``（status 不变、DB 不写）。
``fail`` 事件特判（不进 ``_ALLOWED``）：任意状态 → ``failed`` + 落结构化 ``error``。

状态全持久化在 DB 行（status + 中间产物 JSON），engine 可从任意 status resume，
不依赖内存态（T-36-02-03 可恢复性）。ORM 写经 ``sync_to_async`` 桥接（沿用
delivery service async 范式）。
"""

from __future__ import annotations

from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from delivery.models import (
    PlanSession,
    PlanSessionEntrypoint,
    PlanSessionEvent,
    PlanSessionStatus,
)
from delivery.services.event_taxonomy import EVENT_PLAN_SESSION_FAILED

logger = structlog.get_logger(__name__)

__all__ = ["ConcurrentTransitionError", "PlanSessionService"]


class ConcurrentTransitionError(RuntimeError):
    """并发/陈旧状态转移被拒（WR-01）。

    ``transition`` 以「DB 行 status == 预期 from_status」为条件原子更新；条件不满足
    （影响行数 != 1）即说明 DB 行已被并发/陈旧推进改写或行不存在——拒绝盲写覆盖，
    抛本异常（保 resume 安全：两个并发 advance 不能同时成功推进同一转移）。
    """


# DOMAIN §14 转移表的白名单（{from_status: {event: to_status}}）。
# event 命名与 §14 语义对齐（Claude's Discretion）。``fail`` 不入此表，由 transition 特判。
_ALLOWED: dict[str, dict[str, str]] = {
    # §14 行：decomposing | 拆分完成 → routing
    PlanSessionStatus.DECOMPOSING: {
        "decomposed": PlanSessionStatus.ROUTING,
    },
    # §14 行：routing | RepoRouterV2 返回候选仓 → recalling
    PlanSessionStatus.ROUTING: {
        "routed": PlanSessionStatus.RECALLING,
    },
    # §14 行：recalling | 召回完成 → clarifying
    PlanSessionStatus.RECALLING: {
        "recalled": PlanSessionStatus.CLARIFYING,
    },
    # §14 行：clarifying | 无待澄清/全部已答 → researching；有待澄清 → clarifying(自挂起)
    PlanSessionStatus.CLARIFYING: {
        "clarified": PlanSessionStatus.RESEARCHING,
        "needs_clarification": PlanSessionStatus.CLARIFYING,
    },
    # §14 行：researching | fan-out 等待 → researching(自留)；所有 done/failed → merging
    PlanSessionStatus.RESEARCHING: {
        "research_dispatched": PlanSessionStatus.RESEARCHING,
        "research_complete": PlanSessionStatus.MERGING,
    },
    # §14 行：merging | 融合+validator 通过 → done；validator 失败 → 按报告回退 clarifying 或 researching
    PlanSessionStatus.MERGING: {
        "merged": PlanSessionStatus.DONE,
        "validation_failed_reclarify": PlanSessionStatus.CLARIFYING,
        "validation_failed_reresearch": PlanSessionStatus.RESEARCHING,
    },
}

# transition payload 中允许落库的模型字段（仅与模型字段同名的键，半可信 payload 防越权写）
# routing/recall_context 为 Phase 38-02/38-03 engine transition 落库的唯一通道
_PERSISTABLE_FIELDS = (
    "decomposition",
    "routing",
    "recall_context",
    "current_plan_version",
    "event_time",
)


class PlanSessionService:
    """PlanSession 状态变更唯一入口（INV-6 精神）。"""

    async def create_session(
        self,
        entrypoint: str,
        *,
        work_item: Any = None,
        decomposition: dict | None = None,
        event_time: Any = None,
        created_by: Any = None,
        conversation_id: Any = None,
    ) -> PlanSession:
        """建 PlanSession（status 默认 decomposing）—— engine/入口层建会话的入口。

        IN-02：``entrypoint`` 须为 ``PlanSessionEntrypoint`` 合法值（workflow|chat），
        否则 ``raise ValueError``（Django ``choices`` 仅 ``full_clean()`` 校验、``create()``
        不触发，作为单一写入入口须显式校验，与状态机「非法即 raise」风格一致）。

        ``created_by`` 为发起编排的用户（可空）：召回 stage（38-03）作权限 actor，
        为 None 时下游 search_similar fail-closed 返回空召回（不泄漏越权数据）。
        """
        if entrypoint not in PlanSessionEntrypoint.values:
            raise ValueError(
                f"非法 entrypoint={entrypoint!r}；合法值={list(PlanSessionEntrypoint.values)}"
            )
        return await self._create_session_sync(
            entrypoint, work_item, decomposition, event_time, created_by, conversation_id
        )

    @sync_to_async
    def _create_session_sync(
        self,
        entrypoint: str,
        work_item: Any,
        decomposition: dict | None,
        event_time: Any,
        created_by: Any,
        conversation_id: Any = None,
    ) -> PlanSession:
        return PlanSession.objects.create(
            entrypoint=entrypoint,
            work_item=work_item,
            decomposition=decomposition or {},
            event_time=event_time,
            created_by=created_by,
            conversation_id=conversation_id,
        )

    async def set_current_plan_version(self, session: PlanSession, version_id: Any) -> PlanSession:
        """窄方法：把 ``PlanSession.current_plan_version`` 写为指定 PlanVersion.id（不旁路模型写）。

        merging 段架构师融合落 canonical 后须置 ``current_plan_version``，但该写入**不在
        §14 转移点**（转移由 engine 做）——为不旁路模型写（INV-6 精神），融合 adapter 经本
        窄方法写。``update()`` 条件更新（不触发 auto_now，显式写 updated_at）+ 同步内存态。
        """
        await self._set_current_plan_version_sync(session, version_id)
        return session

    @sync_to_async
    def _set_current_plan_version_sync(self, session: PlanSession, version_id: Any) -> None:
        PlanSession.objects.filter(id=session.id).update(
            current_plan_version=version_id, updated_at=timezone.now()
        )
        session.current_plan_version = version_id

    async def transition(self, session: PlanSession, event: str, **payload: Any) -> PlanSession:
        """**status 唯一变更入口**：按 ``_ALLOWED``(§14) 校验并推进。

        ``event == "fail"``：任意状态 → ``failed``，把 ``payload["error"]`` 结构化写入
        ``session.error``（非 dict 包成 ``{"message": str(error)}``）。

        其余事件：查 ``_ALLOWED[session.status]``；event 不在其中 → ``raise ValueError``
        （消息含 from_status + event + 该状态合法 event 集），status 不变、DB 不写。
        合法 → set ``status = to_status`` + 按 payload 持久化中间产物（仅与模型字段
        同名的键 decomposition/current_plan_version/event_time），保存后调 ``_emit_event``。
        """
        if event == "fail":
            return await self._fail(session, payload)

        from_status = session.status
        allowed = _ALLOWED.get(from_status, {})
        if event not in allowed:
            raise ValueError(
                f"非法状态转移：from_status={str(from_status)} event={event}；"
                f"该状态合法 event={sorted(allowed)}"
            )
        to_status = allowed[event]
        await self._apply_transition_sync(session, from_status, to_status, payload)
        await self._emit_event(event, session, payload)
        return session

    @sync_to_async
    def _apply_transition_sync(
        self, session: PlanSession, from_status: str, to_status: str, payload: dict[str, Any]
    ) -> None:
        """合法转移落库：以 ``status == from_status`` 为前置条件的原子更新（WR-01 防 TOCTOU）。

        用 ``filter(id=, status=from_status).update(...)`` 做条件更新并断言影响行数==1；
        ==0 表示 DB 行 status 已被并发/陈旧 advance 改写或行不存在 → 抛
        ``ConcurrentTransitionError``，**不盲写覆盖**（两个并发 advance 不能同时成功
        推进同一转移，保 resume 安全）。``update()`` 不触发 ``auto_now``，故显式写
        ``updated_at=timezone.now()``。更新成功后才同步内存态，保持与 DB 一致。
        """
        update_values: dict[str, Any] = {"status": to_status, "updated_at": timezone.now()}
        for field in _PERSISTABLE_FIELDS:
            if field in payload:
                update_values[field] = payload[field]
        updated = PlanSession.objects.filter(id=session.id, status=from_status).update(
            **update_values
        )
        if updated != 1:
            raise ConcurrentTransitionError(
                f"并发/陈旧状态转移被拒：session={session.id} "
                f"expected_from={from_status} to={to_status}"
                "（DB 行 status 已被并发推进改写或行不存在）"
            )
        session.status = to_status
        for field, value in update_values.items():
            setattr(session, field, value)

    async def _fail(self, session: PlanSession, payload: dict[str, Any]) -> PlanSession:
        """``fail`` 特判：任意状态 → failed + 落结构化 error（不可恢复错误）。

        IN-01 终态守护：已 ``done``/``failed`` 的会话再 ``fail`` 为幂等 no-op——
        不把已 ``done`` 无声回落 ``failed``、不二次覆盖首个诊断 ``error``（保留首因）。
        """
        if session.status in (PlanSessionStatus.DONE, PlanSessionStatus.FAILED):
            logger.info(
                "plan_session_fail_noop_terminal",
                session_id=str(session.id),
                status=session.status,
            )
            return session
        raw_error = payload.get("error")
        error = raw_error if isinstance(raw_error, dict) else {"message": str(raw_error)}
        applied = await self._fail_sync(session, error)
        if not applied:
            # WR-03：DB 行 status 已被并发/陈旧 advance 改写（如容器回调 barrier 把
            # researching 推进到 merging）。条件更新命中 0 行 → **不盲写覆盖**已正确推进
            # 的状态（否则把成功完成的编排错误置 failed，属状态损坏）。re-fetch DB status
            # 同步内存态后放弃 fail（保留已推进状态），不发 failed 事件。
            await self._refresh_status_sync(session)
            logger.info(
                "plan_session_fail_skip_concurrent_advance",
                session_id=str(session.id),
                current_status=session.status,
            )
            return session
        await self._emit_event(EVENT_PLAN_SESSION_FAILED, session, payload)
        return session

    @sync_to_async
    def _fail_sync(self, session: PlanSession, error: dict[str, Any]) -> bool:
        """以 ``status == 内存 from_status`` 为前置条件的原子 fail 更新（WR-03 防盲写覆盖）。

        镜像 ``_apply_transition_sync`` 的 TOCTOU 防线：``filter(id, status=from_status)
        .update(...)``；影响行数 != 1 表示 DB 行已被并发/陈旧 advance 改写或行不存在
        → 返回 ``False``（**不盲写覆盖**，绝不把已推进状态回落 failed），由调用方放弃 fail。
        ==1 才同步内存态并返回 ``True``。``update()`` 不触发 ``auto_now``，显式写 updated_at。
        """
        from_status = session.status
        updated = PlanSession.objects.filter(id=session.id, status=from_status).update(
            status=PlanSessionStatus.FAILED, error=error, updated_at=timezone.now()
        )
        if updated != 1:
            return False
        session.status = PlanSessionStatus.FAILED
        session.error = error
        return True

    @sync_to_async
    def _refresh_status_sync(self, session: PlanSession) -> None:
        """从 DB 重读 status 同步内存态（fail 被并发推进拒绝后，保持内存与 DB 一致）。"""
        fresh = PlanSession.objects.filter(id=session.id).values("status").first()
        if fresh is not None:
            session.status = fresh["status"]

    async def _emit_event(
        self, event_name: str, session: PlanSession, payload: dict[str, Any]
    ) -> None:
        """事件钩子（Phase 41 EVENT-01）：持久化 §15 信封行 ``PlanSessionEvent``。

        持久化一行 ``PlanSessionEvent``（``event==event_name``、``session==session``、
        ``work_item==session.work_item_id``、``payload==payload or {}``、``ts`` 默认 now），
        §15 统一信封 ``{event, session_id, work_item_id?, ts, payload}`` 的列拆解形态。

        **best-effort（绝不抛出影响转移）**：整体 try/except 包裹——DB 写失败只
        ``logger.warning``，绝不重新抛出（编排可靠性优先于事件完整性，T-41-01-02）。
        async 上下文禁裸 lazy-FK：用 ``session.work_item_id`` 标量（不访问
        ``session.work_item``），规避 Phase 38 CR-01 类。
        """
        logger.info(
            "plan_session_event",
            event_name=event_name,
            session_id=str(session.id),
            status=session.status,
        )
        try:
            await self._persist_event(event_name, session, payload)
        except Exception as exc:  # noqa: BLE001 — best-effort：事件持久化失败绝不阻断转移
            logger.warning(
                "plan_session_event_persist_failed",
                event_name=event_name,
                session_id=str(session.id),
                error=str(exc),
            )

    @sync_to_async
    def _persist_event(
        self, event_name: str, session: PlanSession, payload: dict[str, Any]
    ) -> None:
        PlanSessionEvent.objects.create(
            session=session,
            event=event_name,
            work_item=session.work_item_id,
            payload=payload or {},
        )
