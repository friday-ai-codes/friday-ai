"""Audit REST API 测试 —— 权限、过滤、搜索、405 守护。

覆盖 AUDIT-04 要求的 10 个测试用例：
1. superuser list → 200 + 分页
2. superuser detail → 200 + 全字段
3. non-superuser list → 403
4. unauthenticated → 401
5. PUT/PATCH/DELETE → 405
6. filter by action
7. filter by source
8. filter by target_type
9. search by actor_display
10. empty result → 空列表 + 分页元数据
"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from audit.models import AuditEvent

User = get_user_model()

pytestmark = pytest.mark.django_db


def _create_event(**overrides):
    """创建审计事件的快捷 helper。"""
    defaults = {
        "action": "user.created",
        "target_type": "User",
        "target_id": "1",
        "actor_type": "user",
        "actor_display": "admin",
        "source": AuditEvent.Source.API,
    }
    defaults.update(overrides)
    return AuditEvent.objects.create(**defaults)


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(
        username="audit_admin",
        email="audit_admin@example.com",
        password="testpass123",
    )


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        username="audit_user",
        email="audit_user@example.com",
        password="testpass123",
    )


@pytest.fixture
def super_client(superuser):
    client = APIClient()
    client.force_authenticate(user=superuser)
    return client


@pytest.fixture
def regular_client(regular_user):
    client = APIClient()
    client.force_authenticate(user=regular_user)
    return client


class TestAuditEventListAPI:
    """审计事件列表端点测试。"""

    def test_superuser_can_list(self, super_client):
        """superuser list → 200 + 分页结果。"""
        _create_event()
        _create_event(action="user.deleted", target_type="User", target_id="2")

        resp = super_client.get("/api/audit-events/")
        assert resp.status_code == status.HTTP_200_OK
        # 分页包装: {count, next, previous, results}
        assert "count" in resp.data
        assert resp.data["count"] == 2
        assert len(resp.data["results"]) == 2

    def test_non_superuser_gets_403(self, regular_client):
        """非 superuser list → 403。"""
        _create_event()
        resp = regular_client.get("/api/audit-events/")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_gets_401(self, db):
        """未认证 list → 401。"""
        _create_event()
        client = APIClient()
        resp = client.get("/api/audit-events/")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_empty_result_set(self, super_client):
        """空结果 → 空列表 + 分页元数据。"""
        resp = super_client.get("/api/audit-events/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 0
        assert resp.data["results"] == []

    def test_filter_by_action(self, super_client):
        """按 action 参数过滤。"""
        _create_event(action="user.created")
        _create_event(action="user.deleted")

        resp = super_client.get("/api/audit-events/", {"action": "user.created"})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["action"] == "user.created"

    def test_filter_by_source(self, super_client):
        """按 source 参数过滤。"""
        _create_event(source=AuditEvent.Source.API)
        _create_event(source=AuditEvent.Source.SYSTEM, action="system.startup")

        resp = super_client.get("/api/audit-events/", {"source": "system"})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["source"] == "system"

    def test_filter_by_target_type(self, super_client):
        """按 target_type 参数过滤。"""
        _create_event(target_type="User")
        _create_event(target_type="Repository", action="repo.created")

        resp = super_client.get("/api/audit-events/", {"target_type": "User"})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["target_type"] == "User"

    def test_search_by_actor_display(self, super_client):
        """按 actor_display 搜索。"""
        _create_event(actor_display="alice")
        _create_event(actor_display="bob", action="user.deleted")

        resp = super_client.get("/api/audit-events/", {"search": "alice"})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["actor_username"] == "alice"


class TestAuditEventDetailAPI:
    """审计事件详情端点测试。"""

    def test_superuser_can_get_detail(self, super_client):
        """superuser detail → 200 + 全字段。"""
        user = User.objects.create_user(username="actor", password="pass")
        event = _create_event(
            actor=user,
            actor_display="actor",
            before={"role": "viewer"},
            after={"role": "admin"},
            ip_address="10.0.0.1",
        )

        resp = super_client.get(f"/api/audit-events/{event.pk}/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["id"] == str(event.pk)
        assert resp.data["action"] == "user.created"
        assert resp.data["target_type"] == "User"
        assert resp.data["target_id"] == "1"
        assert resp.data["before"] == {"role": "viewer"}
        assert resp.data["after"] == {"role": "admin"}
        assert resp.data["actor_username"] == "actor"
        assert resp.data["source"] == "api"
        assert resp.data["ip_address"] == "10.0.0.1"
        assert resp.data["actor_type"] == "user"
        assert "timestamp" in resp.data

    def test_mutation_returns_405(self, super_client):
        """PUT/PATCH/DELETE on detail → 405。"""
        event = _create_event()

        for method in ("put", "patch", "delete"):
            resp = getattr(super_client, method)(
                f"/api/audit-events/{event.pk}/",
                data={"action": "hacked"},
                format="json",
            )
            assert resp.status_code == status.HTTP_405_METHOD_NOT_ALLOWED, (
                f"{method.upper()} should return 405"
            )
