"""系统告警模型测试（ALERT-01/02）：SystemAlertRule + AlertEvent + SettingKeys.ALERT_*。

覆盖：
- SystemAlertRule 字段持久化 + 默认值（enabled=True / cooldown=600）；
- AlertEvent 去重条件唯一约束 (rule,target_key) status=firing 生效（重复抛 IntegrityError）；
- resolved 后约束释放，可再建 firing；
- SettingKeys.ALERT_* 7 常量存在且为点分命名。
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError
from django.utils import timezone

from system.models import AlertEvent, SettingKeys, SystemAlertRule


@pytest.mark.django_db
class TestSystemAlertRule:
    def test_create_persists_fields_and_defaults(self):
        rule = SystemAlertRule.objects.create(
            name="CPU 高水位",
            metric="cpu",
            op="gt",
            value=85.0,
            severity="P1",
            channels=["email", "feishu"],
        )
        rule.refresh_from_db()
        assert rule.metric == "cpu"
        assert rule.op == "gt"
        assert rule.value == 85.0
        assert rule.channels == ["email", "feishu"]
        # 默认值。
        assert rule.enabled is True
        assert rule.cooldown == 600
        assert rule.window == 300
        assert rule.dimension == {}
        assert rule.title_template == ""


@pytest.mark.django_db
class TestAlertEventDedup:
    def _mk_rule(self) -> SystemAlertRule:
        return SystemAlertRule.objects.create(
            name="r", metric="cpu", op="gt", value=85.0, severity="P1"
        )

    def test_duplicate_firing_raises_integrity_error(self):
        rule = self._mk_rule()
        AlertEvent.objects.create(
            rule=rule,
            severity="P1",
            status="firing",
            target_key="{}",
            started_at=timezone.now(),
        )
        # 同 (rule, target_key) 再建 firing → 去重约束抛 IntegrityError。
        with pytest.raises(IntegrityError):
            AlertEvent.objects.create(
                rule=rule,
                severity="P1",
                status="firing",
                target_key="{}",
                started_at=timezone.now(),
            )

    def test_constraint_released_after_resolved(self):
        rule = self._mk_rule()
        first = AlertEvent.objects.create(
            rule=rule,
            severity="P1",
            status="firing",
            target_key="{}",
            started_at=timezone.now(),
        )
        # 首条转 resolved → 约束释放。
        first.status = "resolved"
        first.ended_at = timezone.now()
        first.save(update_fields=["status", "ended_at"])
        # 可再建一条同 (rule, target_key) firing。
        second = AlertEvent.objects.create(
            rule=rule,
            severity="P1",
            status="firing",
            target_key="{}",
            started_at=timezone.now(),
        )
        assert second.pk != first.pk
        assert AlertEvent.objects.filter(rule=rule, status="firing").count() == 1


@pytest.mark.django_db
class TestAlertSettingKeys:
    def test_alert_setting_keys_present_and_dotted(self):
        expected = {
            "ALERT_EVAL_INTERVAL_SECONDS": "alert.eval_interval_seconds",
            "ALERT_RETENTION_DAYS": "alert.retention_days",
            "ALERT_RETENTION_SIZE": "alert.retention_max_rows",
            "ALERT_EMAIL_ENABLED": "alert.email_enabled",
            "ALERT_EMAIL_RECIPIENTS": "alert.email_recipients",
            "ALERT_FEISHU_CHAT_ID": "alert.feishu_chat_id",
            "ALERT_WEBHOOK_URL": "alert.webhook_url",
        }
        for attr, value in expected.items():
            assert hasattr(SettingKeys, attr), f"SettingKeys 缺少 {attr}"
            assert getattr(SettingKeys, attr) == value
            assert value.startswith("alert.")
