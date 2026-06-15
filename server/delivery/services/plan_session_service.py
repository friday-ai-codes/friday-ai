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

from delivery.models import PlanSession, PlanSessionStatus

logger = structlog.get_logger(__name__)

__all__ = ["PlanSessionService"]


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
_PERSISTABLE_FIELDS = ("decomposition", "current_plan_version", "event_time")


class PlanSessionService:
    """PlanSession 状态变更唯一入口（INV-6 精神）。"""

    async def create_session(
        self,
        entrypoint: str,
        *,
        work_item: Any = None,
        decomposition: dict | None = None,
        event_time: Any = None,
    ) -> PlanSession:
        """建 PlanSession（status 默认 decomposing）—— engine/入口层建会话的入口。"""
        return await self._create_session_sync(entrypoint, work_item, decomposition, event_time)

    @sync_to_async
    def _create_session_sync(
        self,
        entrypoint: str,
        work_item: Any,
        decomposition: dict | None,
        event_time: Any,
    ) -> PlanSession:
        return PlanSession.objects.create(
            entrypoint=entrypoint,
            work_item=work_item,
            decomposition=decomposition or {},
            event_time=event_time,
        )

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

        allowed = _ALLOWED.get(session.status, {})
        if event not in allowed:
            raise ValueError(
                f"非法状态转移：from_status={str(session.status)} event={event}；"
                f"该状态合法 event={sorted(allowed)}"
            )
        to_status = allowed[event]
        await self._apply_transition_sync(session, to_status, payload)
        await self._emit_event(event, session, payload)
        return session

    @sync_to_async
    def _apply_transition_sync(
        self, session: PlanSession, to_status: str, payload: dict[str, Any]
    ) -> None:
        """合法转移落库：set status + payload 中可落库字段 + save（update_fields 精确）。"""
        session.status = to_status
        update_fields = ["status", "updated_at"]
        for field in _PERSISTABLE_FIELDS:
            if field in payload:
                setattr(session, field, payload[field])
                update_fields.append(field)
        session.save(update_fields=update_fields)

    async def _fail(self, session: PlanSession, payload: dict[str, Any]) -> PlanSession:
        """``fail`` 特判：任意状态 → failed + 落结构化 error（不可恢复错误）。"""
        raw_error = payload.get("error")
        error = raw_error if isinstance(raw_error, dict) else {"message": str(raw_error)}
        await self._fail_sync(session, error)
        await self._emit_event("plan.session.failed", session, payload)
        return session

    @sync_to_async
    def _fail_sync(self, session: PlanSession, error: dict[str, Any]) -> None:
        session.status = PlanSessionStatus.FAILED
        session.error = error
        session.save(update_fields=["status", "error", "updated_at"])

    async def _emit_event(
        self, event_name: str, session: PlanSession, payload: dict[str, Any]
    ) -> None:
        """事件钩子占位（best-effort no-op + log）。

        事件 taxonomy 真实发射在 Phase 41（DOMAIN §15）；本 phase 仅留钩子点，
        **绝不抛出影响转移**（best-effort）。
        """
        logger.info(
            "plan_session_event",
            event_name=event_name,
            session_id=str(session.id),
            status=session.status,
        )
