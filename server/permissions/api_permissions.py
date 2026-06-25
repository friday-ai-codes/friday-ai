"""DRF 权限类：项目级分级权限控制。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from accounts.models import User

import structlog
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from .models import SpaceRole
from .services import PermissionService

logger = structlog.get_logger(__name__)


class IsSuperUser(BasePermission):
    """要求 is_superuser。用于系统设置、Runner 管理等全局端点。"""

    message = "仅超级管理员可访问"

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_superuser
        )


class IsProjectMember(BasePermission):
    """要求用户是项目成员（任意角色 viewer+）。

    用于 object-level 权限检查。has_permission 仅验证认证状态，
    has_object_permission 检查项目 membership。
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(
        self, request: Request, view: APIView, obj: Any
    ) -> bool:
        if request.user.is_superuser:
            return True

        project = _get_project(obj)
        if project is None:
            return False

        return PermissionService.has_project_access(
            cast("User", request.user), project, SpaceRole.VIEWER
        )


class IsProjectAdmin(BasePermission):
    """要求用户是项目管理员（admin+）。

    用于项目配置、成员管理等管理操作。
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(
        self, request: Request, view: APIView, obj: Any
    ) -> bool:
        if request.user.is_superuser:
            return True

        project = _get_project(obj)
        if project is None:
            return False

        return PermissionService.has_project_access(
            cast("User", request.user), project, SpaceRole.ADMIN
        )


class ProjectRolePermission(BasePermission):
    """通用角色权限类，根据 HTTP method 自动分级。

    - GET/HEAD/OPTIONS → viewer+（只读）
    - POST/PUT/PATCH/DELETE → member+（写操作）

    子类可覆盖 write_min_role 属性来调整写操作的最低角色要求。
    """

    # 写操作的最低角色，子类可覆盖（如 admin+ 用于配置端点）
    write_min_role: str = SpaceRole.MEMBER

    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(
        self, request: Request, view: APIView, obj: Any
    ) -> bool:
        if request.user.is_superuser:
            return True

        project = _get_project(obj)
        if project is None:
            return False

        # 读操作：viewer+
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return PermissionService.has_project_access(
                cast("User", request.user), project, SpaceRole.VIEWER
            )

        # 写操作：由 write_min_role 控制
        return PermissionService.has_project_access(
            cast("User", request.user), project, self.write_min_role
        )


def _get_project(obj: Any) -> Any:
    """从对象链式查找关联的 project。

    支持以下链路：
    - obj.space
    - obj.workflow.space
    - obj.workflow_execution.workflow.space
    - obj.config.workflow.space（WebhookLog）
    """
    # 直接有 space 属性
    if hasattr(obj, "space"):
        return obj.space

    # workflow -> space
    if hasattr(obj, "workflow"):
        workflow = obj.workflow
        if hasattr(workflow, "space"):
            return workflow.space

    # workflow_execution -> workflow -> space
    if hasattr(obj, "workflow_execution"):
        execution = obj.workflow_execution
        if hasattr(execution, "workflow"):
            workflow = execution.workflow
            if hasattr(workflow, "space"):
                return workflow.space

    # config -> workflow -> space（WebhookLog）
    if hasattr(obj, "config"):
        config = obj.config
        if hasattr(config, "workflow"):
            workflow = config.workflow
            if hasattr(workflow, "space"):
                return workflow.space

    logger.warning(
        "cannot_determine_project",
        obj_type=type(obj).__name__,
        obj_id=str(getattr(obj, "pk", "unknown")),
    )
    return None
