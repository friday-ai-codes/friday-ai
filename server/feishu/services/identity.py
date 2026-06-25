"""飞书人员↔Friday 用户身份映射解析/写入（IDENT-01）。

- ``resolve_feishu_user(feishu_user_key=None, open_id=None) -> User | None``：单一解析入口。
  手动绑定优先于 JIT；**未映射 fail-soft 返回 None**（不抛、不阻断主流程），调用方保留原始
  飞书 id 可后补绑定。供 Phase 78（飞书拉人带身份）、Phase 81（Cursor 上报归因）复用，
  与可观测"谁触发"同源。
- ``bind_feishu_user(user, feishu_user_key=None, open_id=None, source="manual") -> FeishuUserBinding``：
  单一写入入口，``get_or_create`` 幂等。

**绝不**把飞书凭证/原始 id 之外的敏感串写日志（脱敏规范）；本模块日志仅记 user_key/open_id
末段提示 + 命中与否，不记任何令牌。
"""

from __future__ import annotations

from typing import Any

import structlog
from asgiref.sync import sync_to_async

from feishu.models import FeishuBindingSource, FeishuUserBinding

logger = structlog.get_logger(__name__)

__all__ = ["resolve_feishu_user", "bind_feishu_user"]


async def resolve_feishu_user(
    feishu_user_key: str | None = None, open_id: str | None = None
) -> Any | None:
    """解析飞书人员到 Friday ``User``（手动优先；未映射 fail-soft 返回 None）。

    Args:
        feishu_user_key: 飞书 user_key（任一可空）。
        open_id: 飞书 open_id（任一可空）。

    Returns:
        命中的 ``User``，或 None（未映射，调用方保留原始 id）。
    """
    if not feishu_user_key and not open_id:
        return None
    return await _resolve_sync(feishu_user_key or "", open_id or "")


@sync_to_async
def _resolve_sync(feishu_user_key: str, open_id: str) -> Any | None:
    qs = FeishuUserBinding.objects.select_related("user")

    filters = []
    if feishu_user_key:
        filters.append({"feishu_user_key": feishu_user_key})
    if open_id:
        filters.append({"open_id": open_id})

    matched = None
    for f in filters:
        # 手动绑定优先：同键命中时先取 manual。
        binding = (
            qs.filter(**f)
            .order_by(
                # manual 排在前（'jit' > 'manual' 字典序，故 manual 升序在前）
                "source",
                "-updated_at",
            )
            .first()
        )
        if binding is not None:
            matched = binding
            break

    if matched is None:
        logger.info(
            "feishu_user_unmapped",
            has_user_key=bool(feishu_user_key),
            has_open_id=bool(open_id),
            component="initiatives",
            category="sampling",
        )
        return None
    return matched.user


async def bind_feishu_user(
    *,
    user: Any,
    feishu_user_key: str = "",
    open_id: str = "",
    source: str = FeishuBindingSource.MANUAL,
) -> FeishuUserBinding:
    """创建/取飞书人员↔用户绑定（单一写入入口，get_or_create 幂等）。

    Args:
        user: Friday ``User`` 实例。
        feishu_user_key / open_id: 飞书标识（至少一个非空）。
        source: 绑定来源（manual/jit）。

    Returns:
        既有或新建的 ``FeishuUserBinding``。
    """
    if not feishu_user_key and not open_id:
        raise ValueError("feishu_user_key 与 open_id 至少提供一个")
    return await _bind_sync(user, feishu_user_key, open_id, source)


@sync_to_async
def _bind_sync(
    user: Any, feishu_user_key: str, open_id: str, source: str
) -> FeishuUserBinding:
    binding, _created = FeishuUserBinding.objects.get_or_create(
        feishu_user_key=feishu_user_key,
        open_id=open_id,
        user=user,
        defaults={"source": source},
    )
    return binding
