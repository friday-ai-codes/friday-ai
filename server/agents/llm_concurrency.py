"""LLM 凭证级并发限流（CONC-02）。

每个 ``ProviderCredential`` 可配 ``max_concurrency``（默认 50，0=不限）。chat /
深度分析 / 编码的 LLM 调用在发起前经 :func:`acquire_llm_slot` 按**凭证 id** 申请
一个并发槽位：

- 配置了 Redis（``settings.LLM_CONCURRENCY_REDIS_URL`` 非空）→ 用 **Redis 租约
  信号量**（sorted-set + Lua 原子 acquire + TTL 自愈 + 持有期自动续租），跨副本精确；
- 否则 → **进程内 asyncio.Semaphore** fallback（单进程精确，多进程各自计数，降级可用）。

超过该凭证上限时**排队等待**至 ``timeout``，再抛 :class:`LLMBusyError`（友好
「系统繁忙」），**不打到 provider 触发 429**。Redis 故障时 fail-soft 降级到进程内
信号量（绝不因限流基础设施不可用而阻断 LLM）。

``max_concurrency<=0`` 或 ``credential_id`` 为空 → no-op（不限流，零开销）。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import AsyncIterator

import structlog

logger = structlog.get_logger(__name__)


class LLMBusyError(Exception):
    """凭证级并发已满且等待超时——对外友好「系统繁忙」。"""

    def __init__(self, message: str = "系统繁忙，请稍后重试（该 Provider 凭证并发已达上限）") -> None:
        super().__init__(message)


# ---------------------------------------------------------------------------
# 进程内 fallback：按凭证 id 的 asyncio.Semaphore 注册表
# ---------------------------------------------------------------------------

_inprocess_semaphores: dict[str, tuple[asyncio.Semaphore, int]] = {}
_registry_lock = asyncio.Lock()


async def _get_inprocess_semaphore(key: str, capacity: int) -> asyncio.Semaphore:
    """获取/创建某凭证的进程内信号量；容量变化时按新容量重建。"""
    async with _registry_lock:
        existing = _inprocess_semaphores.get(key)
        if existing is None or existing[1] != capacity:
            sem = asyncio.Semaphore(capacity)
            _inprocess_semaphores[key] = (sem, capacity)
            return sem
        return existing[0]


# ---------------------------------------------------------------------------
# Redis 租约信号量
# ---------------------------------------------------------------------------

# 原子 acquire：先按 TTL 清过期租约，再判活跃数 < max 则加本 token。
_ACQUIRE_LUA = """
local now = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local maxc = tonumber(ARGV[3])
local token = ARGV[4]
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - ttl)
local count = redis.call('ZCARD', KEYS[1])
if count < maxc then
  redis.call('ZADD', KEYS[1], now, token)
  redis.call('PEXPIRE', KEYS[1], ttl)
  return 1
end
return 0
"""

_POLL_INTERVAL_SECONDS = 0.2

_redis_clients: dict[str, object] = {}


def _get_redis_client(url: str):
    """懒创建并缓存 async redis 客户端（按 url）。失败抛异常由调用方 fail-soft 接住。"""
    client = _redis_clients.get(url)
    if client is None:
        import redis.asyncio as aioredis  # 局部 import：仅 Redis 路径需要

        client = aioredis.from_url(url, encoding="utf-8", decode_responses=True)
        _redis_clients[url] = client
    return client


def _slot_key(credential_id: str) -> str:
    return f"friday:llm:slots:{credential_id}"


def _log_slot_acquired(
    key_id: str, max_concurrency: int, backend: str, started: float
) -> None:
    """获到槽位后旁路上报排队耗时（QPS/queue_wait，per RATE-02），best-effort。

    category=sampling（高频内部步骤）+ component=llm；带 call_source（chokepoint
    读 contextvar 兜底）。观测失败吞掉，绝不影响限流放行。
    """
    try:
        from agents.call_source import get_call_source

        logger.info(
            "llm_slot_acquired",
            credential_id=key_id,
            max_concurrency=max_concurrency,
            backend=backend,
            queue_wait_ms=int((time.perf_counter() - started) * 1000),
            call_source=get_call_source(),
            category="sampling",
            component="llm",
        )
    except Exception:  # noqa: BLE001 — 观测绝不反噬限流
        pass


async def _redis_acquire(
    client, key: str, token: str, max_concurrency: int, lease_ttl: float, timeout: float
) -> bool:
    """轮询式 Redis 租约 acquire；成功 True，超时 False。"""
    ttl_ms = int(lease_ttl * 1000)
    deadline = time.monotonic() + timeout
    while True:
        now_ms = int(time.time() * 1000)
        acquired = await client.eval(_ACQUIRE_LUA, 1, key, now_ms, ttl_ms, max_concurrency, token)
        if int(acquired) == 1:
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


async def _redis_renew_loop(client, key: str, token: str, lease_ttl: float) -> None:
    """持有期内周期性续租，防长流（深度分析数分钟）租约提前过期被他人抢占。"""
    interval = max(lease_ttl / 3.0, 1.0)
    ttl_ms = int(lease_ttl * 1000)
    try:
        while True:
            await asyncio.sleep(interval)
            now_ms = int(time.time() * 1000)
            with contextlib.suppress(Exception):
                await client.zadd(key, {token: now_ms})
                await client.pexpire(key, ttl_ms)
    except asyncio.CancelledError:
        return


async def _redis_release(client, key: str, token: str) -> None:
    with contextlib.suppress(Exception):
        await client.zrem(key, token)


# ---------------------------------------------------------------------------
# 公开入口
# ---------------------------------------------------------------------------


def _resolve_settings() -> tuple[str, float, float]:
    from django.conf import settings

    url = getattr(settings, "LLM_CONCURRENCY_REDIS_URL", "") or ""
    timeout = float(getattr(settings, "LLM_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS", 60.0))
    lease_ttl = float(getattr(settings, "LLM_CONCURRENCY_LEASE_TTL_SECONDS", 900))
    return url, timeout, lease_ttl


@contextlib.asynccontextmanager
async def acquire_llm_slot(
    credential_id: object,
    max_concurrency: int,
    *,
    timeout: float | None = None,
    lease_ttl: float | None = None,
) -> AsyncIterator[None]:
    """按凭证申请一个 LLM 并发槽位（async context manager）。

    Args:
        credential_id: ProviderCredential id（None/空 → 不限流）。
        max_concurrency: 该凭证并发上限（<=0 → 不限流）。
        timeout: 等待槽位的最长秒数（None 取 settings 默认）。
        lease_ttl: Redis 租约 TTL 秒（None 取 settings 默认）。

    Raises:
        LLMBusyError: 等待超时（凭证级并发已满）。
    """
    if not credential_id or max_concurrency is None or max_concurrency <= 0:
        # 不限流：零开销直接放行
        yield
        return

    key_id = str(credential_id)
    # 72-02：排队计时起点（获到槽位后算 queue_wait_ms）。
    _acquire_start = time.perf_counter()
    url, default_timeout, default_lease = _resolve_settings()
    eff_timeout = default_timeout if timeout is None else timeout
    eff_lease = default_lease if lease_ttl is None else lease_ttl

    # --- Redis 路径（配置了 url 时优先；故障 fail-soft 降级进程内）---
    if url:
        try:
            client = _get_redis_client(url)
            token = uuid.uuid4().hex
            key = _slot_key(key_id)
            acquired = await _redis_acquire(
                client, key, token, max_concurrency, eff_lease, eff_timeout
            )
            if not acquired:
                # 业务可归因限流（per 72-01 classify_error 归 business）：category=caller。
                logger.info(
                    "llm_slot_busy_timeout",
                    credential_id=key_id,
                    max_concurrency=max_concurrency,
                    backend="redis",
                    category="caller",
                    component="llm",
                )
                raise LLMBusyError()
            _log_slot_acquired(key_id, max_concurrency, "redis", _acquire_start)
            renew_task = asyncio.create_task(_redis_renew_loop(client, key, token, eff_lease))
            try:
                yield
            finally:
                renew_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await renew_task
                await _redis_release(client, key, token)
            return
        except LLMBusyError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Redis 不可用：fail-soft 降级进程内信号量，绝不阻断 LLM
            logger.warning(
                "llm_slot_redis_unavailable_fallback_inprocess",
                credential_id=key_id,
                error=str(exc),
            )

    # --- 进程内 fallback ---
    sem = await _get_inprocess_semaphore(key_id, max_concurrency)
    try:
        await asyncio.wait_for(sem.acquire(), timeout=eff_timeout)
    except (TimeoutError, asyncio.TimeoutError) as exc:
        # 业务可归因限流（per 72-01 classify_error 归 business）：category=caller。
        logger.info(
            "llm_slot_busy_timeout",
            credential_id=key_id,
            max_concurrency=max_concurrency,
            backend="inprocess",
            category="caller",
            component="llm",
        )
        raise LLMBusyError() from exc
    _log_slot_acquired(key_id, max_concurrency, "inprocess", _acquire_start)
    try:
        yield
    finally:
        sem.release()


__all__ = ["LLMBusyError", "acquire_llm_slot"]
