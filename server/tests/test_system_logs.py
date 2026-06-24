"""运维监控「系统日志」端点与内存环形缓冲测试。"""

import pytest

LOGS_URL = "/api/system/logs/"


class TestLogBuffer:
    def test_append_and_snapshot_newest_first(self):
        from common.log_buffer import append_log, clear, snapshot

        clear()
        append_log({"ts": "t1", "level": "INFO", "logger": "a", "message": "first"})
        append_log({"ts": "t2", "level": "ERROR", "logger": "b", "message": "second"})
        items = snapshot(limit=10)
        assert [e["message"] for e in items] == ["second", "first"]  # 最新在前

    def test_snapshot_level_filter(self):
        from common.log_buffer import append_log, clear, snapshot

        clear()
        append_log({"ts": "t1", "level": "INFO", "logger": "a", "message": "i"})
        append_log({"ts": "t2", "level": "ERROR", "logger": "b", "message": "e"})
        only_error = snapshot(limit=10, level="ERROR")
        assert [e["message"] for e in only_error] == ["e"]


@pytest.mark.django_db
class TestSystemLogsView:
    """``/api/system/logs/`` 已由内存缓冲版升级为 SystemLogEntry 查询版（71-04 LOG-01）：
    返回 ``{"items", "total", "counters"}``，并向后兼容 ``level`` 查询参数。
    """

    def _mk_log(self, **kwargs):
        from django.utils import timezone

        from system.models import SystemLogEntry

        defaults = {
            "ts": timezone.now(),
            "level": "info",
            "component": "x",
            "message": "line",
        }
        defaults.update(kwargs)
        return SystemLogEntry.objects.create(**defaults)

    def test_non_superuser_forbidden(self, api_client, user):
        api_client.force_authenticate(user=user)
        assert api_client.get(LOGS_URL).status_code == 403

    def test_superuser_gets_logs(self, api_client, admin_user):
        self._mk_log(level="warn", message="hello-obs")
        api_client.force_authenticate(user=admin_user)
        resp = api_client.get(LOGS_URL)
        assert resp.status_code == 200
        body = resp.json()
        # 新契约：items + total + 顶部四计数。
        assert "items" in body
        assert "counters" in body
        assert any(e["message"] == "hello-obs" for e in body["items"])

    def test_level_query_filter(self, api_client, admin_user):
        self._mk_log(level="info", message="info-line")
        self._mk_log(level="error", message="error-line")
        api_client.force_authenticate(user=admin_user)
        body = api_client.get(LOGS_URL, {"level": "ERROR"}).json()
        msgs = [e["message"] for e in body["items"]]
        assert "error-line" in msgs
        assert "info-line" not in msgs
