"""审计导出 API 测试（AUDITUI-02，SC-4）。

覆盖：CSV / JSON 导出内容 + 过滤透传 + max_rows 上限 400 + fail-closed 403。
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from audit.services.audit_service import AuditService

pytestmark = pytest.mark.django_db(transaction=True)

EXPORT_URL = "/api/audit/events/export/"


def _admin(admin_user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=admin_user)
    return c


def _seed(action="member.created", target_type="user", target_id="t1", source="api", **kw):
    AuditService.emit(
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_repr=f"{target_type}:{target_id}",
        source=source,
        **kw,
    )


def _consume(resp) -> str:
    return b"".join(resp.streaming_content).decode("utf-8")


class TestFailClosed:
    def test_non_superuser_forbidden(self, authenticated_client):
        assert authenticated_client.get(EXPORT_URL).status_code == 403


class TestCsvExport:
    def test_csv_has_header_and_rows(self, admin_user):
        _seed(action="member.created")
        _seed(action="credential.created")
        resp = _admin(admin_user).get(EXPORT_URL, {"fmt": "csv"})
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("text/csv")
        assert "attachment" in resp["Content-Disposition"]
        text = _consume(resp)
        assert "occurred_at,actor_repr,action" in text
        assert "member.created" in text
        assert "credential.created" in text

    def test_csv_respects_filter(self, admin_user):
        _seed(action="member.created")
        _seed(action="credential.deleted")
        resp = _admin(admin_user).get(EXPORT_URL, {"fmt": "csv", "action": "credential.deleted"})
        text = _consume(resp)
        assert "credential.deleted" in text
        assert "member.created" not in text


class TestJsonExport:
    def test_json_items_array(self, admin_user):
        _seed(action="member.created")
        resp = _admin(admin_user).get(EXPORT_URL, {"fmt": "json"})
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("application/json")
        payload = json.loads(_consume(resp))
        assert "items" in payload
        assert len(payload["items"]) == 1
        assert payload["items"][0]["action"] == "member.created"


class TestMaxRows:
    def test_over_limit_returns_400(self, admin_user):
        _seed(action="member.created")
        with patch("audit.api.views.EXPORT_MAX_ROWS", 0):
            resp = _admin(admin_user).get(EXPORT_URL, {"fmt": "csv"})
        assert resp.status_code == 400
        assert "收紧" in resp.json()["detail"]
