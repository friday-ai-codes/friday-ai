"""会话项目绑定改归/解绑守护测试（WS-03，Phase 82）。

PATCH /api/chat/conversations/{id}/ 的 bound_project_id：
- 改归到可读项目（public_org / 成员）→ 200，bound_project 落库
- null 解绑 → 200，bound_project 置空
- 改归到不可读项目（members_only 非成员）→ 400 fail-closed，不落库
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from chat.models import Conversation
from initiatives.models import ProjectVisibility
from initiatives.services import ProjectDocService, ProjectService
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@pytest.fixture(autouse=True)
def _silence_provision():
    """建项目时不真正派发飞书 provision（隔离后台外呼 + 避免 sqlite 表锁）。"""
    with patch.object(ProjectDocService, "provision_dispatch", return_value=None):
        yield


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _make_project(*, key: str, visibility=ProjectVisibility.PUBLIC_ORG, owner=None):
    from asgiref.sync import async_to_sync

    space = Space.objects.create(name="S", feishu_project_key=f"sp-{key}")
    project, _ = async_to_sync(ProjectService().create)(
        space=space, name="P", feishu_project_key=key, created_by=owner
    )
    if visibility != ProjectVisibility.PUBLIC_ORG:
        project.visibility = visibility
        project.save(update_fields=["visibility"])
    return project


def test_rebind_to_public_org_project(db) -> None:
    user = User.objects.create_user(username="rb_owner", password="x")
    project = _make_project(key="rb-pub", owner=user)
    conv = Conversation.objects.create(title="t", created_by=user)

    resp = _client(user).patch(
        f"/api/chat/conversations/{conv.id}/",
        {"bound_project_id": str(project.id)},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    assert resp.json()["bound_project_id"] == str(project.id)
    conv.refresh_from_db()
    assert str(conv.bound_project_id) == str(project.id)


def test_unbind_sets_null(db) -> None:
    user = User.objects.create_user(username="rb_unbind", password="x")
    project = _make_project(key="rb-unbind", owner=user)
    conv = Conversation.objects.create(title="t", bound_project=project, created_by=user)

    resp = _client(user).patch(
        f"/api/chat/conversations/{conv.id}/",
        {"bound_project_id": None},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    assert resp.json()["bound_project_id"] is None
    conv.refresh_from_db()
    assert conv.bound_project_id is None


def test_rebind_to_unreadable_members_only_rejected(db) -> None:
    """members_only 项目、非成员 → 400 fail-closed，不落库。"""
    stranger = User.objects.create_user(username="rb_stranger", password="x")
    owner = User.objects.create_user(username="rb_real_owner", password="x")
    project = _make_project(
        key="rb-priv", visibility=ProjectVisibility.MEMBERS_ONLY, owner=owner
    )
    conv = Conversation.objects.create(title="t", created_by=stranger)

    resp = _client(stranger).patch(
        f"/api/chat/conversations/{conv.id}/",
        {"bound_project_id": str(project.id)},
        format="json",
    )
    assert resp.status_code == 400, resp.content
    conv.refresh_from_db()
    assert conv.bound_project_id is None
