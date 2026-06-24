"""系统告警 CRUD + 事件查询 + 保留清理 API 测试（ALERT-01/02 + 清理）。

覆盖：
- 规则 CRUD：超管 POST 201、PATCH 200、DELETE 204；
- 权限：非超管 403（IsSuperUser fail-closed）；
- 白名单防御：非法 metric / channels 含 sms → 400 中文 detail；
- 事件查询：severity/status 筛选 + 倒序 + total；非超管 403；
- 保留清理：按龄 / 按量清理 AlertEvent（started_at 口径）+ 失败降级 best-effort。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from system.models import AlertEvent, SystemAlertRule

RULES_URL = "/api/system/alerts/rules/"
EVENTS_URL = "/api/system/alerts/events/"


def _valid_rule_body(**overrides) -> dict:
    body = {
        "name": "CPU 高水位",
        "metric": "cpu",
        "op": "gt",
        "value": 85.0,
        "severity": "P1",
        "channels": ["email", "feishu"],
        "dimension": {},
    }
    body.update(overrides)
    return body


@pytest.mark.django_db
class TestSystemAlertRuleCRUD:
    def test_create_rule_returns_201(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        resp = api_client.post(RULES_URL, _valid_rule_body(), format="json")
        assert resp.status_code == 201, resp.content
        data = resp.json()
        assert data["metric"] == "cpu"
        assert data["enabled"] is True
        assert data["cooldown"] == 600
        assert SystemAlertRule.objects.filter(id=data["id"]).exists()

    def test_list_rules(self, api_client, admin_user):
        SystemAlertRule.objects.create(
            name="r1", metric="cpu", op="gt", value=85.0, severity="P1"
        )
        SystemAlertRule.objects.create(
            name="r2", metric="qps", op="gt", value=100.0, severity="P2", enabled=False
        )
        api_client.force_authenticate(user=admin_user)
        data = api_client.get(RULES_URL).json()
        assert data["total"] == 2
        # ?enabled=true 仅返回启用规则。
        data_enabled = api_client.get(RULES_URL, {"enabled": "true"}).json()
        assert data_enabled["total"] == 1

    def test_patch_and_delete(self, api_client, admin_user):
        rule = SystemAlertRule.objects.create(
            name="r", metric="cpu", op="gt", value=85.0, severity="P1"
        )
        api_client.force_authenticate(user=admin_user)
        detail = f"{RULES_URL}{rule.id}/"
        resp = api_client.patch(detail, {"enabled": False}, format="json")
        assert resp.status_code == 200
        rule.refresh_from_db()
        assert rule.enabled is False
        # DELETE → 204 + DB 无该规则。
        assert api_client.delete(detail).status_code == 204
        assert not SystemAlertRule.objects.filter(id=rule.id).exists()

    def test_retrieve_404_for_missing(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        assert api_client.get(f"{RULES_URL}999999/").status_code == 404


@pytest.mark.django_db
class TestSystemAlertRuleValidation:
    def test_invalid_metric_rejected(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        resp = api_client.post(RULES_URL, _valid_rule_body(metric="foobar"), format="json")
        assert resp.status_code == 400

    def test_invalid_channel_rejected(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        resp = api_client.post(
            RULES_URL, _valid_rule_body(channels=["email", "sms"]), format="json"
        )
        assert resp.status_code == 400

    def test_invalid_dimension_key_rejected(self, api_client, admin_user):
        api_client.force_authenticate(user=admin_user)
        resp = api_client.post(
            RULES_URL, _valid_rule_body(dimension={"evil": "x"}), format="json"
        )
        assert resp.status_code == 400


@pytest.mark.django_db
class TestSystemAlertRulePermission:
    def test_non_superuser_forbidden(self, api_client, user):
        api_client.force_authenticate(user=user)
        assert api_client.get(RULES_URL).status_code == 403
        assert api_client.post(RULES_URL, _valid_rule_body(), format="json").status_code == 403

    def test_events_non_superuser_forbidden(self, api_client, user):
        api_client.force_authenticate(user=user)
        assert api_client.get(EVENTS_URL).status_code == 403


@pytest.mark.django_db
class TestAlertEventQuery:
    def _mk_event(self, **kwargs) -> AlertEvent:
        defaults = {
            "severity": "P1",
            "status": "firing",
            "started_at": timezone.now(),
            "target_key": "",
        }
        defaults.update(kwargs)
        return AlertEvent.objects.create(**defaults)

    def test_filter_by_severity_and_status(self, api_client, admin_user):
        self._mk_event(severity="P0", status="firing", target_key="a")
        self._mk_event(severity="P1", status="firing", target_key="b")
        self._mk_event(severity="P0", status="resolved", target_key="c")
        api_client.force_authenticate(user=admin_user)
        data = api_client.get(EVENTS_URL, {"severity": "P0", "status": "firing"}).json()
        assert data["total"] == 1
        assert data["items"][0]["severity"] == "P0"
        assert data["items"][0]["status"] == "firing"

    def test_desc_order_by_started_at(self, api_client, admin_user):
        base = timezone.now()
        for i in range(3):
            self._mk_event(started_at=base - timedelta(minutes=i), target_key=f"k{i}")
        api_client.force_authenticate(user=admin_user)
        data = api_client.get(EVENTS_URL).json()
        assert data["total"] == 3
        ts_list = [item["started_at"] for item in data["items"]]
        assert ts_list == sorted(ts_list, reverse=True)


@pytest.mark.django_db(transaction=True)
class TestAlertRetentionPurge:
    """保留清理走 async ORM（``sync_to_async``）：必须 ``transaction=True`` 让落库
    数据跨线程连接可见、并在用例间真正清表（与 log_retention 测试同款）。
    """

    async def _amk_event(self, **kwargs):
        from asgiref.sync import sync_to_async

        defaults = {
            "severity": "P1",
            "status": "firing",
            "started_at": timezone.now(),
        }
        defaults.update(kwargs)
        return await sync_to_async(AlertEvent.objects.create)(**defaults)

    @pytest.mark.asyncio
    async def test_purge_by_age_uses_started_at(self):
        from asgiref.sync import sync_to_async

        from system.alert_retention import purge_alert_events
        from system.models import SettingKeys, SystemSetting

        now = timezone.now()
        await self._amk_event(started_at=now - timedelta(days=120), target_key="old")
        await self._amk_event(started_at=now, target_key="recent")
        await sync_to_async(SystemSetting.objects.create)(
            key=SettingKeys.ALERT_RETENTION_DAYS, value="90"
        )

        result = await purge_alert_events()
        # 不抛 FieldError（按 started_at），删旧留新。
        assert result["by_age"] == 1
        remaining = await sync_to_async(
            lambda: list(AlertEvent.objects.values_list("target_key", flat=True))
        )()
        assert remaining == ["recent"]

    @pytest.mark.asyncio
    async def test_purge_by_size_deletes_oldest(self):
        from asgiref.sync import sync_to_async

        from system.alert_retention import purge_alert_events
        from system.models import SettingKeys, SystemSetting

        now = timezone.now()
        for i in range(5):
            await self._amk_event(
                started_at=now - timedelta(minutes=i), target_key=f"k{i}"
            )
        # 天数极大（不按龄删），行数上限 3 → 删最旧 2 条。
        await sync_to_async(SystemSetting.objects.create)(
            key=SettingKeys.ALERT_RETENTION_DAYS, value="3650"
        )
        await sync_to_async(SystemSetting.objects.create)(
            key=SettingKeys.ALERT_RETENTION_SIZE, value="3"
        )

        result = await purge_alert_events()
        assert result["by_size"] == 2
        count = await sync_to_async(AlertEvent.objects.count)()
        assert count == 3
        # 保留最新（k0/k1/k2），最旧 k4/k3 被删。
        remaining = await sync_to_async(
            lambda: set(AlertEvent.objects.values_list("target_key", flat=True))
        )()
        assert remaining == {"k0", "k1", "k2"}

    @pytest.mark.asyncio
    async def test_purge_failure_is_swallowed(self, monkeypatch):
        from system import alert_retention
        from system.alert_retention import purge_alert_events

        async def _boom() -> tuple[int, int]:
            raise RuntimeError("boom")

        # 让配置读取抛错 → best-effort 吞掉，返回部分结果不冒泡。
        monkeypatch.setattr(alert_retention, "_alert_retention_config", _boom)
        result = await purge_alert_events()
        assert result == {"by_age": 0, "by_size": 0}
