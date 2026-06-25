"""access_scope fail-closed 权限解析测试（Phase 15-01）。"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async

from knowledge.access_scope import resolve_allowed_project_ids, resolve_allowed_repository_ids
from permissions.models import SpaceMembership, SpaceRole

pytestmark = pytest.mark.django_db(transaction=True)


async def test_user_with_membership_sees_project(project, user, project_memberships):
    """user A 仅 membership 项目 P1 → resolve 含 P1.id。"""
    allowed = await resolve_allowed_project_ids(user)
    assert str(project.id) in allowed


async def test_user_without_membership_gets_empty(project, other_user):
    """user B 无 membership → 空集合。"""
    allowed = await resolve_allowed_project_ids(other_user)
    assert allowed == []


async def test_none_user_returns_empty():
    """user=None → 空集合。"""
    assert await resolve_allowed_project_ids(None) == []
    assert await resolve_allowed_repository_ids(None) == []


async def test_caller_project_ids_intersect(project, user, project_memberships, project_without_repo):
    """caller project_ids 只能收窄 allowed 集合。"""
    await sync_to_async(SpaceMembership.objects.create)(
        user=user, space=project_without_repo, role=SpaceRole.MEMBER
    )
    allowed = await resolve_allowed_project_ids(user, project_ids=[str(project.id)])
    assert allowed == [str(project.id)]

    allowed_invisible = await resolve_allowed_project_ids(
        user, project_ids=[str(project_without_repo.id)]
    )
    assert allowed_invisible == [str(project_without_repo.id)]

    # 含不可见项目 → 空
    assert await resolve_allowed_project_ids(user, project_ids=[str(project.id), "99999999-0000-0000-0000-000000000099"]) == []


async def test_superuser_sees_all_projects(admin_user, project, project_without_repo):
    """superuser → 全项目 id（caller 可收窄）。"""
    all_ids = await resolve_allowed_project_ids(admin_user)
    assert str(project.id) in all_ids
    assert str(project_without_repo.id) in all_ids

    narrowed = await resolve_allowed_project_ids(admin_user, project_ids=[str(project.id)])
    assert narrowed == [str(project.id)]


async def test_resolve_allowed_repository_ids(project, user, repository, project_memberships):
    """resolve_allowed_repository_ids 仅返回 user 可见 project 下仓库。"""
    allowed = await resolve_allowed_repository_ids(user)
    assert str(repository.id) in allowed

    narrowed = await resolve_allowed_repository_ids(user, repository_ids=[str(repository.id)])
    assert narrowed == [str(repository.id)]
