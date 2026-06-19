"""进程角色判定 helper（DURABLE-02 的判据来源）。

`FRIDAY_PROCESS_ROLE` 决定一个进程是 web / worker / scheduler / migrate / test
中的哪一种，从而决定它是否应该执行"仅 web 进程才该跑"的启动副作用
（reconcile / sweep / recovery 等）。worker / migrate 进程跑这些副作用会误杀
在途任务或在迁移期报业务表不存在。

本模块**独立读 env、不依赖 Django settings**：它会在 `AppConfig.ready()` 这种
非常早的启动期被调用（settings 可能尚未完全就绪），且供 Plan 02 的三处 apps.py
消费，必须零 Django 依赖以避免循环 import。
"""

from __future__ import annotations

import os

import structlog

logger = structlog.get_logger(__name__)

# 默认角色：保持既有单进程部署零回归（不设 env 即 web，照常跑所有启动副作用）。
DEFAULT_ROLE = "web"


def current_role() -> str:
    """返回归一化后的当前进程角色（小写、去空白），缺省 ``"web"``。"""
    return os.environ.get("FRIDAY_PROCESS_ROLE", DEFAULT_ROLE).strip().lower() or DEFAULT_ROLE


def should_run_startup_side_effects(
    *,
    job: str,
    allowed: frozenset[str] = frozenset({"web"}),
) -> bool:
    """判定当前进程是否应执行某项 web-only 启动副作用。

    Args:
        job: 副作用名（仅用于短路日志，便于排查为何某项启动任务没跑）。
        allowed: 允许执行该副作用的角色集合，默认仅 ``{"web"}``。

    Returns:
        role ∈ allowed → True；否则记一条 info 级日志（角色 + job 名）后返回 False，
        不静默跳过。
    """
    role = current_role()
    if role in allowed:
        return True
    logger.info("startup_side_effect_skipped_by_role", role=role, job=job)
    return False


__all__ = ["DEFAULT_ROLE", "current_role", "should_run_startup_side_effects"]
