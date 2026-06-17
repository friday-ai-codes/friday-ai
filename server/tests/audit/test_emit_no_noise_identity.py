"""SC-4 身份侧无审计噪音测试（AUDITCOV-01）。

读操作（用户列表 / 成员列表 / 空间详情）与自助操作（改密）刻意不产生 AuditEvent——
仅敏感/管理写操作 emit。每个用例断言该操作未新增审计行（count == 0）。
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from audit.models import AuditEvent
from projects.models import Project

pytestmark = pytest.mark.django_db(transaction=True)


def _admin_client(admin_user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


def _make_project() -> Project:
    return Project.objects.create(name="噪音空间", feishu_project_key="key-noise")


def test_user_list_get_no_audit(admin_user):
    client = _admin_client(admin_user)
    resp = client.get("/api/auth/users/")
    assert resp.status_code == 200
    assert AuditEvent.objects.count() == 0


def test_member_list_get_no_audit(admin_user):
    project = _make_project()
    client = _admin_client(admin_user)
    resp = client.get(f"/api/spaces/{project.id}/members/")
    assert resp.status_code == 200
    assert AuditEvent.objects.count() == 0


def test_space_detail_get_no_audit(admin_user):
    project = _make_project()
    client = _admin_client(admin_user)
    resp = client.get(f"/api/spaces/{project.id}/")
    assert resp.status_code == 200
    assert AuditEvent.objects.count() == 0


def test_self_change_password_no_audit(user):
    """自助改密非管理审计点——不产生 AuditEvent。"""
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post(
        "/api/auth/change-password/",
        {"old_password": "testpassword123", "new_password": "N3wStr0ngPass!"},
        format="json",
    )
    assert resp.status_code == 200
    assert AuditEvent.objects.count() == 0
