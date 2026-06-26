"""ProjectDoc 渲染内容 read-through 缓存（SYNC-05）。

落点为独立基础设施薄层（不绑定 DocSyncService），统一缓存键与降级语义：
- read-through：``get_doc_render`` 命中即返回；未命中由调用方读 DB 渲染后 ``set_doc_render`` 回填。
- 失效：写时 / 收飞书 ``drive.file.edit_v1`` 事件后调 ``invalidate_doc_render(doc_id)``，
  用 **delete 而非 set 空**（下次读再回填，避免缓存空值穿透 / 脏读，Pitfall 7）。
- TTL 兜底：``set`` 默认用 ``settings.DOC_RENDER_CACHE_TTL``，作"漏失效"的过期保险。
- 降级：复用 Django ``CACHES`` 框架（django_redis ``IGNORE_EXCEPTIONS`` / LocMem 自动回退）。
  本模块再叠一层 try/except 兜底：任何缓存异常都静默降级直读 DB（返回 None / no-op），
  **绝不反噬渲染主流程**——缓存是优化、不是真相源（DB canonical）。

观测：缓存故障记 ``doc_render_cache_degraded``（category=sampling / component=doc_sync /
debug 级），只记 ``doc_id`` 与异常类型，**绝不记渲染正文**（含飞书文档片段，T-83-05-INFO）。
"""

from __future__ import annotations

from typing import Any

import structlog
from django.conf import settings
from django.core.cache import cache

logger = structlog.get_logger(__name__)

# 统一缓存键前缀：``projdoc:render:{doc_id}``。
# Django CACHES 已配 KEY_PREFIX="friday"，最终落 redis key 形如 ``friday:1:projdoc:render:<id>``。
_KEY_TEMPLATE = "projdoc:render:{doc_id}"


def doc_render_cache_key(doc_id: Any) -> str:
    """渲染缓存键：``projdoc:render:{doc_id}``。

    doc_id 统一 ``str()`` 归一，避免 int / UUID 等类型产生不同键命中不同槽。
    """
    return _KEY_TEMPLATE.format(doc_id=str(doc_id))


def get_doc_render(doc_id: Any) -> str | None:
    """read-through 读：命中返回缓存渲染值，未命中 / 缓存故障返回 None（降级直读 DB）。

    整段 try/except 兜底：redis 抖动 / 不可用时（即便 IGNORE_EXCEPTIONS 已开，仍防御性
    再吞一层）静默返回 None，让调用方回退 DB 渲染，绝不抛回主流程。
    """
    key = doc_render_cache_key(doc_id)
    try:
        return cache.get(key)
    except Exception as exc:  # noqa: BLE001 — 缓存故障绝不反噬渲染主流程（best-effort 降级直读 DB）
        logger.debug(
            "doc_render_cache_degraded",
            category="sampling",
            component="doc_sync",
            op="get",
            doc_id=str(doc_id),
            error_type=type(exc).__name__,
        )
        return None


def set_doc_render(doc_id: Any, value: str, *, timeout: int | None = None) -> None:
    """read-through 回填：未命中读 DB 渲染后写缓存；TTL 默认 ``DOC_RENDER_CACHE_TTL``。

    缓存故障静默吞掉（回填失败只是少一次加速，下次读再尝试），绝不反噬主流程。
    """
    key = doc_render_cache_key(doc_id)
    ttl = timeout if timeout is not None else getattr(settings, "DOC_RENDER_CACHE_TTL", 300)
    try:
        cache.set(key, value, timeout=ttl)
    except Exception as exc:  # noqa: BLE001 — 回填失败绝不反噬主流程
        logger.debug(
            "doc_render_cache_degraded",
            category="sampling",
            component="doc_sync",
            op="set",
            doc_id=str(doc_id),
            error_type=type(exc).__name__,
        )


def invalidate_doc_render(doc_id: Any) -> None:
    """写时 / 收飞书事件失效：按 doc_id ``delete`` 缓存（**绝不 set 空**，Pitfall 7）。

    delete 后下次读 miss 再回填最新 DB 渲染，保证写后最终一致；缓存故障静默吞掉。
    """
    key = doc_render_cache_key(doc_id)
    try:
        cache.delete(key)
    except Exception as exc:  # noqa: BLE001 — 失效失败绝不反噬主流程（TTL 兜底过期）
        logger.debug(
            "doc_render_cache_degraded",
            category="sampling",
            component="doc_sync",
            op="invalidate",
            doc_id=str(doc_id),
            error_type=type(exc).__name__,
        )
