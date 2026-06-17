"""审计查询 REST API 测试（AUDITUI-01，SC-1/SC-2）。

覆盖：过滤（actor/action/target/source/时间/q）+ offset/limit 分页 + 详情；
fail-closed（非 superuser 403、未认证 401/403）；只读（无写路由）。
"""

from __future__ import annotations

import uuid

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from audit.services.audit_service import AuditService

pytestmark = pytest.mark.django_db(transaction=True)

LIST_URL = "/api/audit/events/"
DETAIL_URL = "/api/audit/events/{event_id}/"


def _admin(admin_user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=admin_user)
    return c


def _seed(action="member.created", actor=None, target_type="user", target_id="t1", source="api"):
    AuditService.emit(
        action=action,
        actor=actor,
        target_type=target_type,
        target_id=target_id,
        target_repr=f"{target_type}:{target_id}",
        source=source,
    )


class TestFailClosed:
    def test_non_superuser_forbidden(self, authenticated_client):
        assert authenticated_client.get(LIST_URL).status_code == 403

    def test_unauthenticated_blocked(self, api_client):
        assert api_client.get(LIST_URL).status_code in (401, 403)

    def test_superuser_ok(self, admin_user):
        assert _admin(admin_user).get(LIST_URL).status_code == 200


class TestListAndFilter:
    def test_list_returns_items_and_total(self, admin_user):
        _seed(action="member.created")
        _seed(action="credential.created")
        resp = _admin(admin_user).get(LIST_URL)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2

    def test_filter_by_action(self, admin_user):
        _seed(action="member.created")
        _seed(action="credential.deleted")
        resp = _admin(admin_user).get(LIST_URL, {"action": "credential.deleted"})
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["action"] == "credential.deleted"

    def test_filter_by_source_and_target_type(self, admin_user):
        _seed(action="member.created", target_type="user", source="api")
        _seed(action="purge.started", target_type="repository", source="purge")
        resp = _admin(admin_user).get(LIST_URL, {"source": "purge", "target_type": "repository"})
        assert resp.json()["total"] == 1

    def test_filter_by_actor_id(self, admin_user):
        _seed(action="member.created", actor=admin_user)
        _seed(action="credential.created", actor=None)
        resp = _admin(admin_user).get(LIST_URL, {"actor_id": str(admin_user.id)})
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["actor_id"] == str(admin_user.id)

    def test_filter_by_q_target_repr(self, admin_user):
        _seed(action="member.created", target_type="user", target_id="zhangsan")
        _seed(action="member.created", target_type="user", target_id="lisi")
        resp = _admin(admin_user).get(LIST_URL, {"q": "zhangsan"})
        assert resp.json()["total"] == 1

    def test_filter_by_time_range(self, admin_user):
        _seed(action="member.created")
        future = (timezone.now() + timezone.timedelta(days=1)).isoformat()
        resp = _admin(admin_user).get(LIST_URL, {"occurred_from": future})
        assert resp.json()["total"] == 0

    def test_pagination_limit_offset(self, admin_user):
        for i in range(5):
            _seed(action="member.created", target_id=f"u{i}")
        client = _admin(admin_user)
        page1 = client.get(LIST_URL, {"limit": 2, "offset": 0}).json()
        page2 = client.get(LIST_URL, {"limit": 2, "offset": 2}).json()
        assert page1["total"] == 5
        assert len(page1["items"]) == 2
        ids1 = {x["id"] for x in page1["items"]}
        ids2 = {x["id"] for x in page2["items"]}
        assert ids1.isdisjoint(ids2)


class TestDetail:
    def test_detail_returns_before_after(self, admin_user):
        AuditService.emit(
            action="role.changed",
            actor=admin_user,
            target_type="project_membership",
            target_id="m1",
            before={"role": "member"},
            after={"role": "admin"},
            source="api",
        )
        client = _admin(admin_user)
        event_id = client.get(LIST_URL).json()["items"][0]["id"]
        resp = client.get(DETAIL_URL.format(event_id=event_id))
        assert resp.status_code == 200
        body = resp.json()
        assert body["before"] == {"role": "member"}
        assert body["after"] == {"role": "admin"}

    def test_detail_404_missing(self, admin_user):
        resp = _admin(admin_user).get(DETAIL_URL.format(event_id=uuid.uuid4()))
        assert resp.status_code == 404


class TestReadOnly:
    def test_no_write_routes(self, admin_user):
        """只读契约：列表/详情端点不接受写方法（405/404，绝无 create/update/delete）。"""
        client = _admin(admin_user)
        _seed()
        event_id = client.get(LIST_URL).json()["items"][0]["id"]
        assert client.post(LIST_URL, {}, format="json").status_code in (403, 404, 405)
        assert client.delete(DETAIL_URL.format(event_id=event_id)).status_code in (403, 404, 405)
        assert client.patch(
            DETAIL_URL.format(event_id=event_id), {}, format="json"
        ).status_code in (403, 404, 405)
