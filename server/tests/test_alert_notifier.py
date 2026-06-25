"""系统告警三通道分发守护测试（ALERT-03）。

覆盖 Requirement: ALERT-03
威胁参考: T-74-03-01（正文/异常脱敏）、T-74-03-02（webhook SSRF）、
          T-74-03-03/04（best-effort 绝不反噬评估）

要点：
- email 未配置/失败 → skipped/failed，绝不抛；正文经 redact_secrets_in_text 脱敏。
- webhook 对内网 URL 走 SSRF 拦截（不发请求）；正文脱敏。
- feishu 复用 FeishuIMService（monkeypatch）；未配置 chat_id 不调 create。
- notify_channels 汇总三通道结果、回写 email_sent + notified_channels，任一 helper
  抛错仍不冒泡（最外层兜底）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest import mock

import httpx
import pytest
import respx

from common.logging import REDACTED

LEAK_SECRET = "sk-ant-leaktest1234567890"


async def _make_event(**overrides: Any) -> Any:
    """构造一条最小 AlertEvent（async acreate）。"""
    from system.models import AlertEvent

    defaults: dict[str, Any] = dict(
        severity="P0",
        title_zh="CPU 使用率过高",
        rule_info={"expr": "cpu_usage_percent > 85.00 (current 95.40) over last 5m"},
        target={},
        status="firing",
        started_at=datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc),
        current_value=95.4,
    )
    defaults.update(overrides)
    return await AlertEvent.objects.acreate(**defaults)


async def _set_setting(key: str, value: str) -> None:
    from system.models import SystemSetting

    await SystemSetting.objects.aupdate_or_create(key=key, defaults={"value": value})


@pytest.mark.django_db(transaction=True)
class TestSendEmail:
    """EMAIL 通道：skipped/sent/failed 三态 + 正文脱敏。"""

    async def test_skipped_when_unconfigured(self) -> None:
        """未开启 + EMAIL_HOST 空 → skipped，不抛。"""
        from system import alert_notifier

        event = await _make_event()
        status = await alert_notifier._send_email(event)
        assert status == "skipped"

    async def test_sent_and_body_redacted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """开启 + 配置齐全 → sent，且传入 send_mail 的 body 脱敏。"""
        from django.conf import settings

        from system import alert_notifier
        from system.models import SettingKeys

        monkeypatch.setattr(settings, "EMAIL_HOST", "smtp.example.com", raising=False)
        await _set_setting(SettingKeys.ALERT_EMAIL_ENABLED, "true")
        await _set_setting(SettingKeys.ALERT_EMAIL_RECIPIENTS, "ops@example.com, sre@example.com")

        captured: dict[str, Any] = {}

        def _fake_send_mail(subject, body, from_email, recipients, fail_silently=False):
            captured["subject"] = subject
            captured["body"] = body
            captured["recipients"] = recipients
            return 1

        monkeypatch.setattr("django.core.mail.send_mail", _fake_send_mail)

        # 注入明文凭证到 rule_info.expr，验证正文脱敏。
        event = await _make_event(
            rule_info={"expr": f"leaked {LEAK_SECRET} in expr"},
        )
        status = await alert_notifier._send_email(event)

        assert status == "sent"
        assert captured["recipients"] == ["ops@example.com", "sre@example.com"]
        assert LEAK_SECRET not in captured["body"]
        assert REDACTED in captured["body"]

    async def test_skipped_when_no_recipients(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """开启 + 有 host 但无收件人 → skipped。"""
        from django.conf import settings

        from system import alert_notifier
        from system.models import SettingKeys

        monkeypatch.setattr(settings, "EMAIL_HOST", "smtp.example.com", raising=False)
        await _set_setting(SettingKeys.ALERT_EMAIL_ENABLED, "true")

        event = await _make_event()
        assert await alert_notifier._send_email(event) == "skipped"

    async def test_failed_when_send_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """send_mail 抛错 → failed，不冒泡。"""
        from django.conf import settings

        from system import alert_notifier
        from system.models import SettingKeys

        monkeypatch.setattr(settings, "EMAIL_HOST", "smtp.example.com", raising=False)
        await _set_setting(SettingKeys.ALERT_EMAIL_ENABLED, "true")
        await _set_setting(SettingKeys.ALERT_EMAIL_RECIPIENTS, "ops@example.com")

        def _boom(*args, **kwargs):
            raise RuntimeError("smtp down")

        monkeypatch.setattr("django.core.mail.send_mail", _boom)

        event = await _make_event()
        assert await alert_notifier._send_email(event) == "failed"


@pytest.mark.django_db(transaction=True)
class TestSendWebhook:
    """webhook 通道：SSRF 拦截 + 合法发送 + 正文脱敏。"""

    @respx.mock
    async def test_internal_host_blocked(self) -> None:
        """内网 URL → False，且未命中任何请求（SSRF 拦截）。"""
        from system import alert_notifier
        from system.models import SettingKeys

        await _set_setting(SettingKeys.ALERT_WEBHOOK_URL, "http://127.0.0.1/hook")
        route = respx.post("http://127.0.0.1/hook").mock(
            return_value=httpx.Response(200)
        )

        event = await _make_event()
        ok = await alert_notifier._send_webhook(event)

        assert ok is False
        assert not route.called

    @respx.mock
    async def test_legal_url_sent_and_redacted(self) -> None:
        """合法 URL 200 → True，且 payload 脱敏。"""
        from system import alert_notifier
        from system.models import SettingKeys

        await _set_setting(SettingKeys.ALERT_WEBHOOK_URL, "https://hooks.example.com/alert")
        route = respx.post("https://hooks.example.com/alert").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        event = await _make_event(
            rule_info={"expr": f"leaked {LEAK_SECRET}"},
        )
        ok = await alert_notifier._send_webhook(event)

        assert ok is True
        assert route.called
        sent_body = route.calls.last.request.content.decode("utf-8")
        assert LEAK_SECRET not in sent_body
        assert REDACTED in sent_body

    @respx.mock
    async def test_4xx_returns_false(self) -> None:
        """>=400 → False，不抛。"""
        from system import alert_notifier
        from system.models import SettingKeys

        await _set_setting(SettingKeys.ALERT_WEBHOOK_URL, "https://hooks.example.com/alert")
        respx.post("https://hooks.example.com/alert").mock(
            return_value=httpx.Response(500)
        )

        event = await _make_event()
        assert await alert_notifier._send_webhook(event) is False

    async def test_unconfigured_returns_false(self) -> None:
        """未配置 URL → False。"""
        from system import alert_notifier

        event = await _make_event()
        assert await alert_notifier._send_webhook(event) is False


@pytest.mark.django_db(transaction=True)
class TestSendFeishu:
    """飞书通道：复用 FeishuIMService（monkeypatch）。"""

    async def test_sent_when_chat_id_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """配置 chat_id → True，send_card 被调用。"""
        from system import alert_notifier
        from system.models import SettingKeys

        await _set_setting(SettingKeys.ALERT_FEISHU_CHAT_ID, "oc_test_chat")

        fake_im = mock.AsyncMock()
        fake_im.send_card = mock.AsyncMock(return_value="msg_1")
        create_mock = mock.AsyncMock(return_value=fake_im)
        monkeypatch.setattr(
            "services.feishu_im.FeishuIMService.create", create_mock
        )

        event = await _make_event()
        ok = await alert_notifier._send_feishu(event)

        assert ok is True
        create_mock.assert_awaited_once()
        fake_im.send_card.assert_awaited_once()

    async def test_skipped_when_no_chat_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未配置 chat_id → False，且不调 create。"""
        from system import alert_notifier

        create_mock = mock.AsyncMock()
        monkeypatch.setattr(
            "services.feishu_im.FeishuIMService.create", create_mock
        )

        event = await _make_event()
        ok = await alert_notifier._send_feishu(event)

        assert ok is False
        create_mock.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
class TestNotifyChannels:
    """单一分发出口汇总 + 回写 + 最外层兜底。"""

    async def test_aggregates_and_persists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """email=sent / feishu=True / webhook=False → 回写正确、不抛。"""
        from system import alert_notifier

        async def _email(event):
            return "sent"

        async def _feishu(event):
            return True

        async def _webhook(event):
            return False

        monkeypatch.setattr(alert_notifier, "_send_email", _email)
        monkeypatch.setattr(alert_notifier, "_send_feishu", _feishu)
        monkeypatch.setattr(alert_notifier, "_send_webhook", _webhook)

        event = await _make_event()
        result = await alert_notifier.notify_channels(
            event, ["email", "feishu", "webhook"]
        )

        assert result["email"] == "sent"
        # 回写：email_sent=sent；webhook 失败不入 notified_channels。
        from system.models import AlertEvent

        refreshed = await AlertEvent.objects.aget(id=event.id)
        assert refreshed.email_sent == "sent"
        assert refreshed.notified_channels == ["email", "feishu"]

    async def test_helper_exception_does_not_propagate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """某 helper 抛错 → notify_channels 仍不冒泡（最外层兜底）。"""
        from system import alert_notifier

        async def _boom(event):
            raise RuntimeError("channel exploded")

        monkeypatch.setattr(alert_notifier, "_send_email", _boom)

        event = await _make_event()
        # 不抛即通过（兜底返回空 dict）。
        result = await alert_notifier.notify_channels(event, ["email"])
        assert result == {}

    async def test_email_not_selected_keeps_pending(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """未选 email 通道 → email_sent 保留默认 pending。"""
        from system import alert_notifier

        async def _feishu(event):
            return True

        monkeypatch.setattr(alert_notifier, "_send_feishu", _feishu)

        event = await _make_event()
        await alert_notifier.notify_channels(event, ["feishu"])

        from system.models import AlertEvent

        refreshed = await AlertEvent.objects.aget(id=event.id)
        assert refreshed.email_sent == "pending"
        assert refreshed.notified_channels == ["feishu"]
