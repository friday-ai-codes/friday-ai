"""stranded 派发恢复的周期任务壳（31u 任务队列完整化收尾）。

**触发方**：apscheduler 的 ``recover_stranded_dispatch_sessions`` job
（``agents/management/commands/runapscheduler.py``，与 ``recover_stalled_blueprint_sessions``
同一调度器）。⛔ 不新起定时体系、⛔ 不加 durable periodic——理由：procrastinate 路径的
「无 runner 等待」已被派发任务体的 re-defer backoff 全覆盖，唯一漏网是 in-process
fallback（SQLite dev）重启丢 job 与「入队成功但 job 链意外中断」的极端窗口，这正是
apscheduler 保险丝的定位（与 ``tasks/blueprint_recovery_tasks.py`` 完全同构且两个环境都跑）。

**语义 = 兜底恢复，不是主路径**：派发主链是 ``dispatch()`` 的「快照持久化 + defer」；
本任务只捡「滞留 PENDING 且有派发快照」的会话重新入队。判据与动作全在
``runners.dispatcher.arecover_stranded_dispatch_sessions``（active assignment 跳过、
单条隔离、任务体状态守卫兜底幂等），本模块只是调度壳，照 ``tasks/
blueprint_recovery_tasks.py`` 范式保住「service 管业务、tasks 管调度」的分层。
归因 **system**（scheduler 上下文，无触发用户）。

整体 ``try/except`` 兜底 → warning + 全零计数：恢复失败绝不上抛回 job wrapper，
更不该打断 scheduler 主循环。
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["arecover_stranded_dispatch_sessions_task"]

_COMPONENT = "runners"


async def arecover_stranded_dispatch_sessions_task() -> dict[str, int]:
    """扫描滞留的待派发会话并重新入队 durable 派发任务。

    返回 ``{"scanned": n, "skipped_active": n, "requeued": n, "failed": n}``（恒定四键）。
    """
    try:
        from runners.dispatcher import arecover_stranded_dispatch_sessions

        return await arecover_stranded_dispatch_sessions()
    except Exception as exc:  # noqa: BLE001 — 绝不上抛：恢复失败不该打断 scheduler
        from common.logging import redact_secrets_in_text

        logger.warning(
            "dispatch_recovery_task_failed",
            category="caller",
            component=_COMPONENT,
            initiated_by_user_id="system",
            error=redact_secrets_in_text(str(exc)),
        )
        return {"scanned": 0, "skipped_active": 0, "requeued": 0, "failed": 0}
