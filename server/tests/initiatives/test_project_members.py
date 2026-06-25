"""项目成员协作守护测试：增删改 + 主R 唯一/转移（Phase 77，MEMBER-01/02）。"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from initiatives.models import ProjectMember, ProjectRole
from initiatives.services import ProjectMemberError, ProjectService
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@sync_to_async
def _user(username) -> object:
    return User.objects.create_user(username=username, password="x")


async def _project_with_owner():
    space = await sync_to_async(Space.objects.create)(name="S", feishu_project_key="m-k")
    owner = await _user("owner")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key="m-board", created_by=owner
    )
    return project, owner


async def test_add_member_idempotent() -> None:
    project, _owner = await _project_with_owner()
    u = await _user("dev")
    m1, c1 = await ProjectService().add_member(
        project_id=project.id, user=u, role=ProjectRole.BACKEND
    )
    m2, c2 = await ProjectService().add_member(
        project_id=project.id, user=u, role=ProjectRole.FRONTEND
    )
    assert c1 is True and c2 is False
    assert m1.id == m2.id


async def test_add_member_owner_role_rejected() -> None:
    project, _owner = await _project_with_owner()
    u = await _user("dev2")
    with pytest.raises(ProjectMemberError):
        await ProjectService().add_member(
            project_id=project.id, user=u, role=ProjectRole.OWNER
        )


async def test_single_owner_enforced() -> None:
    project, _owner = await _project_with_owner()
    # 项目已有 1 个 owner（创建者）
    owner_count = await ProjectMember.objects.filter(
        project=project, role=ProjectRole.OWNER
    ).acount()
    assert owner_count == 1


async def test_change_member_role_cannot_set_owner() -> None:
    project, _owner = await _project_with_owner()
    u = await _user("dev3")
    await ProjectService().add_member(
        project_id=project.id, user=u, role=ProjectRole.BACKEND
    )
    with pytest.raises(ProjectMemberError):
        await ProjectService().change_member_role(
            project_id=project.id, user_id=u.id, role=ProjectRole.OWNER
        )


async def test_transfer_owner_swaps_roles_atomically() -> None:
    project, owner = await _project_with_owner()
    new_owner = await _user("newowner")
    await ProjectService().add_member(
        project_id=project.id, user=new_owner, role=ProjectRole.PM
    )
    await ProjectService().transfer_owner(
        project_id=project.id, new_owner_user_id=new_owner.id
    )
    new_m = await ProjectMember.objects.aget(project=project, user=new_owner)
    old_m = await ProjectMember.objects.aget(project=project, user=owner)
    assert new_m.role == ProjectRole.OWNER
    assert old_m.role == ProjectRole.PM  # 互换：旧 owner 接手新 owner 转移前的角色
    # 仍仅一个 owner
    assert (
        await ProjectMember.objects.filter(
            project=project, role=ProjectRole.OWNER
        ).acount()
        == 1
    )


async def test_transfer_owner_to_non_member_rejected() -> None:
    project, _owner = await _project_with_owner()
    stranger = await _user("stranger")
    with pytest.raises(ProjectMemberError):
        await ProjectService().transfer_owner(
            project_id=project.id, new_owner_user_id=stranger.id
        )


async def test_remove_owner_rejected_must_transfer_first() -> None:
    project, owner = await _project_with_owner()
    with pytest.raises(ProjectMemberError):
        await ProjectService().remove_member(
            project_id=project.id, user_id=owner.id
        )
