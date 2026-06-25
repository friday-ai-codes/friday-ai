"""权限查询服务：集中式权限判断引擎。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from .models import ProjectMembership, ProjectRole

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from accounts.models import User
    from projects.models import Project

logger = structlog.get_logger(__name__)

# 角色优先级映射：数值越大权限越高
ROLE_PRIORITY: dict[str, int] = {
    ProjectRole.VIEWER: 0,
    ProjectRole.MEMBER: 1,
    ProjectRole.ADMIN: 2,
}


class PermissionService:
    """集中式权限查询服务。

    提供统一的空间级权限判断方法，所有权限类和 Mixin 调用此服务。
    所有方法保持同步 —— DRF/adrf 会自动用 sync_to_async 包装。
    """

    @classmethod
    def has_project_access(
        cls,
        user: User,
        project: Project,
        min_role: str = ProjectRole.VIEWER,
    ) -> bool:
        """检查用户是否有指定最低角色的空间访问权限。

        Args:
            user: 请求用户
            project: 目标空间
            min_role: 最低要求角色（默认 viewer）

        Returns:
            True 如果用户满足权限要求
        """
        # superuser 始终有权限
        if user.is_superuser:
            return True

        role = cls.get_user_role(user, project)
        if role is None:
            logger.debug(
                "permission_denied_not_member",
                user_id=str(user.pk),
                project_id=str(project.pk),
            )
            return False

        user_priority = ROLE_PRIORITY.get(role, -1)
        required_priority = ROLE_PRIORITY.get(min_role, 0)
        has_access = user_priority >= required_priority

        if not has_access:
            logger.debug(
                "permission_denied_insufficient_role",
                user_id=str(user.pk),
                project_id=str(project.pk),
                user_role=role,
                required_role=min_role,
            )

        return has_access

    @classmethod
    def get_user_role(
        cls,
        user: User,
        project: Project,
    ) -> str | None:
        """获取用户在项目中的角色。

        Returns:
            角色字符串（admin/member/viewer）或 None（非成员）
        """
        try:
            membership = ProjectMembership.objects.get(
                user=user,
                project=project,
            )
            return membership.role
        except ProjectMembership.DoesNotExist:
            return None

    @classmethod
    def get_user_projects(cls, user: User) -> QuerySet[Project]:
        """获取用户所属的所有空间。

        superuser 返回所有项目，普通用户按 membership 过滤。
        """
        from projects.models import Project

        if user.is_superuser:
            return Project.objects.all()
        return Project.objects.filter(memberships__user=user).distinct()

    @classmethod
    def can_admin_repository(cls, user: User, repository_id: str) -> bool:
        """仓库级管理权限：超管，或该仓库所关联任一空间的 admin。

        用于仓库级管理操作（索引、建立知识、敏感信息、provider/插件/webhook 等）。
        仓库可能关联多个空间——只要用户是其中任一空间的 admin 即放行。孤儿仓库
        （未关联任何空间）仅超管可管理。
        """
        if not (user and getattr(user, "is_authenticated", False)):
            return False
        if user.is_superuser:
            return True
        return ProjectMembership.objects.filter(
            user=user,
            role=ProjectRole.ADMIN,
            project__repositories__id=repository_id,
        ).exists()
