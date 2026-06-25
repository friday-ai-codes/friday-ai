"""知识检索权限 scope 解析（Phase 15，fail-closed）。

无 user 或 user 无可见 project → 空集合；caller 传入的 project_ids/repository_ids
只能 intersect 收窄，不能放宽。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from asgiref.sync import sync_to_async
from permissions.services import PermissionService

if TYPE_CHECKING:
    from accounts.models import User

__all__ = ["resolve_allowed_project_ids", "resolve_allowed_repository_ids"]


async def resolve_allowed_project_ids(
    user: User | None,
    project_ids: list[str] | None = None,
) -> list[str]:
    """解析 user 可见的 project_id 列表（fail-closed）。

    - user=None → []
    - superuser → 全项目（caller project_ids 可收窄）
    - 普通用户 → membership 项目集合
    - caller project_ids 与 allowed 取交集；含不可见 id → []
    """
    if user is None:
        return []

    allowed = await sync_to_async(
        lambda: list(PermissionService.get_user_projects(user).values_list("id", flat=True))
    )()
    allowed_set = {str(pid) for pid in allowed}

    if project_ids is None:
        return sorted(allowed_set)

    caller = {str(pid) for pid in project_ids}
    if not caller.issubset(allowed_set):
        return []
    return sorted(caller)


async def resolve_allowed_repository_ids(
    user: User | None,
    repository_ids: list[str] | None = None,
    project_ids: list[str] | None = None,
) -> list[str]:
    """解析 user 可见 project 下关联的 repository_id（P6 双维权限）。

  仓库通过 Space.repositories M2M 关联；superuser 返回全量仓库。
    """
    if user is None:
        return []

    from repositories.models import Repository

    allowed_projects = await resolve_allowed_project_ids(user, project_ids)
    if not allowed_projects:
        return []

    if user.is_superuser and repository_ids is None:
        repo_ids = await sync_to_async(
            lambda: list(Repository.objects.values_list("id", flat=True))
        )()
        return sorted(str(rid) for rid in repo_ids)

    def _repos_for_projects() -> list[str]:
        from projects.models import Space

        qs = Space.objects.filter(id__in=allowed_projects).prefetch_related("repositories")
        ids: set[str] = set()
        for proj in qs:
            for repo in proj.repositories.all():
                ids.add(str(repo.id))
        return sorted(ids)

    allowed_repos = set(await sync_to_async(_repos_for_projects)())

    if repository_ids is None:
        return sorted(allowed_repos)

    caller = {str(rid) for rid in repository_ids}
    if not caller.issubset(allowed_repos):
        return []
    return sorted(caller)
