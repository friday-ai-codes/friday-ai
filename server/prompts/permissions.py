"""Prompt API 权限辅助函数。

方法级 RBAC 切换（contract）：
- 读操作（GET）：任何 IsAuthenticated 用户可读系统级 prompt；项目级需 VIEWER+
- 写操作（POST / PATCH / DELETE / activate）：
    * 系统级 → 仅 superuser
    * 项目级 → 仅项目 ADMIN

所有辅助函数都是 `async def`，由 adrf async view 直接 `await`。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from asgiref.sync import sync_to_async
from rest_framework import status
from rest_framework.response import Response

from permissions.models import SpaceRole
from permissions.services import PermissionService
from prompts.models import Prompt, PromptScope

if TYPE_CHECKING:
    from rest_framework.request import Request


async def _require_write_permission(
    request: "Request | Any",
    prompt: Prompt,
) -> Response | None:
    """检查对给定 Prompt 的写权限（security mitigation）。

    流程：
        1. superuser → 放行
        2. system scope → 非 superuser 直接 403
        3. project scope → `PermissionService.has_project_access(user, project, ADMIN)`

    Returns:
        Response 403 如果无权限；None 如果有权限（调用方继续执行）。
    """
    user = request.user
    if user.is_superuser:
        return None

    if prompt.scope == PromptScope.SYSTEM:
        return Response(
            {
                "error": "permission_denied",
                "detail": "系统级 prompt 仅超级管理员可修改",
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    # project scope —— 走 PermissionService 的 sync API（sync_to_async 包装）
    has_access = await sync_to_async(PermissionService.has_project_access)(
        user,
        prompt.space,
        SpaceRole.ADMIN,
    )
    if not has_access:
        return Response(
            {
                "error": "permission_denied",
                "detail": "项目级 prompt 仅项目管理员可修改",
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


async def _require_read_permission(
    request: "Request | Any",
    prompt: Prompt,
) -> Response | None:
    """检查对给定 Prompt 的读权限（security mitigation）。

    - 系统级 prompt → 任何 IsAuthenticated 用户可读
    - 项目级 prompt → 需 VIEWER+ 项目角色（或 superuser）
    """
    user = request.user
    if user.is_superuser:
        return None
    if prompt.scope == PromptScope.SYSTEM:
        return None
    has_access = await sync_to_async(PermissionService.has_project_access)(
        user,
        prompt.space,
        SpaceRole.VIEWER,
    )
    if not has_access:
        return Response(
            {
                "error": "permission_denied",
                "detail": "项目级 prompt 仅项目成员可读",
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


async def _require_project_write_permission(
    request: "Request | Any",
    project: Any,
) -> Response | None:
    """创建项目级 Prompt 前的预检 —— 验证用户在目标 project 有 ADMIN 角色。

    用于 POST /api/prompts/ 新建项目级 Prompt 时，还没有 Prompt 实例可传给
    `_require_write_permission`，因此需要一个直接拿 project 的变体。
    """
    user = request.user
    if user.is_superuser:
        return None
    has_access = await sync_to_async(PermissionService.has_project_access)(
        user,
        project,
        SpaceRole.ADMIN,
    )
    if not has_access:
        return Response(
            {
                "error": "permission_denied",
                "detail": "项目级 prompt 仅项目管理员可创建",
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


async def _require_project_read_permission(
    request: "Request | Any",
    project: Any,
) -> Response | None:
    """列出项目级 Prompt 前的预检 —— 验证用户在目标 project 至少是 VIEWER。"""
    user = request.user
    if user.is_superuser:
        return None
    has_access = await sync_to_async(PermissionService.has_project_access)(
        user,
        project,
        SpaceRole.VIEWER,
    )
    if not has_access:
        return Response(
            {
                "error": "permission_denied",
                "detail": "项目级 prompt 仅项目成员可读",
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    return None
