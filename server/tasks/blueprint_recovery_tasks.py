"""蓝图僵尸会话恢复的周期任务壳（116 事故修复）。

**触发方**：既有 apscheduler 的 ``recover_stalled_blueprint_sessions`` job
（``agents/management/commands/runapscheduler.py``，与 ``remind_blueprint_clarifications``
同一调度器）。⛔ 不新起定时体系。

**语义 = 兜底恢复，不是主路径**：作答 / 确认门动作后的续驱仍在请求内联跑（被取消时
移交 background_runner）；本任务只捡「进程重启 / 请求被杀导致续驱丢失」留下的滞留会话。
判据与动作全在 ``services.process_runtime.blueprint_resume.arecover_stalled_blueprint_sessions``
（人审接管的蓝图一律跳过；合法等待中的会话由驱动器的 pause 短路原地放回），本模块只是
调度壳，照 ``tasks/blueprint_reminder_tasks.py`` 范式保住「service 管业务、tasks 管调度」
的分层。归因 **system**（scheduler 上下文，无触发用户）。

整体 ``try/except`` 兜底 → warning + 全零计数：恢复失败绝不上抛回 job wrapper，
更不该打断 scheduler 主循环。
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["arecover_stalled_blueprint_sessions_task"]

_COMPONENT = "blueprint_recovery"


async def arecover_stalled_blueprint_sessions_task() -> dict[str, int]:
    """扫描滞留的蓝图会话并重驱到下一个挂起点或终态。

    返回 ``{"scanned": n, "skipped_human_owned": n, "recovered": n, "unchanged": n}``
    （恒定四键）。
    """
    try:
        from services.process_runtime.blueprint_resume import (
            arecover_stalled_blueprint_sessions,
        )

        return await arecover_stalled_blueprint_sessions()
    except Exception as exc:  # noqa: BLE001 — 绝不上抛：恢复失败不该打断 scheduler
        from common.logging import redact_secrets_in_text

        logger.warning(
            "blueprint_recovery_task_failed",
            category="caller",
            component=_COMPONENT,
            initiated_by_user_id="system",
            error=redact_secrets_in_text(str(exc)),
        )
        return {"scanned": 0, "skipped_human_owned": 0, "recovered": 0, "unchanged": 0}
