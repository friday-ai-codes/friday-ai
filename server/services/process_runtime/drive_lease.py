"""会话驱动租约 —— 「同一会话同时只允许一个驱动者跑 stage handler」的唯一实现。

为什么需要它
============

编排引擎的驱动者是**多入口、跨进程**的：durable worker 的续驱 job、容器回调的 fan-out
barrier、确认门/作答动作端点、以及周期性的僵尸会话扫描。这些入口彼此不知道对方的存在，
而 :meth:`ProcessEngine.advance` 原先唯一的并发意识是**写回那一瞬间**的 CAS——
handler 本体（含分钟级的 LLM 调用与开线程）没有任何保护。

后果不是「状态被写坏」（CAS 拦住了写回），而是**同一份活被完整地干了 N 遍**：曾观测到一次
蓝图会话的 AI 审查被并发跑了 7 遍，7 份 token 全部烧掉、同样 4 个 BLOCKER 被登记成 30 多条
重复线程，最后只有 1 份写回生效。触发它的是一个自我放大的循环——回调 barrier 是**电平判据**
（「都产出了吗」一旦为真就恒为真），于是每个后到的回调都再入队一次续驱；并发续驱又让
``dispatch_plans`` 读到陈旧快照而重复落库，重复落库再触发新回调。

⛔ **为什么不能用别的东西代替**

- 进程内 ``asyncio.Lock`` / 线程锁：驱动者跨进程（worker 与 web 是两个进程），拦不住。
- ``stage_state`` 里放标记：各 stage handler 会**整桶覆写**自己那个键，标记会被无声抹掉
  （同类事故见 ``blueprint_review._bucket`` 的 T-114-14 注释）。
- Postgres advisory lock：会话级锁绑在**连接**上，而这里的 handler 横跨大量 ``await`` 与
  ``sync_to_async`` 线程池调度，连接不稳定；事务级 advisory lock 则要求整个 handler 待在
  一个长事务里，分钟级 LLM 调用期间占着连接不可接受。
- durable 队列的 ``lock=``：它**只在 procrastinate 后端有效**，in-process fallback 明确
  忽略该参数（见 ``durable/backends.py``），而且僵尸会话扫描根本不走队列。

所以判据只能落在**行上**：一条 ``UPDATE ... WHERE`` 的原子 CAS，对所有入口、所有后端、
所有进程一致成立。

语义
====

- **抢占**：单条 UPDATE 带 ``WHERE 租约为空 OR 已过期``，返回受影响行数；1 = 抢到，0 = 别人
  正在驱动。
- **可重入**：同一驱动上下文内嵌套获取（续驱 helper 包住循环、循环里的 ``advance`` 再获取一次）
  直接放行，由最外层负责释放。靠 contextvar 识别，不查库。
- **超时自愈**：持有者崩溃/被杀不会让会话永久卡死，租约过期后下一个驱动者可接管。
  ⚠️ :data:`DEFAULT_LEASE_SECONDS` 必须**大于最慢的一次 stage handler**（AI 审查含多次 LLM
  调用），否则会退化成「上一个还在跑、下一个就接管」——那正是本模块要消灭的场景。
- **绝不反噬业务**：抢占/释放的 DB 异常一律吞掉并**按「抢到了」处理**（fail-open）。
  租约是省钱的优化，不是正确性屏障——DB 抖动时宁可重复跑一次，也不能让编排整个停摆。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["DEFAULT_LEASE_SECONDS", "asession_drive_lease"]

# 租约有效期：必须覆盖最慢的一次 stage handler。蓝图 AI 审查一轮包含机械规则 + 一次
# goal-backward LLM 调用 + 批量开线程，实测分钟级；取 15 分钟留足余量。
# ⛔ 不要为了「卡死能快点恢复」把它调小：调小的直接后果是并发驱动重新出现（上一个还在跑
# LLM，下一个就认为租约过期而接管），而卡死本身有僵尸会话扫描兜底。
DEFAULT_LEASE_SECONDS = 900

# 当前上下文已持有的租约：``{session_id: token}``。每个驱动跑在自己的后台任务里 ⇒ 各自
# 独立的 contextvars 上下文，不会串味。
#
# ⚠️ **必须按 session_id 分别记，不能只记一个 token**：僵尸会话扫描会在**同一个上下文**里
# 逐条驱动不同会话，若可重入判据是「本上下文是否持有任意租约」，那么第一条会话拿到租约后，
# 后面每一条都会被误判成「外层已持有」而**完全跳过抢占** —— 租约对扫描这条路径直接失效，
# 而扫描恰恰是绕过队列 lock 的那条路径。
_DRIVE_OWNER: ContextVar[dict[str, str]] = ContextVar("process_runtime_drive_owner", default={})


@asynccontextmanager
async def asession_drive_lease(
    session_id: Any, *, ttl_seconds: int = DEFAULT_LEASE_SECONDS, reason: str = ""
) -> AsyncIterator[bool]:
    """会话驱动租约上下文；``yield`` 出「是否该由本上下文驱动」。

    用法::

        async with asession_drive_lease(session.id, reason="advance") as acquired:
            if not acquired:
                return session          # 别人正在驱动，本次原地返回（⛔ 不是错误）
            ...                          # 跑 handler

    Args:
        session_id: ``ConvergenceSession`` 主键。假值直接放行（调用方传空是 bug，
            但不该因此卡住驱动）。
        ttl_seconds: 租约有效期秒数，见 :data:`DEFAULT_LEASE_SECONDS` 的取值纪律。
        reason: 观测用的驱动来源标记（advance / drive_loop / recovery_scan…）。

    Yields:
        ``True`` = 本上下文持有租约（或外层已持有 / 已 fail-open）；``False`` = 别人在驱动。
    """
    if not session_id:
        yield True
        return

    key = str(session_id)
    held = _DRIVE_OWNER.get()

    # 可重入：**同一会话**的外层驱动器已持有 ⇒ 直接放行，释放归外层（内层释放会让外层裸奔）。
    if key in held:
        yield True
        return

    token = uuid.uuid4().hex
    acquired = await _aacquire(session_id, token, ttl_seconds)
    if not acquired:
        logger.info(
            "session_drive_lease_busy",
            category="sampling",
            component="process_runtime",
            session_id=key,
            reason=reason,
        )
        yield False
        return

    # 整份替换而不是原地改：contextvar 的值被子任务共享，原地 mutate 会让兄弟任务看见
    # 本任务的持有记录，可重入判据随之串味。
    reset = _DRIVE_OWNER.set({**held, key: token})
    try:
        yield True
    finally:
        _DRIVE_OWNER.reset(reset)
        await _arelease(session_id, token)


async def _aacquire(session_id: Any, token: str, ttl_seconds: int) -> bool:
    """原子抢占：``UPDATE ... WHERE 租约为空 OR 已过期``，受影响行数即成败。

    fail-open：DB 异常按「抢到了」处理（见模块 docstring 的最后一条纪律）。
    """
    try:
        from django.db.models import Q
        from django.utils import timezone

        from delivery.models import ConvergenceSession

        now = timezone.now()
        updated = await (
            ConvergenceSession.objects.filter(id=session_id)
            .filter(Q(drive_lease_until__isnull=True) | Q(drive_lease_until__lte=now))
            .aupdate(
                drive_lease_owner=token,
                drive_lease_until=now + timedelta(seconds=max(int(ttl_seconds or 0), 1)),
            )
        )
        return bool(updated)
    except Exception as exc:  # noqa: BLE001 — 租约是优化不是正确性屏障，绝不反噬驱动
        logger.warning(
            "session_drive_lease_acquire_failed",
            category="sampling",
            component="process_runtime",
            session_id=str(session_id),
            error=str(exc),
        )
        return True


async def _arelease(session_id: Any, token: str) -> None:
    """释放：``WHERE owner = 本 token`` —— 绝不误放**别人**已接管的租约。

    「别人接管」在正常路径下不该发生，但本次驱动超过 TTL 时会：那时租约已被下一个驱动者
    合法抢走，此处按 owner 比对后不动它。
    """
    try:
        from delivery.models import ConvergenceSession

        await ConvergenceSession.objects.filter(id=session_id, drive_lease_owner=token).aupdate(
            drive_lease_owner="", drive_lease_until=None
        )
    except Exception as exc:  # noqa: BLE001 — 释放失败靠 TTL 自愈，绝不上抛
        logger.warning(
            "session_drive_lease_release_failed",
            category="sampling",
            component="process_runtime",
            session_id=str(session_id),
            error=str(exc),
        )
