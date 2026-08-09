"""内存图服务的**读取层闸门** —— 仓库可读性校验与 exclusion 收口（Phase 121，GRAPH-04）。

问题背景
========
图服务会被 MCP 工具、AI 对话、后台任务与工作流四类调用方共用，其中 ``repository_id``
与 ``user`` 都是不可信输入。如果每个调用方各自校验，迟早有一条路径漏掉「已软删」或
「未索引」这两道；更危险的是 exclusion —— ``.env`` / ``*.pem`` / ``id_rsa`` 的符号名与
文件路径一旦漏进图，就会同时泄漏进 Phase 122–127 的**每一个**上层工具输出。

方案（单一校验点 + 装配阶段过滤）
==================================
本模块把两件事各收口成一个函数：

- :func:`ensure_repository_readable` —— 仓库可读性的**唯一**校验点。存在性、软删、
  索引态三道判定合并在这里，per-user ACL 的扩展位也留在这里
  （:func:`_check_user_acl`）。⛔ 未索引仓库抛 :class:`~services.code_graph.model.GraphNotIndexed`，
  **绝不返回空图**：空图会被上层误读为「没有影响」，让 agent 得出「这次改动安全」的
  错误结论。未索引是「不知道」，不是「没有」。
- :func:`build_matcher_and_fingerprint` / :func:`make_path_exclusion_memo` ——
  exclusion 判定的取用面。判定逻辑本身**不在这里实现**，全部复用
  ``services/exclusion.py``（全仓唯一事实源）；本模块只负责把它接进图装配链路，
  并额外算出一份精确的规则指纹供缓存签名比对。

边界与残余风险
==============
① **fail-closed 优先于一切**：matcher 构造失败 → 整仓拒绝（抛
   :class:`~services.code_graph.model.GraphAccessDenied`），⛔ 绝不降级成「不过滤」。
   降级放行等于把被排除文件泄漏进所有图工具的输出，比拒绝服务严重得多。

② **过滤发生在装配阶段，不是输出阶段**：被排除的 ``Symbol.file_path`` 对应的节点
   根本不进节点集，其邻接边随之消失（节点丢弃由 Plan 121-05 落地）。输出阶段过滤
   挡不住计数、深度分组等旁路泄漏。

③ **残余风险（如实记录）**：图缓存是 **per-worker 进程内存**。某用户的权限若在缓存
   建立**之后**被收回，进程里那个图对象本身不会被撤销——但
   :func:`ensure_repository_readable` 在**每次** ``get_graph`` 都执行（不因缓存命中而
   跳过），因此实际访问仍会被拦下。真正的残余风险只存在于「per-user ACL 落地之后、
   精细到符号级的授权」场景，该项已在 121-CONTEXT.md 的 Deferred 列表。
"""

from __future__ import annotations

import uuid
from typing import Any, Final

import structlog

from services.code_graph.model import GraphAccessDenied, GraphNotIndexed

logger = structlog.get_logger(__name__)

# 事件名常量（形态对齐 ``codegraph/lsp/volar_pool.py`` L42–47）。
# ⚠️ 前缀不得缩写：``graph_build_*`` 已被 ``services/graph_builder.py`` 占用、
#    ``galaxy_cache_*`` 已被 ``codegraph/galaxy/cache.py`` 占用，缩写会让两条链路的
#    日志混在一起筛不开。
_EVENT_ACCESS_DENIED: Final[str] = "code_graph_access_denied"

__all__ = ["ensure_repository_readable"]


def _initiated_by(user: Any | None) -> str:
    """取触发用户标识；无触发用户（后台/预热路径）记 ``system``（LOGGING-SPEC §3）。"""
    if user is None:
        return "system"
    user_id = getattr(user, "id", None) or getattr(user, "pk", None)
    return str(user_id) if user_id is not None else "system"


def _log_access_denied(*, repository_id: Any, reason: str, user: Any | None) -> None:
    """拒绝出口的结构化埋点。观测 best-effort —— 任何异常吞掉，绝不反噬主流程。"""
    try:
        logger.warning(
            _EVENT_ACCESS_DENIED,
            component="code_graph",
            category="sampling",
            repository_id=str(repository_id),
            reason=reason,
            initiated_by_user_id=_initiated_by(user),
        )
    except Exception:  # noqa: BLE001 — 观测失败绝不反噬业务（不是安全降级分支）
        pass


def _check_user_acl(user: Any | None, repo: Any) -> None:
    """per-user 仓库 ACL 的**扩展点**（当前为空实现，恒 ``return None``）。

    本仓当前的仓库层只有「认证 + 存在性」两道（``repositories/permissions.py``：
    「配合 IsAuthenticated 使用，任意登录用户均可访问存在的仓库」）。本相位
    **不发明 ACL 模型**，只把校验点收口——未来若需要引入仓库级 ACL，在此处扩展
    ownership 检查即可，全部图访问自动继承，无需逐个调用方改造。

    落地 ACL 时的出口约定：拒绝一律抛 :class:`GraphAccessDenied`，并在抛出前调
    :func:`_log_access_denied`（``reason="acl_denied"``），与其余三道判定同形。
    """
    return None


async def ensure_repository_readable(user: Any | None, repository_id: str) -> None:
    """仓库可读性的单一校验点。可读则静默返回 ``None``，否则抛异常。

    四道判定，任何一道不过都是**显式异常**，没有「返回空结果」这种出口：

    1. ``repository_id`` 走 :class:`uuid.UUID` 解析（ASVS V5 输入校验），非法即拒。
    2. ``aget(id=..., is_deleted=False)``：``DoesNotExist`` 与软删**合并成同一出口**，
       不向调用方泄漏「这个仓库存在但你看不到」这种存在性差异。
    3. ``index_status != INDEXED`` → :class:`GraphNotIndexed`。⛔ 不返回空图。
    4. :func:`_check_user_acl` 扩展点（当前空实现）。

    :param user: 触发用户（可为 ``None``，表示后台/系统路径），用于埋点归因与未来 ACL。
    :param repository_id: 仓库主键（字符串或 UUID 均可）。
    :raises GraphAccessDenied: ``repository_id`` 非法，或仓库不存在/已软删。
    :raises GraphNotIndexed: 仓库尚未建立索引。
    """
    from repositories.models import IndexStatus, Repository

    try:
        repo_uuid = uuid.UUID(str(repository_id))
    except (ValueError, TypeError, AttributeError):
        _log_access_denied(
            repository_id=repository_id, reason="invalid_repository_id", user=user
        )
        raise GraphAccessDenied(
            "repository_id 非法", {"repository_id": str(repository_id)}
        ) from None

    try:
        repo = await Repository.objects.aget(id=repo_uuid, is_deleted=False)
    except Repository.DoesNotExist:
        # 「不存在」与「已软删」共用同一句文案与同一个异常类型（不泄漏存在性差异）。
        _log_access_denied(
            repository_id=repository_id, reason="not_found_or_deleted", user=user
        )
        raise GraphAccessDenied(
            "仓库不存在或已删除", {"repository_id": str(repository_id)}
        ) from None

    if repo.index_status != IndexStatus.INDEXED:
        _log_access_denied(repository_id=repository_id, reason="not_indexed", user=user)
        raise GraphNotIndexed(
            "仓库尚未建立索引",
            {"repository_id": str(repository_id), "index_status": str(repo.index_status)},
        )

    _check_user_acl(user, repo)
