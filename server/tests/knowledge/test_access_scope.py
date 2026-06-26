"""access_scope fail-closed 权限解析测试（Phase 15-01）。"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from knowledge.access_scope import resolve_allowed_project_ids, resolve_allowed_repository_ids
from permissions.models import SpaceMembership, SpaceRole

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


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


# ---------------------------------------------------------------------------
# Phase 85-02 安全门：项目内容 visibility 召回口径（A3 within-phase live 校验）
#
# live 验证结论：members_only 项目对非成员经 ``search_similar`` 零召回——非成员的可读集合
# 不含其项目 id（membership 空 + members_only 不并入 public_org 集），caller intersect
# 收窄即 fail-closed。未发现「按 Space 维度过滤导致 members_only 泄漏」，故 access_scope
# 过滤口径**保持不变**（无需修改）；以下为真实 PASS（非 xfail）零泄漏 + 对称守护断言。
# ---------------------------------------------------------------------------


async def _make_initiative_project(created_by, *, key, visibility):
    """建 initiatives.Project（owner=created_by），按需设 visibility（夹具直写）。"""
    from initiatives.models import ProjectVisibility
    from initiatives.services import ProjectService
    from projects.models import Space

    space = await sync_to_async(Space.objects.create)(name="S", feishu_project_key=f"{key}-sp")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key=key, created_by=created_by
    )
    if visibility != ProjectVisibility.PUBLIC_ORG:
        project.visibility = visibility
        await project.asave(update_fields=["visibility"])
    return project


async def test_members_only_non_member_scope_zero_leak():
    """members_only + 非成员 → caller intersect 项目 id 收窄为 []（零泄漏）。"""
    from initiatives.models import ProjectVisibility

    owner = await sync_to_async(User.objects.create_user)(username="scope-mo-owner", password="x")
    stranger = await sync_to_async(User.objects.create_user)(username="scope-mo-stranger", password="x")
    project = await _make_initiative_project(
        owner, key="scope-mo", visibility=ProjectVisibility.MEMBERS_ONLY
    )
    # 非成员的可读集合既不含 Project.id 也不含其 space_id。
    allowed = await resolve_allowed_project_ids(stranger)
    assert str(project.id) not in allowed
    assert str(project.space_id) not in allowed
    # caller 显式传 members_only 项目 id → 收窄为 []（fail-closed）。
    assert await resolve_allowed_project_ids(stranger, project_ids=[str(project.id)]) == []


async def test_search_similar_members_only_non_member_zero_hits():
    """非成员对 members_only 项目经 search_similar 召回零命中（真实，短路于 allowed 空）。"""
    from initiatives.models import ProjectVisibility
    from knowledge.retrieval import DeliveryKnowledgeSearchService

    owner = await sync_to_async(User.objects.create_user)(username="ss-mo-owner", password="x")
    stranger = await sync_to_async(User.objects.create_user)(username="ss-mo-stranger", password="x")
    project = await _make_initiative_project(
        owner, key="ss-mo", visibility=ProjectVisibility.MEMBERS_ONLY
    )
    results = await DeliveryKnowledgeSearchService().search_similar(
        "任意检索词", user=stranger, project_ids=[str(project.id)]
    )
    assert results == []


async def test_public_org_non_member_scope_visible():
    """public_org + 非成员 → 项目并入可读集合（visibility 对称，非成员可读）。"""
    from initiatives.models import ProjectVisibility

    owner = await sync_to_async(User.objects.create_user)(username="scope-po-owner", password="x")
    stranger = await sync_to_async(User.objects.create_user)(username="scope-po-stranger", password="x")
    project = await _make_initiative_project(
        owner, key="scope-po", visibility=ProjectVisibility.PUBLIC_ORG
    )
    allowed = await resolve_allowed_project_ids(stranger)
    assert str(project.id) in allowed


async def test_member_members_only_scope_visible():
    """成员（SpaceMembership）+ members_only → 项目 space 并入可读集合（不回退）。"""
    from initiatives.models import ProjectVisibility

    owner = await sync_to_async(User.objects.create_user)(username="scope-mem-owner", password="x")
    project = await _make_initiative_project(
        owner, key="scope-mem", visibility=ProjectVisibility.MEMBERS_ONLY
    )
    member = await sync_to_async(User.objects.create_user)(username="scope-mem-user", password="x")
    await sync_to_async(SpaceMembership.objects.create)(
        user=member, space_id=project.space_id, role=SpaceRole.MEMBER
    )
    allowed = await resolve_allowed_project_ids(member)
    assert str(project.space_id) in allowed
