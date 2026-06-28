"""项目作战室 P2 — 会话共享可见性 + clone 贡献守护测试。

覆盖：
- 创建 shared 会话（绑定项目）→ visibility=shared 落库
- shared 会话：项目成员可读（GET detail 200）/ 非成员 404
- shared 会话出现在成员的项目会话列表（?bound_project=）
- 删除：非创建者非管理员成员 404；创建者可删；项目管理员（主R）可删他人共享会话
- 可见性互转：创建者 personal→shared（需 bound_project）200；非创建者 404
- clone 贡献：成员把共享会话克隆为自己的项目个人会话（201，归属自己、personal）
- 个人会话隔离不破：他人 GET personal 仍 404
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from chat.models import Conversation
from initiatives.models import ProjectMember, ProjectRole
from initiatives.services import ProjectDocService, ProjectService
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@pytest.fixture(autouse=True)
def _silence_provision():
    with patch.object(ProjectDocService, "provision_dispatch", return_value=None):
        yield


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _make_project(*, key: str, owner):
    from asgiref.sync import async_to_sync

    space = Space.objects.create(name="S", feishu_project_key=f"sp-{key}")
    project, _ = async_to_sync(ProjectService().create)(
        space=space, name="P", feishu_project_key=key, created_by=owner
    )
    return project


def _add_member(project, user, role=ProjectRole.BACKEND):
    return ProjectMember.objects.create(project=project, user=user, role=role)


def _create_shared(client, project, *, title="shared") -> str:
    resp = client.post(
        "/api/chat/conversations/",
        {"bound_project_id": str(project.id), "visibility": "shared", "title": title},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["visibility"] == "shared"
    assert body["bound_project_id"] == str(project.id)
    return body["id"]


def test_create_shared_conversation_persists_visibility() -> None:
    owner = User.objects.create_user(username="sv_owner", password="x")
    project = _make_project(key="sv-create", owner=owner)
    conv_id = _create_shared(_client(owner), project)
    conv = Conversation.objects.get(id=conv_id)
    assert conv.visibility == Conversation.Visibility.SHARED
    assert str(conv.bound_project_id) == str(project.id)


def test_shared_visible_to_member_not_to_stranger() -> None:
    owner = User.objects.create_user(username="sv_o2", password="x")
    member = User.objects.create_user(username="sv_m2", password="x")
    stranger = User.objects.create_user(username="sv_s2", password="x")
    project = _make_project(key="sv-read", owner=owner)
    _add_member(project, member)

    conv_id = _create_shared(_client(owner), project)

    # 项目成员可读
    assert _client(member).get(f"/api/chat/conversations/{conv_id}/").status_code == 200
    # 非成员 404（不泄漏存在性）
    assert _client(stranger).get(f"/api/chat/conversations/{conv_id}/").status_code == 404


def test_shared_appears_in_member_project_list() -> None:
    owner = User.objects.create_user(username="sv_o3", password="x")
    member = User.objects.create_user(username="sv_m3", password="x")
    project = _make_project(key="sv-list", owner=owner)
    _add_member(project, member)
    conv_id = _create_shared(_client(owner), project)

    resp = _client(member).get(f"/api/chat/conversations/?bound_project={project.id}")
    assert resp.status_code == 200
    ids = {c["id"] for c in resp.json()}
    assert conv_id in ids


def test_shared_delete_denied_for_plain_member() -> None:
    owner = User.objects.create_user(username="sv_o4", password="x")
    member = User.objects.create_user(username="sv_m4", password="x")
    project = _make_project(key="sv-del1", owner=owner)
    _add_member(project, member)
    conv_id = _create_shared(_client(owner), project)

    # 普通成员（非创建者非管理员）不可删 → 404
    assert _client(member).delete(f"/api/chat/conversations/{conv_id}/").status_code == 404
    assert Conversation.objects.get(id=conv_id).is_deleted is False


def test_shared_delete_allowed_for_project_admin() -> None:
    """项目管理员（主R）可删成员创建的共享会话。"""
    admin = User.objects.create_user(username="sv_admin", password="x")
    member = User.objects.create_user(username="sv_m5", password="x")
    project = _make_project(key="sv-del2", owner=admin)  # admin = OWNER 主R
    _add_member(project, member)

    # 成员创建共享会话
    conv_id = _create_shared(_client(member), project)
    # 管理员删除他人共享会话 → 204
    assert _client(admin).delete(f"/api/chat/conversations/{conv_id}/").status_code == 204
    assert Conversation.objects.get(id=conv_id).is_deleted is True


def test_visibility_transition_creator_only() -> None:
    owner = User.objects.create_user(username="sv_o6", password="x")
    member = User.objects.create_user(username="sv_m6", password="x")
    project = _make_project(key="sv-vis", owner=owner)
    _add_member(project, member)

    # 创建者建一个绑定项目的个人会话
    resp = _client(owner).post(
        "/api/chat/conversations/",
        {"bound_project_id": str(project.id), "visibility": "personal", "title": "p"},
        format="json",
    )
    conv_id = resp.json()["id"]

    # 非创建者改可见性 → 404（aget_for_user owner gate）
    assert _client(member).patch(
        f"/api/chat/conversations/{conv_id}/", {"visibility": "shared"}, format="json"
    ).status_code == 404

    # 创建者 personal→shared → 200
    ok = _client(owner).patch(
        f"/api/chat/conversations/{conv_id}/", {"visibility": "shared"}, format="json"
    )
    assert ok.status_code == 200, ok.content
    assert Conversation.objects.get(id=conv_id).visibility == "shared"


def test_visibility_shared_requires_bound_project() -> None:
    owner = User.objects.create_user(username="sv_o7", password="x")
    # 不绑定项目的通用会话
    conv = Conversation.objects.create(title="g", created_by=owner)
    resp = _client(owner).patch(
        f"/api/chat/conversations/{conv.id}/", {"visibility": "shared"}, format="json"
    )
    assert resp.status_code == 400
    assert resp.json().get("code") == "visibility_requires_project"


def test_clone_for_contribution_creates_personal_copy() -> None:
    owner = User.objects.create_user(username="sv_o8", password="x")
    member = User.objects.create_user(username="sv_m8", password="x")
    project = _make_project(key="sv-clone", owner=owner)
    _add_member(project, member)
    conv_id = _create_shared(_client(owner), project)

    # 成员 clone 共享会话 → 201，副本归属自己、personal、继承 bound_project
    resp = _client(member).post(f"/api/chat/conversations/{conv_id}/clone/")
    assert resp.status_code == 201, resp.content
    new_id = resp.json()["conversation_id"]
    clone = Conversation.objects.get(id=new_id)
    assert clone.created_by_id == member.id
    assert clone.visibility == Conversation.Visibility.PERSONAL
    assert str(clone.bound_project_id) == str(project.id)

    # 非成员不能 clone（无读权限）→ 404
    stranger = User.objects.create_user(username="sv_s8", password="x")
    assert _client(stranger).post(
        f"/api/chat/conversations/{conv_id}/clone/"
    ).status_code == 404


def test_personal_isolation_unbroken() -> None:
    """个人会话隔离不被共享逻辑破坏：他人 GET personal 仍 404。"""
    owner = User.objects.create_user(username="sv_o9", password="x")
    other = User.objects.create_user(username="sv_x9", password="x")
    conv = Conversation.objects.create(title="p", created_by=owner)
    assert _client(other).get(f"/api/chat/conversations/{conv.id}/").status_code == 404
