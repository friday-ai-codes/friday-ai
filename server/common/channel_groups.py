"""channel layer 分组订阅/退订的 fail-soft 收口（Q86L-02）。

为什么需要这个模块
==================
``channels_redis`` 的 ``group_add`` 会走 redis-py 异步连接池，而该池**可能把一条已死的
TCP 连接交给调用方**：

1. ``redis/asyncio/connection.py`` 的 ``is_connected`` 只判 ``_reader``/``_writer`` 非空，
   **不看 transport 是否活着** → ``connect()`` 对死连接直接 return。
2. ``ConnectionPool.ensure_connection()`` 只在 ``(ConnectionError, OSError)`` 时重连；
   死 transport 若 ``can_read_destructive()`` 干净返回 False，就被原样发给调用方。
3. ``send_packed_command`` 只把 ``OSError`` 映射成 ``ConnectionError``，而 uvloop 抛的是
   ``RuntimeError: unable to perform operation on <TCPTransport closed=True ...>``，
   落进 ``except BaseException`` 原样重抛。
4. ``Retry._supported_errors`` 默认不含 ``RuntimeError`` → **永不重试**。

结果：远端 Redis 抖动后，``RuntimeError`` 直穿 ``consumer.connect()`` 逃进 ASGI 服务器，
uvicorn 在 ``send_500_response()`` 里再抛一次级联异常，客户端（Go runner / 浏览器）
随即无脑重连风暴。

为什么「重试 1 次」就够
======================
``send_packed_command`` 的 ``except BaseException`` 分支在 ``raise`` 之前已经
``await self.disconnect(nowait=True)``——死连接在异常抛出时就被置为「未连接」，随后由
``execute_command`` 的 ``finally: pool.release(conn)`` 放回空闲队列。于是下一次
``get_connection()`` → ``ensure_connection()`` → ``connect()`` 会**新建 TCP 连接**。
也就是说第一次失败恰好把死连接清掉，紧接着的第二次尝试落在新连接上。
故这里固定尝试 2 次、不 sleep：把一次用户可见的握手拒绝转成透明恢复。
Redis 真挂了则第二次同样失败，最坏代价由每次尝试的 ``asyncio.wait_for`` 上界封顶。
⛔ 不要改成无限重试——那是自造重试风暴。

容错与观测都绝不反噬业务
========================
``safe_group_add`` 只返回 bool、``safe_group_discard`` 恒返回 None，业务异常一律不外抛；
``asyncio.CancelledError`` 必须**穿透**（否则任务取消语义被吞掉）。埋点整段
``try/except`` 包裹，日志自身故障也不影响 WS 握手。异常文本经 ``redact_secrets_in_text``
脱敏后只留 ``error`` / ``error_type``，⛔ 不记 traceback、不记连接串。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from common.log_context import LogSource
from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

# 单次 group 操作上界（秒）：不依赖 redis kwargs 是否生效，对任意 channel layer 实现都成立。
_GROUP_OP_TIMEOUT_SECONDS: float = 5.0

# 尝试次数：首次失败已把死连接清出池，重试 1 次即可（见模块 docstring「为什么重试 1 次」）。
_GROUP_ADD_MAX_ATTEMPTS: int = 2


def _elapsed_ms(started_at: float) -> int:
    """自 ``started_at``（``time.perf_counter()``）起的耗时毫秒（与既有 WS 指标算法一致）。"""
    return max(int((time.perf_counter() - started_at) * 1000), 0)


def _log_group_add_recovered(
    *,
    component: str,
    group: str,
    initiated_by_user_id: str,
    attempt: int,
    previous_error_type: str,
    duration_ms: int,
) -> None:
    """重试救回（sampling/info）。埋点故障绝不反噬业务。"""
    try:
        logger.info(
            "ws_group_add_recovered",
            component=component,
            group=group,
            source=LogSource.WS.value,
            initiated_by_user_id=initiated_by_user_id,
            attempt=attempt,
            previous_error_type=previous_error_type,
            duration_ms=duration_ms,
            category="sampling",
        )
    except Exception:  # noqa: BLE001 — 观测代码绝不反噬业务
        pass


def _log_group_add_failed(
    *,
    component: str,
    group: str,
    initiated_by_user_id: str,
    attempts: int,
    exc: BaseException,
    duration_ms: int,
) -> None:
    """彻底失败（caller/warning）：用户可归因的一次订阅失败，全量记录。"""
    try:
        logger.warning(
            "ws_group_add_failed",
            component=component,
            group=group,
            source=LogSource.WS.value,
            initiated_by_user_id=initiated_by_user_id,
            attempts=attempts,
            error_type=type(exc).__name__,
            error=redact_secrets_in_text(str(exc)),
            duration_ms=duration_ms,
            category="caller",
        )
    except Exception:  # noqa: BLE001 — 观测代码绝不反噬业务
        pass


def _log_group_discard_failed(
    *,
    component: str,
    group: str,
    initiated_by_user_id: str,
    exc: BaseException,
    duration_ms: int,
) -> None:
    """退订失败（sampling/debug）：断连清理属高频路径，只留采样级线索。"""
    try:
        logger.debug(
            "ws_group_discard_failed",
            component=component,
            group=group,
            source=LogSource.WS.value,
            initiated_by_user_id=initiated_by_user_id,
            error_type=type(exc).__name__,
            error=redact_secrets_in_text(str(exc)),
            duration_ms=duration_ms,
            category="sampling",
        )
    except Exception:  # noqa: BLE001 — 观测代码绝不反噬业务
        pass


async def safe_group_add(
    channel_layer: Any,
    group: str,
    channel: str,
    *,
    component: str,
    initiated_by_user_id: str = "system",
) -> bool:
    """订阅 channel layer 分组；失败返回 False（绝不抛业务异常），CancelledError 穿透。

    成功路径**不发**事件（group 订阅是每条 WS 连接必经的热路径，成功侧刷 INFO 违反
    级别纪律）；仅「重试救回」与「彻底失败」各发一条。

    Args:
        channel_layer: consumer 的 ``self.channel_layer``。
        group: 分组名。
        channel: consumer 的 ``self.channel_name``。
        component: LOGGING-SPEC §5 已登记组件名（如 ``runners``）。
        initiated_by_user_id: 触发用户；WS 不过统一中间件，故显式传，无用户主体记 ``system``。

    Returns:
        True 表示已成功加入分组；False 表示调用方应以「可重试」语义拒绝/降级。
    """
    started_at = time.perf_counter()
    last_exc: BaseException | None = None
    for attempt in range(1, _GROUP_ADD_MAX_ATTEMPTS + 1):
        try:
            await asyncio.wait_for(
                channel_layer.group_add(group, channel),
                timeout=_GROUP_OP_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            raise  # 取消语义必须穿透：绝不把「任务被取消」误判成「Redis 故障」
        except Exception as exc:  # noqa: BLE001 — Redis 抖动一律 fail-soft，异常不外抛
            last_exc = exc
            continue
        if attempt > 1 and last_exc is not None:
            _log_group_add_recovered(
                component=component,
                group=group,
                initiated_by_user_id=initiated_by_user_id,
                attempt=attempt,
                previous_error_type=type(last_exc).__name__,
                duration_ms=_elapsed_ms(started_at),
            )
        return True

    if last_exc is not None:
        _log_group_add_failed(
            component=component,
            group=group,
            initiated_by_user_id=initiated_by_user_id,
            attempts=_GROUP_ADD_MAX_ATTEMPTS,
            exc=last_exc,
            duration_ms=_elapsed_ms(started_at),
        )
    return False


async def safe_group_discard(
    channel_layer: Any,
    group: str,
    channel: str,
    *,
    component: str,
    initiated_by_user_id: str = "system",
) -> None:
    """退订分组；任何失败都吞掉（断连清理绝不反噬），CancelledError 穿透。

    断连本就是终态：退订失败最坏只是让一条已死 channel 在 Redis 分组里多留一会儿，
    由 channels_redis 的过期机制回收——远不值得把异常抛进 ``disconnect()``。
    """
    started_at = time.perf_counter()
    try:
        await asyncio.wait_for(
            channel_layer.group_discard(group, channel),
            timeout=_GROUP_OP_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        raise  # 取消语义必须穿透
    except Exception as exc:  # noqa: BLE001 — 退订失败一律吞掉
        _log_group_discard_failed(
            component=component,
            group=group,
            initiated_by_user_id=initiated_by_user_id,
            exc=exc,
            duration_ms=_elapsed_ms(started_at),
        )


__all__ = ["safe_group_add", "safe_group_discard"]
