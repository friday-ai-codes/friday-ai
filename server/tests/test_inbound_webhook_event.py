"""入站 webhook 原始留痕测试（LOG-07）。

覆盖：
- ``record_inbound_webhook`` 入库前必经脱敏（headers / raw_body 落库无明文，对称守护）；
- 飞书 webhook 集成：一次 POST → TriggerLog 与 InboundWebhookEvent 双写（既有 TriggerLog 零回归）；
- 留痕失败 best-effort（acreate 抛异常不冒泡，绝不反噬主流程）；
- WebhookEventListView IsSuperUser 403 / 200 倒序 + kind 筛选。
"""

from __future__ import annotations

import json

import pytest
from django.utils import timezone

from common.logging import REDACTED
from system.models import InboundWebhookEvent

LIST_URL = "/api/system/webhooks/"


def _mk_event(**kwargs) -> InboundWebhookEvent:
    defaults = {
        "received_at": timezone.now(),
        "kind": "feishu",
        "source_ip": "1.2.3.4",
        "headers": {},
        "raw_body": "{}",
        "user_id": "system",
        "verified": False,
        "correlation": {},
    }
    defaults.update(kwargs)
    return InboundWebhookEvent.objects.create(**defaults)


@pytest.mark.django_db(transaction=True)
class TestRecordInboundWebhookRedaction:
    """脱敏不破对称守护：落库 headers / raw_body 绝不含明文凭证。"""

    @pytest.mark.asyncio
    async def test_dict_body_and_headers_redacted(self):
        from asgiref.sync import sync_to_async

        from system.webhook_recorder import record_inbound_webhook

        await record_inbound_webhook(
            kind="feishu",
            raw_body={"token": "sk-ant-leaktest1234567890", "x": 1},
            headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"},
            source_ip="10.0.0.1",
            correlation={"event_uuid": "u1"},
        )

        row = await sync_to_async(
            lambda: InboundWebhookEvent.objects.order_by("-id").first()
        )()
        assert row is not None
        serialized = json.dumps({"headers": row.headers, "raw_body": row.raw_body})
        # 明文凭证绝不落库；脱敏占位符必须出现。
        assert "sk-ant-leaktest1234567890" not in serialized
        assert "eyJhbGciOiJIUzI1NiI" not in serialized
        assert REDACTED in serialized
        # 非敏感字段保留（x=1 在 raw_body 中）。
        assert '"x": 1' in row.raw_body or '"x":1' in row.raw_body
        assert row.correlation == {"event_uuid": "u1"}

    @pytest.mark.asyncio
    async def test_str_json_body_redacted(self):
        from asgiref.sync import sync_to_async

        from system.webhook_recorder import record_inbound_webhook

        # 字符串 body 先尝试 JSON 解析走结构化脱敏（命中字段名命门）。
        raw = json.dumps({"api_key": "sk-ant-leaktest1234567890", "ok": True})
        await record_inbound_webhook(kind="git_push", raw_body=raw)

        row = await sync_to_async(
            lambda: InboundWebhookEvent.objects.order_by("-id").first()
        )()
        assert row is not None
        assert "sk-ant-leaktest1234567890" not in row.raw_body
        assert REDACTED in row.raw_body

    @pytest.mark.asyncio
    async def test_record_failure_swallowed(self, monkeypatch):
        """acreate 抛异常 → record_inbound_webhook 不冒泡（best-effort 绝不反噬业务）。"""
        from system import webhook_recorder

        async def _boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(
            webhook_recorder.InboundWebhookEvent.objects, "acreate", _boom
        )

        # 不抛即通过。
        await webhook_recorder.record_inbound_webhook(
            kind="feishu", raw_body={"a": 1}
        )


@pytest.mark.django_db
class TestFeishuWebhookDoubleWrite:
    """飞书 webhook 双写：一次 POST → TriggerLog 与 InboundWebhookEvent 各落库（零回归）。"""

    def test_feishu_event_double_write(self, api_client):
        from feishu.models import TriggerLog

        resp = api_client.post(
            "/api/feishu/webhook/",
            data={
                "header": {"uuid": "evt-1", "event_type": "WorkitemCreateEvent"},
                "payload": {"id": "wi-1"},
            },
            format="json",
        )
        # 无匹配空间 → IGNORED，但 TriggerLog 与 InboundWebhookEvent 均应各落 1 行。
        assert resp.status_code == 200
        assert TriggerLog.objects.count() == 1
        assert InboundWebhookEvent.objects.count() == 1
        evt = InboundWebhookEvent.objects.first()
        assert evt.kind == "feishu"
        assert evt.correlation.get("event_uuid") == "evt-1"

    def test_url_verification_not_recorded(self, api_client):
        """challenge 验证不算入站事件，不应留痕。"""
        resp = api_client.post(
            "/api/feishu/webhook/",
            data={"type": "url_verification", "challenge": "c1"},
            format="json",
        )
        assert resp.status_code == 200
        assert InboundWebhookEvent.objects.count() == 0


@pytest.mark.django_db
class TestWorkflowWebhookRecording:
    """通用工作流 webhook（POST /api/webhook/<path>/）入站留痕（LOG-07）。"""

    def test_workflow_webhook_records_redacted_event(self, api_client):
        # 无匹配 WebhookConfig → 业务返回 200 no_workflows，但仍应留痕一条 kind=workflow。
        resp = api_client.post(
            "/api/webhook/some-hook-path/",
            data={"api_key": "sk-ant-leaktest1234567890", "ok": True},
            format="json",
        )
        assert resp.status_code in (200, 201)

        evt = InboundWebhookEvent.objects.filter(kind="workflow").first()
        assert evt is not None
        assert evt.kind == "workflow"
        assert evt.correlation.get("webhook_path") == "some-hook-path"
        # 入库前必经脱敏：明文凭证绝不落库，脱敏占位符出现。
        assert "sk-ant-leaktest1234567890" not in evt.raw_body
        assert REDACTED in evt.raw_body


@pytest.mark.django_db
class TestWebhookEventListView:
    def test_non_superuser_forbidden(self, api_client, user):
        api_client.force_authenticate(user=user)
        assert api_client.get(LIST_URL).status_code == 403

    def test_anonymous_forbidden(self, api_client):
        assert api_client.get(LIST_URL).status_code in (401, 403)

    def test_list_desc_order_and_kind_filter(self, api_client, admin_user):
        from datetime import timedelta

        base = timezone.now()
        _mk_event(kind="feishu", received_at=base - timedelta(minutes=2))
        _mk_event(kind="git_push", received_at=base - timedelta(minutes=1))
        _mk_event(kind="feishu", received_at=base)

        api_client.force_authenticate(user=admin_user)
        data = api_client.get(LIST_URL).json()
        assert data["total"] == 3
        received = [item["received_at"] for item in data["items"]]
        assert received == sorted(received, reverse=True)

        data = api_client.get(LIST_URL, {"kind": "feishu"}).json()
        assert data["total"] == 2
        assert all(item["kind"] == "feishu" for item in data["items"])

    def test_detail_returns_redacted_raw(self, api_client, admin_user):
        evt = _mk_event(
            kind="feishu",
            headers={"Authorization": REDACTED},
            raw_body=json.dumps({"token": REDACTED}),
        )
        api_client.force_authenticate(user=admin_user)
        resp = api_client.get(f"{LIST_URL}{evt.id}/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["kind"] == "feishu"
        assert REDACTED in json.dumps({"h": body["headers"], "b": body["raw_body"]})

    def test_detail_not_found(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        assert api_client.get(f"{LIST_URL}999999/").status_code == 404
