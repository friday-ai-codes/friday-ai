"""「本项目关联仓」解析（D-2 宽口径并集，ROUTE-01/02 的分组依据来源）。

分组依据 = 项目所属 ``Space.repositories`` **∪** 该 Space 下 ``Project`` 的
``RepoAssociation`` 中 ``status=verified`` 的行。

（此处刻意不写成实例化形态 ``RepoAssociation`` + 紧跟括号——`test_repo_association_inv6_guard`
的旁路写表扫描按行匹配该形态，文档字符串写成那样会被误判为旁路写入。本模块只读不写。）

为什么取宽口径（107-CONTEXT D-2 裁决）：ROUTE-01/02 的需求原文是「哪些是本平台内
的」「未关联当前平台，可能涉及跨组协作」——分界线在平台/组级别，而不是单个工作项的
已验证关联。若取窄口径（只算 verified 关联），`in_project` 组会几乎恒空，分组呈现上线
即失去信息量（与 global 组恒空是同一类失效，只是换了一边）。

返回值的两种「空」语义**必须区分**，它直接决定 `block_order` 的形状：

- ``None`` = 调用方**无项目上下文**（work_item 不存在 / 无 space / space 不存在）
  → `_apply_presentation` 走 `has_project_context=False`，`block_order == ["global"]`。
- ``frozenset()`` = **有**项目上下文但该项目零关联仓 → 仍启用分组呈现，
  `block_order` 恒长度 2（`in_project` 组为空是一条有信息量的事实）。

分组依据**不做** `index_status` 过滤：分组是「归属」语义，未索引的仓同样属于本项目；
而候选本身只可能来自已索引的仓，故过滤与否对结果无影响，不过滤语义更干净。
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

import structlog
from asgiref.sync import sync_to_async

logger = structlog.get_logger(__name__)

__all__ = ["aresolve_grouping_repo_ids"]

_COMPONENT = "repo_router_v2"


async def aresolve_grouping_repo_ids(
    *,
    work_item_id: Any = None,
    space_id: Any = None,
) -> frozenset[str] | None:
    """解析「本项目关联仓」的宽口径并集（D-2）。

    Args:
        work_item_id: ``delivery.WorkItem`` 主键（编排入口）；经 ``WorkItem.space``
            解析 Space。
        space_id: ``projects.Space`` 主键（chat 入口，无 Project 实例时也够用）。
            与 ``work_item_id`` 同时给出时**以 work_item_id 为准**。

    Returns:
        ``frozenset[str]`` 仓库 id 集（id 一律 ``str()`` 归一，与
        ``RepoRouteCandidateV2.repo_id`` 类型一致）；无项目上下文返回 ``None``。
        本函数**绝不抛**——解析失败一律降级为 ``None`` 或只返回 space 半边。
    """
    started = perf_counter()
    source = "work_item" if work_item_id is not None else "space"
    if work_item_id is not None and space_id is not None:
        _log_scope(
            "repo_group_scope_ambiguous_input",
            source="work_item",
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )

    space = await _aresolve_space(work_item_id=work_item_id, space_id=space_id)
    if space is None:
        return None

    space_ids = await _aspace_repository_ids(space)

    # verified 半边是并集的**可选**部分：它失败不该毁掉整个分组（退化成 space 半边仍
    # 是可用的分组依据），故整块 try/except 降级。
    verified_ids: frozenset[str] = frozenset()
    try:
        project = await _aresolve_project(space)
        if project is not None:
            from initiatives.services.repo_association_service import (
                RepoAssociationService,
            )

            rows = await RepoAssociationService().get_verified_associations(
                project=project
            )
            verified_ids = frozenset(
                str(row.get("repository_id") or "")
                for row in (rows or [])
                if row.get("repository_id")
            )
    except Exception as exc:  # noqa: BLE001 — 可选半边失败即降级，绝不冒泡
        from common.logging import redact_secrets_in_text

        logger.warning(
            "repo_group_scope_verified_half_failed",
            reason=redact_secrets_in_text(str(exc)),
            error_type=type(exc).__name__,
            component=_COMPONENT,
            category="sampling",
        )

    union = space_ids | verified_ids
    _log_scope(
        "repo_group_scope_resolved",
        source=source,
        space_repo_count=len(space_ids),
        verified_repo_count=len(verified_ids),
        union_count=len(union),
        duration_ms=round((perf_counter() - started) * 1000, 2),
    )
    return union


def _log_scope(event: str, **kv: Any) -> None:
    """分组依据解析的采样事件（best-effort，绝不反噬解析主流程）。"""
    try:
        logger.debug(event, component=_COMPONENT, category="sampling", **kv)
    except Exception:  # noqa: BLE001 — 观测 best-effort
        pass


@sync_to_async
def _aresolve_space(*, work_item_id: Any, space_id: Any) -> Any:
    """解析 Space（work_item_id 优先），解析不到返回 None（同步 ORM 经 sync_to_async）。"""
    from projects.models import Space

    if work_item_id is not None:
        from delivery.models import WorkItem

        try:
            wi = (
                WorkItem.objects.select_related("space").filter(id=work_item_id).first()
            )
        except Exception:  # noqa: BLE001 — 非法主键等一律当无上下文
            return None
        return wi.space if wi is not None else None

    if space_id is None:
        return None
    try:
        return Space.objects.filter(id=space_id).first()
    except Exception:  # noqa: BLE001 — 非法主键等一律当无上下文
        return None


@sync_to_async
def _aspace_repository_ids(space: Any) -> frozenset[str]:
    """取 ``Space.repositories`` 的 id 集（空集合法，表「该空间零关联仓」）。"""
    try:
        return frozenset(str(r) for r in space.repositories.values_list("id", flat=True))
    except Exception:  # noqa: BLE001 — stub/未关联时返回空集，不抛
        return frozenset()


@sync_to_async
def _aresolve_project(space: Any) -> Any:
    """解析 Space 对应的 Project（优先 ``feishu_project_key`` 命中，否则首个）。

    规则逐字对齐 ``workflows/nodes/integrations/board_split_review._aresolve_project``
    与 ``RepoAssociationService._aresolve_project``，但**不复用**二者：前者会让
    ``codegraph`` 反向依赖 ``workflows``（分层倒置），后者是私有方法。此处只做一次
    最小等价查询，规则变更时三处需同步。
    """
    if space is None:
        return None
    from initiatives.models import Project

    qs = Project.objects.filter(space=space)
    project_key = getattr(space, "feishu_project_key", "") or ""
    if project_key:
        matched = qs.filter(feishu_project_key=project_key).first()
        if matched is not None:
            return matched
    return qs.first()
