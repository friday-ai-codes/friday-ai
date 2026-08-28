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


@sync_to_async
def _public_org_project_ids() -> set[str]:
    """visibility==public_org 的项目 id 集合（只读，WS-02 读半放宽）。"""
    from initiatives.models import Project, ProjectVisibility

    return {
        str(pid)
        for pid in Project.objects.filter(visibility=ProjectVisibility.PUBLIC_ORG).values_list(
            "id", flat=True
        )
    }


@sync_to_async
def _member_project_ids(user: User) -> set[str]:
    """user 有 ProjectMember 关系行的 initiatives.Project id 集合（只读，D-02）。"""
    from initiatives.models import Project

    return {
        str(pid) for pid in Project.objects.filter(members__user=user).values_list("id", flat=True)
    }


@sync_to_async
def _all_project_ids() -> set[str]:
    """全量 initiatives.Project id 集合（仅 superuser 分支并入，D-02）。"""
    from initiatives.models import Project

    return {str(pid) for pid in Project.objects.values_list("id", flat=True)}


async def resolve_allowed_project_ids(
    user: User | None,
    project_ids: list[str] | None = None,
) -> list[str]:
    """解析 user 可见的 project_id 列表（fail-closed）。

    - user=None → []
    - superuser → 全量 Space id ∪ 全量 initiatives.Project id（caller project_ids 可收窄）
    - 普通用户 → SpaceMembership 空间 ∪ ProjectMember 项目 ∪ visibility==public_org 项目
    - caller project_ids 与 allowed 取交集；含不可见 id → []（收窄语义不被放宽破坏）

    D-02：members_only 项目文档向量点写 initiatives.Project id，故集合必须含
    Project 维度（否则成员乃至 superuser 的项目文档 RAG 全黑）。注意
    ``resolve_allowed_repository_ids`` 会同时按 Space id 与 initiatives.Project.space
    映射仓库，使 ProjectMember 项目维度与知识仓库可见性保持一致。
    """
    if user is None:
        return []

    allowed = await sync_to_async(
        lambda: list(PermissionService.get_user_projects(user).values_list("id", flat=True))
    )()
    allowed_set = {str(pid) for pid in allowed}

    # WS-02 权限翻转（读半）：public_org 项目并入可读集合（只读，不写）。
    # members_only 不并入 → 非成员维持零可见；caller intersect 收窄语义保持不变。
    allowed_set |= await _public_org_project_ids()

    # D-02：Project 维度并集——普通用户并入 ProjectMember 关系项目；
    # superuser 并入全量 Project。非成员既无 SpaceMembership 也无 ProjectMember
    # 行，fail-closed 不被破坏。
    if user.is_superuser:
        allowed_set |= await _all_project_ids()
    else:
        allowed_set |= await _member_project_ids(user)

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
        from django.db.models import Q

        from projects.models import Space

        qs = (
            Space.objects.filter(Q(id__in=allowed_projects) | Q(projects__id__in=allowed_projects))
            .distinct()
            .prefetch_related("repositories")
        )
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
