"""身份/权限类敏感操作 emit 行落库测试（AUDITCOV-01，SC-1）。

覆盖 accounts（建用户/启停/改资料/首启 superuser on_commit）+ projects/members（成员
增删改 + 角色变更）+ projects（空间配置 / 仓库权限变更）的审计 emit 接线，断言 AuditEvent
行落库正确（action / actor / target / 前后值），并校验凭证型字段绝不落明文（SC-1 + 脱敏）。

驱动方式：DRF APIClient + force_authenticate(superuser)——superuser 短路各 view 的项目权限
校验，简化 membership 前置。django_db(transaction=True) 以触发 transaction.on_commit。
"""

from __future__ import annotations

import json

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Invitation
from audit.models import AuditEvent
from permissions.models import ProjectMembership, ProjectRole
from projects.models import Project, ProjectRepository, RepositoryPermission

pytestmark = pytest.mark.django_db(transaction=True)


def _admin_client(admin_user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


def _make_project(name: str = "审计空间") -> Project:
    return Project.objects.create(name=name, feishu_project_key=f"key-{name}")


# ---------------------------------------------------------------------------
# accounts：用户启停 / 改资料 / 建用户 / 首启 superuser
# ---------------------------------------------------------------------------


def test_user_deactivate_emits_deactivated(admin_user, user):
    client = _admin_client(admin_user)
    resp = client.patch(f"/api/auth/users/{user.id}/", {"is_active": False}, format="json")
    assert resp.status_code == 200
    event = AuditEvent.objects.get(action="user.deactivated", target_id=str(user.id))
    assert event.actor_id == admin_user.id
    assert event.before == {"is_active": True}
    assert event.after == {"is_active": False}
    assert event.target_type == "user"


def test_user_activate_emits_activated(admin_user, user):
    user.is_active = False
    user.save(update_fields=["is_active"])
    client = _admin_client(admin_user)
    resp = client.patch(f"/api/auth/users/{user.id}/", {"is_active": True}, format="json")
    assert resp.status_code == 200
    event = AuditEvent.objects.get(action="user.activated", target_id=str(user.id))
    assert event.after == {"is_active": True}


def test_user_status_unchanged_no_emit(admin_user, user):
    """is_active 未变更（True→True）→ 不产生审计行（SC-4 噪音控制）。"""
    client = _admin_client(admin_user)
    resp = client.patch(f"/api/auth/users/{user.id}/", {"is_active": True}, format="json")
    assert resp.status_code == 200
    assert not AuditEvent.objects.filter(target_id=str(user.id)).exists()


def test_admin_profile_update_emits_member_updated(admin_user):
    client = _admin_client(admin_user)
    resp = client.put("/api/auth/admin/profile/", {"username": "admin_renamed"}, format="json")
    assert resp.status_code == 200
    event = AuditEvent.objects.get(action="member.updated", target_id=str(admin_user.id))
    assert event.before == {"username": "admin"}
    assert event.after == {"username": "admin_renamed"}


def test_invite_accept_emits_member_created(admin_user):
    invitation = Invitation.objects.create(
        created_by=admin_user,
        email="newbie@example.com",
        expires_at=timezone.now() + timezone.timedelta(days=1),
    )
    client = APIClient()  # 公开端点，匿名
    resp = client.post(
        "/api/auth/invite/accept/",
        {"token": invitation.token, "username": "newbie", "password": "Sup3rSecret!"},
        format="json",
    )
    assert resp.status_code == 201
    event = AuditEvent.objects.get(action="member.created", target_type="user")
    assert event.actor_id is None  # 匿名注册
    assert event.after["username"] == "newbie"
    assert event.source == "invitation"


def test_setup_superuser_emits_on_commit(db):
    """首启建 superuser（无既有 superuser）→ on_commit 后产 1 条 member.created，actor=None。"""
    client = APIClient()
    resp = client.post(
        "/api/auth/setup/",
        {"username": "root", "password": "Sup3rSecret!", "display_name": "系统管理员"},
        format="json",
    )
    assert resp.status_code == 201
    event = AuditEvent.objects.get(action="member.created", target_type="user")
    assert event.actor_id is None
    assert event.after["is_superuser"] is True
    assert event.source == "system"


# ---------------------------------------------------------------------------
# projects/members：成员增删改 + 角色变更
# ---------------------------------------------------------------------------


def test_member_add_emits(admin_user, user):
    project = _make_project()
    client = _admin_client(admin_user)
    resp = client.post(
        f"/api/spaces/{project.id}/members/",
        {"user_id": str(user.id), "role": ProjectRole.MEMBER},
        format="json",
    )
    assert resp.status_code == 201
    event = AuditEvent.objects.get(action="member.created", target_type="project_membership")
    assert event.actor_id == admin_user.id
    assert event.after["user_id"] == str(user.id)
    assert event.after["role"] == ProjectRole.MEMBER


def test_role_change_emits(admin_user, user):
    project = _make_project()
    ProjectMembership.objects.create(user=user, project=project, role=ProjectRole.MEMBER)
    client = _admin_client(admin_user)
    resp = client.patch(
        f"/api/spaces/{project.id}/members/{user.id}/",
        {"role": ProjectRole.ADMIN},
        format="json",
    )
    assert resp.status_code == 200
    event = AuditEvent.objects.get(action="role.changed", target_type="project_membership")
    assert event.before == {"role": ProjectRole.MEMBER}
    assert event.after == {"role": ProjectRole.ADMIN}


def test_member_delete_emits(admin_user, user):
    project = _make_project()
    ProjectMembership.objects.create(user=user, project=project, role=ProjectRole.MEMBER)
    client = _admin_client(admin_user)
    resp = client.delete(f"/api/spaces/{project.id}/members/{user.id}/")
    assert resp.status_code == 204
    event = AuditEvent.objects.get(action="member.deleted", target_type="project_membership")
    # 删前快照可追溯
    assert event.before["user_id"] == str(user.id)
    assert event.before["role"] == ProjectRole.MEMBER


# ---------------------------------------------------------------------------
# projects：空间配置变更（脱敏）+ 仓库权限变更
# ---------------------------------------------------------------------------


def test_space_feishu_config_emits_no_secret(admin_user):
    project = _make_project()
    client = _admin_client(admin_user)
    secret_value = "super-secret-plugin-token-xyz"
    resp = client.put(
        f"/api/spaces/{project.id}/feishu-config/",
        {"plugin_id": "plg_123", "plugin_secret": secret_value, "user_key": "uk_1"},
        format="json",
    )
    assert resp.status_code == 200
    event = AuditEvent.objects.get(action="project.config_changed", target_id=str(project.id))
    # 仅记字段名集合 + has_secret，DB 绝不含 secret 明文
    blob = json.dumps(event.before) + json.dumps(event.after) + json.dumps(event.metadata)
    assert secret_value not in blob
    assert event.after["redacted"] is True
    assert "feishu_plugin_secret" in event.after["changed"]
    assert event.metadata["config_subtype"] == "feishu_plugin"


def test_repo_permission_change_emits(admin_user, repository):
    project = _make_project()
    link = ProjectRepository.objects.create(
        project=project,
        repository=repository,
        permission_level=RepositoryPermission.READ_ONLY,
    )
    client = _admin_client(admin_user)
    resp = client.patch(
        f"/api/spaces/{project.id}/repositories/{link.id}/",
        {"permission_level": RepositoryPermission.READ_WRITE},
        format="json",
    )
    assert resp.status_code == 200
    event = AuditEvent.objects.get(action="repository.permission_changed", target_id=str(link.id))
    assert event.before == {"permission_level": RepositoryPermission.READ_ONLY}
    assert event.after == {"permission_level": RepositoryPermission.READ_WRITE}
