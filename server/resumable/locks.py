"""实例锁封装：默认无操作（DB 行级 CAS 已保证 exactly-once），可选 Redis。

断点恢复的"同一任务只被一个进程续跑"由 ``ResumableTask`` 的 DB 原子 CAS
（``claim_expired``）保证——单实例与多副本都安全，**不依赖 Redis**。

本模块提供一个可选的集群级互斥：当配置 ``RESUMABLE_USE_REDIS_LOCK=true`` 且
Redis 可用时，用 ``SET NX PX`` 让"每轮恢复扫描"在集群内只有一个 Pod 执行，
减少多副本同时扫描的无谓争用。Redis 不可用 / 未启用时退化为始终"获取成功"，
正确性仍由 DB CAS 兜底。
"""

from __future__ import annotations

import uuid

import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)


def _redis_lock_url() -> str | None:
    """解析 Redis 锁连接 URL；未启用或无配置时返回 None。"""
    if not getattr(settings, "RESUMABLE_USE_REDIS_LOCK", False):
        return None
    url = getattr(settings, "REDIS_CHANNEL_LAYER_URL", None) or getattr(
        settings, "REDIS_URL", None
    )
    return url or None


class InstanceLock:
    """集群级互斥（可选 Redis）。作为上下文管理器使用。

    用法::

        with InstanceLock("resumable:recovery", ttl=60) as lock:
            if lock.acquired:
                run_recovery()

    Redis 未启用时 ``acquired`` 恒为 True（不阻止本地执行，DB CAS 仍是最终防线）。
    """

    def __init__(self, key: str, *, ttl: int = 60) -> None:
        self.key = key
        self.ttl = ttl
        self._token = uuid.uuid4().hex
        self._client = None
        self.acquired = False

    def __enter__(self) -> InstanceLock:
        url = _redis_lock_url()
        if url is None:
            # 未启用 Redis 锁：放行（正确性由 DB CAS 保证）。
            self.acquired = True
            return self
        try:
            import redis  # noqa: PLC0415  (channels-redis 已带 redis 依赖)

            self._client = redis.Redis.from_url(url)
            # SET key token NX PX ttl_ms —— 集群内只有一个进程能拿到。
            ok = self._client.set(
                self.key, self._token, nx=True, px=self.ttl * 1000
            )
            self.acquired = bool(ok)
        except Exception as exc:  # noqa: BLE001
            # Redis 异常不影响主流程：退化为放行，DB CAS 兜底去重。
            logger.warning("resumable_redis_lock_failed", key=self.key, error=str(exc))
            self.acquired = True
            self._client = None
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        client = self._client
        if client is None:
            return
        try:
            # 仅删除自己持有的 token（防误删他人锁）。
            current = client.get(self.key)
            if current is not None and current.decode() == self._token:
                client.delete(self.key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("resumable_redis_unlock_failed", key=self.key, error=str(exc))
        finally:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
