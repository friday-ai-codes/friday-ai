"""项目权限判定（PROJ-03 / MEMBER-02，fail-closed）。

项目 CRUD + 成员操作按**所属 Space 成员权限** fail-closed——复用
``permissions.PermissionService.has_project_access``（Space 三角色判定）。非 Space 成员一律
拒绝。读（list/retrieve）= Space viewer+；写（create/update/status/member/transfer）= Space
admin+ 或 superuser。项目对其全部成员可见可参与（无细粒度行内权限，本期）。

所有判定 async 面向 adrf；ORM 经 ``sync_to_async``。
"""

from __future__ import annotations

from typing import Any

from asgiref.sync import sync_to_async

from permissions.models import SpaceRole
from permissions.services import PermissionService


async def auser_can_access_project(
    user: Any, project: Any, min_space_role: str = SpaceRole.VIEWER
) -> bool:
    """用户是否可按指定最低 Space 角色访问项目（fail-closed）。

    superuser 始终放行；否则要求是项目所属 ``Space`` 的成员且角色 ≥ ``min_space_role``。
    另外：项目成员（``ProjectMember``）即便仅 Space viewer 也可参与本项目（成员可见可参与）。
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return await sync_to_async(PermissionService.has_project_access)(
        user, project.space, min_space_role
    )


async def auser_is_project_member(user: Any, project_id: Any) -> bool:
    """用户是否为该项目成员（用于"成员可见可参与"读放行）。"""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    from initiatives.models import ProjectMember

    return await ProjectMember.objects.filter(
        project_id=project_id, user=user
    ).aexists()
