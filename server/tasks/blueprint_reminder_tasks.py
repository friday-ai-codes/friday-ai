"""蓝图澄清超时提醒的周期任务壳（Phase 114-05，CLAR-04）。

**触发方**：既有 apscheduler 的 ``remind_blueprint_clarifications`` job
（``agents/management/commands/runapscheduler.py``，仓库同步轮询已在用的那一个）。
⛔ **不新起定时体系**：不加 cron / systemd timer / 第二个 ``BackgroundScheduler``
实例——多份调度会让同一条线程被并行提醒多次，而 ``last_reminded_at`` 的周期锚点
挡不住同一 tick 内的并发。job 侧 ``max_instances=1`` + flock 单实例契约是唯一防线。

**语义 = 提醒，不是兜底修复**：⛔ 不自动作答、不改蓝图状态、不判失败。CLAR-04 的
定夺是「pending 超时保持 pending + 按可配周期提醒」——自动作答会把 AI 的猜测冒充成
人的决策写进 ``decision_log``，判失败则会把「还没人来看」误报成「流程坏了」。

**但提醒本身有界（Phase 117，WAIT-01）**：达到 ``pending_reminder_max`` 的线程落
``expired_at`` 后退出扫描面、不再收提醒（计入返回值第五键 ``expired``）。到期
⛔ **不改线程状态、不改蓝图状态** —— 只是「不再催」，未决澄清照旧阻塞 confirm。

**分层**：业务逻辑（扫描面 / 到期判据 / 提醒对象名单 / 周期锚点写回）全在
``delivery.services.blueprint_review_action.aremind_clarification_threads``；本模块只是
调度壳，照 ``tasks/doc_sync_poll.py`` 范式保住「service 管业务、tasks 管调度」的分层。
归因 **system**（scheduler 上下文，无触发用户）。

整体 ``try/except`` 兜底 → warning + 全零计数：提醒失败绝不上抛回 job wrapper，
更不该打断 scheduler 主循环。
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["aremind_blueprint_clarifications"]

_COMPONENT = "blueprint_reminder"


async def aremind_blueprint_clarifications() -> dict[str, int]:
    """扫描 ``needs_clarification`` 蓝图上到期的 blocking 澄清线程并提醒。

    返回 ``{"scanned": n, "due": n, "reminded": n, "skipped": n, "expired": n}``
    （恒定五键；``expired`` 是 117 追加的「本轮新到期线程数」）。
    """
    try:
        from delivery.services.blueprint_review_action import aremind_clarification_threads

        return await aremind_clarification_threads()
    except Exception as exc:  # noqa: BLE001 — 绝不上抛：提醒失败不该打断 scheduler
        from common.logging import redact_secrets_in_text

        logger.warning(
            "blueprint_reminder_task_failed",
            category="caller",
            component=_COMPONENT,
            initiated_by_user_id="system",
            error=redact_secrets_in_text(str(exc)),
        )
        return {"scanned": 0, "due": 0, "reminded": 0, "skipped": 0, "expired": 0}
