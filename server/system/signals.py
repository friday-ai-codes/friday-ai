"""SystemSetting 改动后的副作用：失效 settings cache + 重建相关单例 client。

设计动机：
- ``services.qdrant_service.QdrantService`` 持有进程级单例 ``_client``。
- 之前 ``QdrantService.health_check()`` 会无条件 ``reset_client()`` 兜底"配置变了
  自动生效"——但定时健康检查与索引 upsert 并发时，会把正在用的 httpx 连接池
  关掉，触发 60s 假超时（线上事故，详见 ``services/qdrant_service.py``
  ``health_check`` docstring）。
- 现把"配置变更后失效缓存 client"放到设置写入路径，作为唯一可信触发点。

另外本模块还负责 SQLite 全局 PRAGMA：开启 WAL + busy_timeout，避免索引
图谱写入阶段（4000+ 文件 × 多次 abulk_create）拖死所有 ASGI 接口。
"""

from __future__ import annotations

from typing import Any

import structlog
from django.db.backends.signals import connection_created
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import SettingKeys, SystemSetting

logger = structlog.get_logger(__name__)


_QDRANT_KEYS = {SettingKeys.QDRANT_URL, SettingKeys.QDRANT_API_KEY}

# 运行时日志配置键：命中即重设过滤级别（LOG-06，写时即时生效无需重启）。
_LOG_KEYS = {
    SettingKeys.LOG_LEVEL,
    SettingKeys.LOG_COMPONENT_LEVELS,
    SettingKeys.LOG_STACK_THRESHOLD,
    SettingKeys.LOG_SAMPLING_INITIAL,
    SettingKeys.LOG_SAMPLING_RATE,
    SettingKeys.LOG_RETENTION_DAYS,
    SettingKeys.LOG_RETENTION_SIZE,
}


def _invalidate_setting_cache(key: str) -> None:
    """settings_service._get_raw 用 Django cache 缓存设置；写入后必须失效。"""
    try:
        from django.core.cache import cache

        from .settings_service import _cache_key

        cache.delete(_cache_key(key))
    except Exception as exc:  # 失效失败不应阻止业务路径
        logger.warning("system_setting_cache_invalidate_failed", key=key, error=str(exc))


def _apply_log_config_if_needed(key: str) -> None:
    """命中 ``LOG_*`` 键 → 即时重设过滤级别（缓存已先失效，apply 读到新值）。

    best-effort：失败仅告警、绝不阻塞设置写入路径（观测代码永不反噬业务）。
    级别类立即生效；采样/堆栈/保留等配置经 60s 缓存失效后由各自 consumer 读到新值。
    """
    if key not in _LOG_KEYS:
        return
    try:
        from common.logging import apply_log_level

        apply_log_level()
    except Exception as exc:  # noqa: BLE001 — 调级别失败不阻塞设置写入
        logger.warning("log_runtime_config_apply_failed", key=key, error=str(exc))


def _reset_qdrant_client_if_needed(key: str) -> None:
    if key not in _QDRANT_KEYS:
        return
    try:
        from services.qdrant_service import QdrantService

        QdrantService.reset_client()
        logger.info(
            "qdrant_client_reset_due_to_setting_change",
            key=key,
        )
    except Exception as exc:
        logger.warning(
            "qdrant_client_reset_failed",
            key=key,
            error=str(exc),
        )


@receiver(post_save, sender=SystemSetting)
def on_system_setting_saved(
    sender: type[SystemSetting], instance: SystemSetting, **kwargs: Any
) -> None:
    _invalidate_setting_cache(instance.key)
    _reset_qdrant_client_if_needed(instance.key)
    _apply_log_config_if_needed(instance.key)


@receiver(post_delete, sender=SystemSetting)
def on_system_setting_deleted(
    sender: type[SystemSetting], instance: SystemSetting, **kwargs: Any
) -> None:
    _invalidate_setting_cache(instance.key)
    _reset_qdrant_client_if_needed(instance.key)
    _apply_log_config_if_needed(instance.key)


# ---------------------------------------------------------------------------
# SQLite 全局 PRAGMA：WAL + busy_timeout
# ---------------------------------------------------------------------------
#
# 默认 rollback journal 模式下，写连接持排他锁，所有读连接被阻塞。索引大仓库
# 时图谱阶段 4000+ 文件 × ~5 次 abulk_create 会让 background_runner 长时间
# 占着写锁，ASGI 接口的 ORM 读全部排队 → 用户看到 "接口都待处理" 假死。
#
# WAL 模式让读写并发；busy_timeout 给偶发竞争一个等待窗口，避免立刻
# 抛 OperationalError。
@receiver(connection_created)
def configure_sqlite_pragmas(connection: Any, **kwargs: Any) -> None:
    if connection.vendor != "sqlite":
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA busy_timeout = 5000;")
            # NORMAL fsync 节奏比 FULL 快很多，配合 WAL 仍是 crash-safe。
            cursor.execute("PRAGMA synchronous = NORMAL;")
    except Exception as exc:  # 不应阻塞应用启动
        logger.warning("sqlite_pragma_setup_failed", error=str(exc))
