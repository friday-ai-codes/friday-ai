"""ProjectService 守护测试：CRUD + 幂等 + 状态机 + 审计 + WS 推送（Phase 77）。

async + sync_to_async ORM 写库需 ``transaction=True``（与 delivery 范式一致），否则跨线程
连接写入不被主连接事务回滚清理。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from audit.models import AuditEvent
from audit.services import taxonomy
from initiatives.models import Project, ProjectMember, ProjectRole, ProjectStatus
from initiatives.services import ProjectService, ProjectTransitionError
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@sync_to_async
def _make_space(key="svc-key") -> Space:
    return Space.objects.create(name="S", feishu_project_key=key)


@sync_to_async
def _make_user(username="creator") -> object:
    return User.objects.create_user(username=username, password="x")


async def test_create_project_sets_creator_as_owner() -> None:
    space = await _make_space()
    user = await _make_user()
    project, created = await ProjectService().create(
        space=space, name="P1", feishu_project_key="board-1", created_by=user
    )
    assert created is True
    assert project.status == ProjectStatus.DEVELOPING
    owner = await ProjectMember.objects.aget(project=project, role=ProjectRole.OWNER)
    assert owner.user_id == user.id


async def test_create_is_idempotent_on_space_feishu_key() -> None:
    space = await _make_space()
    user = await _make_user()
    p1, c1 = await ProjectService().create(
        space=space, name="P", feishu_project_key="dup", created_by=user
    )
    p2, c2 = await ProjectService().create(
        space=space, name="P-again", feishu_project_key="dup", created_by=user
    )
    assert c1 is True and c2 is False
    assert p1.id == p2.id
    assert await Project.objects.filter(space=space, feishu_project_key="dup").acount() == 1


async def test_manual_projects_without_key_are_distinct() -> None:
    space = await _make_space()
    user = await _make_user()
    p1, c1 = await ProjectService().create(space=space, name="M1", created_by=user)
    p2, c2 = await ProjectService().create(space=space, name="M2", created_by=user)
    assert c1 and c2
    assert p1.id != p2.id


async def test_status_machine_legal_transition_audited() -> None:
    space = await _make_space()
    user = await _make_user()
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key="st", created_by=user
    )
    updated = await ProjectService().change_status(
        project_id=project.id, to_status=ProjectStatus.ARCHIVED, actor=user
    )
    assert updated.status == ProjectStatus.ARCHIVED
    exists = await AuditEvent.objects.filter(
        action=taxonomy.ACTION_PROJECT_STATUS_CHANGED, target_id=str(project.id)
    ).aexists()
    assert exists, "状态变更应写入 AuditEvent"


async def test_status_machine_illegal_transition_fail_loud() -> None:
    space = await _make_space()
    user = await _make_user()
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key="ill", created_by=user
    )
    await ProjectService().terminate(project_id=project.id, actor=user)
    # terminated 为终态：terminated → developing 非法
    with pytest.raises(ProjectTransitionError):
        await ProjectService().change_status(
            project_id=project.id, to_status=ProjectStatus.DEVELOPING, actor=user
        )


async def test_create_emits_audit_and_pushes_ws() -> None:
    space = await _make_space()
    user = await _make_user()
    with patch(
        "initiatives.services.project_service.apush_project_event",
        new=AsyncMock(),
    ) as push:
        project, created = await ProjectService().create(
            space=space, name="P", feishu_project_key="ws", created_by=user
        )
    assert created
    push.assert_awaited()  # 写库后 best-effort 推送
    assert await AuditEvent.objects.filter(
        action=taxonomy.ACTION_PROJECT_CREATED, target_id=str(project.id)
    ).aexists()
