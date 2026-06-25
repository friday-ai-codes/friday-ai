"""系统日志中心查询 / 清理 / 保留清理 API 测试（LOG-01 / LOG-03 / LOG-08）。

覆盖：
- 查询：倒序 + 组件/级别/用户/来源/关键词(icontains)/时间段筛选 + 顶部四计数；
- 权限：非超管 403（IsSuperUser fail-closed）；
- 清理：按条件批量删 / 无条件需 confirm_all 防误清 / confirm_all 全删；
- 保留：按天数 + 行数清理 SystemLogEntry，及 InboundWebhookEvent 同款。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from system.models import InboundWebhookEvent, SystemLogEntry

QUERY_URL = "/api/system/logs/"
CLEAR_URL = "/api/system/logs/clear/"


def _mk_log(**kwargs) -> SystemLogEntry:
    """造一条 SystemLogEntry，ts 默认 now（可被 kwargs 覆盖）。"""
    defaults = {
        "ts": timezone.now(),
        "level": "info",
        "component": "test",
        "category": "caller",
        "event": "test_event",
        "message": "hello world",
        "user_id": "system",
        "source": "rest",
    }
    defaults.update(kwargs)
    return SystemLogEntry.objects.create(**defaults)


@pytest.fixture(autouse=True)
def _reset_sink():
    """每个用例前后清空落库队列计数，保证 counters 断言隔离。"""
    from system import log_sink

    log_sink._reset_for_tests()
    yield
    log_sink._reset_for_tests()


@pytest.mark.django_db
class TestSystemLogQuery:
    def test_query_returns_desc_order_with_counters(self, api_client, admin_user):
        base = timezone.now()
        for i in range(5):
            _mk_log(ts=base - timedelta(minutes=i), event=f"e{i}", message=f"msg {i}")

        api_client.force_authenticate(user=admin_user)
        resp = api_client.get(QUERY_URL)
        assert resp.status_code == 200
        data = resp.json()

        assert data["total"] == 5
        assert len(data["items"]) == 5
        # 倒序：第一条 ts 最新（minutes=0）。
        ts_list = [item["ts"] for item in data["items"]]
        assert ts_list == sorted(ts_list, reverse=True)
        # 顶部四计数齐全。
        for key in ("queued", "max", "enqueued", "written", "dropped", "write_failed"):
            assert key in data["counters"], f"counters 缺少 {key}"

    def test_filter_by_component(self, api_client, admin_user):
        _mk_log(component="alpha")
        _mk_log(component="beta")
        api_client.force_authenticate(user=admin_user)
        data = api_client.get(QUERY_URL, {"component": "alpha"}).json()
        assert data["total"] == 1
        assert data["items"][0]["component"] == "alpha"

    def test_filter_by_level_normalizes_warning(self, api_client, admin_user):
        _mk_log(level="warn", event="w")
        _mk_log(level="error", event="e")
        api_client.force_authenticate(user=admin_user)
        # 传 WARNING 应归一为 warn 命中。
        data = api_client.get(QUERY_URL, {"level": "WARNING"}).json()
        assert data["total"] == 1
        assert data["items"][0]["level"] == "warn"

    def test_filter_by_user_id(self, api_client, admin_user):
        _mk_log(user_id="42")
        _mk_log(user_id="system")
        api_client.force_authenticate(user=admin_user)
        data = api_client.get(QUERY_URL, {"user_id": "42"}).json()
        assert data["total"] == 1
        assert data["items"][0]["user_id"] == "42"

    def test_filter_by_source(self, api_client, admin_user):
        _mk_log(source="mcp")
        _mk_log(source="rest")
        api_client.force_authenticate(user=admin_user)
        data = api_client.get(QUERY_URL, {"source": "mcp"}).json()
        assert data["total"] == 1
        assert data["items"][0]["source"] == "mcp"

    def test_filter_by_keyword_icontains(self, api_client, admin_user):
        _mk_log(message="database connection failed")
        _mk_log(message="all good")
        api_client.force_authenticate(user=admin_user)
        data = api_client.get(QUERY_URL, {"keyword": "CONNECTION"}).json()
        assert data["total"] == 1
        assert "connection" in data["items"][0]["message"]

    def test_filter_by_start_end(self, api_client, admin_user):
        now = timezone.now()
        _mk_log(ts=now - timedelta(days=10), event="old")
        _mk_log(ts=now, event="recent")
        api_client.force_authenticate(user=admin_user)
        start = (now - timedelta(days=1)).isoformat()
        data = api_client.get(QUERY_URL, {"start": start}).json()
        assert data["total"] == 1
        assert data["items"][0]["event"] == "recent"

    def test_filter_by_call_source_payload(self, api_client, admin_user):
        """高级维度 call_source：payload jsonb 顶层键服务端精确筛选（非当前页 narrowing）。"""
        _mk_log(payload={"call_source": "chat_completion", "model": "gpt"})
        _mk_log(payload={"call_source": "mcp_read", "model": "gpt"})
        api_client.force_authenticate(user=admin_user)
        data = api_client.get(QUERY_URL, {"call_source": "chat_completion"}).json()
        assert data["total"] == 1
        assert data["items"][0]["payload"]["call_source"] == "chat_completion"

    def test_filter_by_provider_payload(self, api_client, admin_user):
        """高级维度 provider：payload jsonb 顶层键服务端精确筛选。"""
        _mk_log(payload={"provider": "anthropic"})
        _mk_log(payload={"provider": "openai"})
        api_client.force_authenticate(user=admin_user)
        data = api_client.get(QUERY_URL, {"provider": "anthropic"}).json()
        assert data["total"] == 1
        assert data["items"][0]["payload"]["provider"] == "anthropic"

    def test_filter_by_credential_payload(self, api_client, admin_user):
        """高级维度 credential：payload jsonb 顶层键服务端精确筛选。"""
        _mk_log(payload={"credential": "cred-a"})
        _mk_log(payload={"credential": "cred-b"})
        api_client.force_authenticate(user=admin_user)
        data = api_client.get(QUERY_URL, {"credential": "cred-a"}).json()
        assert data["total"] == 1
        assert data["items"][0]["payload"]["credential"] == "cred-a"

    def test_filter_by_model_payload(self, api_client, admin_user):
        """高级维度 model：payload jsonb 顶层键服务端精确筛选。"""
        _mk_log(payload={"model": "claude-sonnet"})
        _mk_log(payload={"model": "gpt-4o"})
        api_client.force_authenticate(user=admin_user)
        data = api_client.get(QUERY_URL, {"model": "claude-sonnet"}).json()
        assert data["total"] == 1
        assert data["items"][0]["payload"]["model"] == "claude-sonnet"

    def test_filter_by_correlation_substring(self, api_client, admin_user):
        """关联键 correlation：correlation jsonb 文本化子串检索（任意键/值命中）。"""
        _mk_log(correlation={"run_id": "run-abc-123", "conversation_id": "conv-1"})
        _mk_log(correlation={"run_id": "run-xyz-999"})
        api_client.force_authenticate(user=admin_user)
        # 子串命中 run_id 值。
        data = api_client.get(QUERY_URL, {"correlation": "abc-123"}).json()
        assert data["total"] == 1
        assert data["items"][0]["correlation"]["run_id"] == "run-abc-123"
        # 命中另一条的 conversation_id 值。
        data2 = api_client.get(QUERY_URL, {"correlation": "conv-1"}).json()
        assert data2["total"] == 1

    def test_limit_and_offset(self, api_client, admin_user):
        base = timezone.now()
        for i in range(10):
            _mk_log(ts=base - timedelta(minutes=i), event=f"e{i}")
        api_client.force_authenticate(user=admin_user)
        data = api_client.get(QUERY_URL, {"limit": 3, "offset": 0}).json()
        assert data["total"] == 10
        assert len(data["items"]) == 3


@pytest.mark.django_db
class TestSystemLogQueryPermission:
    def test_non_superuser_forbidden(self, api_client, user):
        api_client.force_authenticate(user=user)
        assert api_client.get(QUERY_URL).status_code == 403

    def test_anonymous_forbidden(self, api_client):
        assert api_client.get(QUERY_URL).status_code in (401, 403)


@pytest.mark.django_db
class TestSystemLogClear:
    def test_clear_by_level(self, api_client, admin_user):
        _mk_log(level="debug")
        _mk_log(level="debug")
        _mk_log(level="info")
        api_client.force_authenticate(user=admin_user)
        resp = api_client.post(CLEAR_URL, {"level": "debug"}, format="json")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 2
        assert SystemLogEntry.objects.count() == 1
        assert SystemLogEntry.objects.filter(level="info").exists()

    def test_clear_by_advanced_dim_call_source(self, api_client, admin_user):
        """按高级维度（call_source）清理：_has_any_filter 识别该维度，无需 confirm_all。"""
        _mk_log(payload={"call_source": "chat_completion"})
        _mk_log(payload={"call_source": "mcp_read"})
        api_client.force_authenticate(user=admin_user)
        resp = api_client.post(CLEAR_URL, {"call_source": "chat_completion"}, format="json")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1
        assert SystemLogEntry.objects.count() == 1
        assert SystemLogEntry.objects.filter(payload__call_source="mcp_read").exists()

    def test_clear_without_condition_requires_confirm(self, api_client, admin_user):
        _mk_log()
        api_client.force_authenticate(user=admin_user)
        resp = api_client.post(CLEAR_URL, {}, format="json")
        assert resp.status_code == 400
        # 未删除任何行。
        assert SystemLogEntry.objects.count() == 1

    def test_clear_all_with_confirm(self, api_client, admin_user):
        _mk_log()
        _mk_log()
        api_client.force_authenticate(user=admin_user)
        resp = api_client.post(CLEAR_URL, {"confirm_all": True}, format="json")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 2
        assert SystemLogEntry.objects.count() == 0

    def test_clear_non_superuser_forbidden(self, api_client, user):
        api_client.force_authenticate(user=user)
        assert api_client.post(CLEAR_URL, {"confirm_all": True}, format="json").status_code == 403


@pytest.mark.django_db(transaction=True)
class TestRetentionPurge:
    """保留清理走 async ORM（``sync_to_async``）：必须 ``transaction=True`` 让落库
    数据跨线程连接可见、并在用例间真正清表（避免异步事务回滚不生效导致数据泄漏）。
    """

    async def _amk_log(self, **kwargs):
        from asgiref.sync import sync_to_async

        return await sync_to_async(_mk_log)(**kwargs)

    @pytest.mark.asyncio
    async def test_purge_system_logs_by_age(self):
        from asgiref.sync import sync_to_async

        from system.log_retention import purge_system_logs
        from system.models import SettingKeys, SystemSetting

        now = timezone.now()
        await self._amk_log(ts=now - timedelta(days=10), event="old")
        await self._amk_log(ts=now, event="recent")
        await sync_to_async(SystemSetting.objects.create)(
            key=SettingKeys.LOG_RETENTION_DAYS, value="7"
        )

        result = await purge_system_logs()
        assert result["by_age"] == 1
        remaining = await sync_to_async(
            lambda: list(SystemLogEntry.objects.values_list("event", flat=True))
        )()
        assert remaining == ["recent"]

    @pytest.mark.asyncio
    async def test_purge_system_logs_by_size(self):
        from asgiref.sync import sync_to_async

        from system.log_retention import purge_system_logs
        from system.models import SettingKeys, SystemSetting

        now = timezone.now()
        for i in range(5):
            await self._amk_log(ts=now - timedelta(minutes=i), event=f"e{i}")
        # 天数极大（不按 age 删），行数上限 3 → 删最旧 2 条。
        await sync_to_async(SystemSetting.objects.create)(
            key=SettingKeys.LOG_RETENTION_DAYS, value="3650"
        )
        await sync_to_async(SystemSetting.objects.create)(
            key=SettingKeys.LOG_RETENTION_SIZE, value="3"
        )

        result = await purge_system_logs()
        assert result["by_size"] == 2
        count = await sync_to_async(SystemLogEntry.objects.count)()
        assert count == 3
        # 保留的是最新的（e0/e1/e2），最旧 e4/e3 被删。
        remaining = await sync_to_async(
            lambda: set(SystemLogEntry.objects.values_list("event", flat=True))
        )()
        assert remaining == {"e0", "e1", "e2"}

    @pytest.mark.asyncio
    async def test_purge_webhook_events_by_age(self):
        from asgiref.sync import sync_to_async

        from system.log_retention import purge_webhook_events
        from system.models import SettingKeys, SystemSetting

        now = timezone.now()
        await sync_to_async(InboundWebhookEvent.objects.create)(
            received_at=now - timedelta(days=10), kind="feishu"
        )
        await sync_to_async(InboundWebhookEvent.objects.create)(
            received_at=now, kind="feishu"
        )
        await sync_to_async(SystemSetting.objects.create)(
            key=SettingKeys.LOG_RETENTION_DAYS, value="7"
        )

        result = await purge_webhook_events()
        assert result["by_age"] == 1
        count = await sync_to_async(InboundWebhookEvent.objects.count)()
        assert count == 1
