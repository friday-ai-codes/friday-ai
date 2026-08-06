"""项目级人工仓库/分支绑定的「固定路由」解析（repo binding pin）。

项目详情页允许把项目与 ``(repository, branch)`` 手动绑定（``initiatives.ProjectBranch``，
``source=manual``）。存在这类绑定时，技术方案编排的 route stage **跳过自动仓库路由**
（能力树检索 + LLM），直接把绑定仓当作候选（``router_version="project_binding"``）；
调研容器也按绑定分支 checkout，而不是仓库的 ``default_branch``。

语义边界：

- **只认 ``source=manual``**：``plan`` / ``coding`` 来源是流水线自动写入（如编码节点
  push 后的 feature 分支），拿它们固定后续路由会形成自反馈回路。
- 同一仓多条手动分支绑定时取**最新创建**的那条（一次调研一仓一分支）。
- 本模块**只读不写、绝不抛**：任何解析失败一律降级为「无绑定」（空列表 / 空串），
  路由回退到既有自动链路，不比现状差。

Project 解析规则（work_item → space → project）逐字对齐
``codegraph/services/repo_group_scope._aresolve_project``（优先 ``feishu_project_key``
命中，否则首个）；规则变更时两处需同步。
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

import structlog
from asgiref.sync import sync_to_async

logger = structlog.get_logger(__name__)

__all__ = [
    "PINNED_ROUTER_VERSION",
    "aresolve_pinned_bindings",
    "apinned_branch_for",
    "asession_pinned_bindings",
]

_COMPONENT = "process_runtime"

# route 结果里标识「项目手动绑定固定路由」的 router_version 受控值。
PINNED_ROUTER_VERSION = "project_binding"


async def aresolve_pinned_bindings(
    *,
    project_id: Any = None,
    work_item_id: Any = None,
) -> list[dict[str, str]]:
    """解析项目的手动仓库/分支绑定（route stage 固定路由的依据）。

    Args:
        project_id: ``initiatives.Project`` 主键（蓝图链从 ``decomposition["project_id"]``
            取）。与 ``work_item_id`` 同时给出时**以 project_id 为准**。
        work_item_id: ``delivery.WorkItem`` 主键（旧链入口）；经 work_item → space →
            project 解析。

    Returns:
        ``[{"repository_id", "repository_name", "branch_name"}]``（每仓一条，取最新
        手动绑定）；无项目上下文 / 无手动绑定 / 解析失败一律返回 ``[]``（绝不抛）。
    """
    started = perf_counter()
    try:
        bindings = await _aload_manual_bindings(project_id=project_id, work_item_id=work_item_id)
    except Exception as exc:  # noqa: BLE001 — 固定路由 best-effort，失败回退自动路由
        from common.logging import redact_secrets_in_text

        logger.warning(
            "repo_binding_pin_resolve_failed",
            reason=redact_secrets_in_text(str(exc)),
            error_type=type(exc).__name__,
            category="sampling",
            component=_COMPONENT,
        )
        return []
    if bindings:
        try:
            logger.debug(
                "repo_binding_pin_resolved",
                binding_count=len(bindings),
                duration_ms=round((perf_counter() - started) * 1000, 2),
                category="sampling",
                component=_COMPONENT,
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort
            pass
    return bindings


async def asession_pinned_bindings(session: Any) -> list[dict[str, str]]:
    """按会话上下文解析固定绑定：蓝图链取 ``decomposition["project_id"]``，否则走 work_item。"""
    decomposition = getattr(session, "decomposition", None)
    decomposition = decomposition if isinstance(decomposition, dict) else {}
    project_id = str(decomposition.get("project_id") or "").strip() or None
    work_item_id = getattr(session, "work_item_id", None)
    if project_id is None and work_item_id is None:
        return []
    return await aresolve_pinned_bindings(project_id=project_id, work_item_id=work_item_id)


async def apinned_branch_for(session: Any, repository_id: Any) -> str:
    """取该仓在会话所属项目下的手动绑定分支（无绑定 / 失败返回空串）。

    调研容器派发用：绑定存在时用它替代 ``Repository.default_branch``。
    """
    repo_id = str(repository_id or "")
    if not repo_id:
        return ""
    for binding in await asession_pinned_bindings(session):
        if binding["repository_id"] == repo_id:
            return binding["branch_name"]
    return ""


@sync_to_async
def _aload_manual_bindings(*, project_id: Any, work_item_id: Any) -> list[dict[str, str]]:
    """同步 ORM 查询（经 sync_to_async 桥接）：project 解析 + 手动绑定去重。"""
    project = _resolve_project_sync(project_id=project_id, work_item_id=work_item_id)
    if project is None:
        return []

    from initiatives.models import BranchSource, ProjectBranch

    rows = (
        ProjectBranch.objects.filter(project=project, source=BranchSource.MANUAL)
        .select_related("repository")
        .order_by("-created_at")
    )
    bindings: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        repo_id = str(row.repository_id)
        if repo_id in seen:
            continue
        seen.add(repo_id)
        bindings.append(
            {
                "repository_id": repo_id,
                "repository_name": str(getattr(row.repository, "name", "") or ""),
                "branch_name": str(row.branch_name or ""),
            }
        )
    return bindings


def _resolve_project_sync(*, project_id: Any, work_item_id: Any) -> Any:
    """解析 Project：project_id 直取；否则 work_item → space → project（镜像既有规则）。"""
    from initiatives.models import Project

    if project_id:
        return Project.objects.filter(id=project_id).first()

    if work_item_id is None:
        return None
    from delivery.models import WorkItem

    work_item = WorkItem.objects.select_related("space").filter(id=work_item_id).first()
    if work_item is None or work_item.space is None:
        return None
    space = work_item.space
    qs = Project.objects.filter(space=space)
    project_key = getattr(space, "feishu_project_key", "") or ""
    if project_key:
        matched = qs.filter(feishu_project_key=project_key).first()
        if matched is not None:
            return matched
    return qs.first()
