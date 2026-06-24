"""系统日志落库队列 + 后台批量 worker 测试（LOG-02）。

覆盖：批量落库 / 队列满丢弃计数 / dict→model 字段映射 / 落库失败计数（绝不反噬业务）。
"""

from __future__ import annotations

import pytest

from system import log_sink
from system.models import SystemLogEntry


@pytest.fixture(autouse=True)
def _reset_sink():
    """每个用例前后清空队列与计数，保证隔离。"""
    log_sink._reset_for_tests()
    yield
    log_sink._reset_for_tests()


@pytest.mark.django_db
class TestEnqueueAndFlush:
    def test_enqueue_then_flush_persists_all(self):
        for i in range(200):
            log_sink.enqueue_system_log(
                {"ts": "2026-06-24T12:00:00Z", "level": "info", "event": f"e{i}"}
            )
        log_sink.flush_now()

        assert SystemLogEntry.objects.count() == 200
        counters = log_sink.snapshot_counters()
        assert counters["enqueued"] == 200
        assert counters["written"] == 200
        assert counters["queued"] == 0

    def test_queue_full_drops_and_counts(self):
        # 塞 5001 条不 flush：第 5001 条触发满丢弃。
        for i in range(5001):
            log_sink.enqueue_system_log({"event": f"e{i}", "level": "info"})
        counters = log_sink.snapshot_counters()
        assert counters["dropped"] >= 1
        assert counters["queued"] <= 5000


class TestToEntryMapping:
    def test_warning_normalized_to_warn(self):
        entry = log_sink._to_entry({"level": "WARNING", "event": "x"})
        assert entry["level"] == "warn"

    def test_missing_ts_defaults_to_now(self):
        entry = log_sink._to_entry({"event": "x"})
        assert entry["ts"] is not None

    def test_unknown_fields_go_to_payload(self):
        entry = log_sink._to_entry({"event": "x", "custom_field": "v", "extra": 1})
        assert entry["payload"]["custom_field"] == "v"
        assert entry["payload"]["extra"] == 1

    def test_correlation_keys_extracted(self):
        entry = log_sink._to_entry(
            {"event": "x", "conversation_id": "c-1", "run_id": "r-1", "other": "o"}
        )
        assert entry["correlation"]["conversation_id"] == "c-1"
        assert entry["correlation"]["run_id"] == "r-1"
        # 关联键移出 payload，避免重复存储。
        assert "conversation_id" not in entry["payload"]
        assert entry["payload"]["other"] == "o"

    def test_message_falls_back_to_event(self):
        entry = log_sink._to_entry({"event": "some_event"})
        assert entry["message"] == "some_event"


@pytest.mark.django_db
class TestWriteFailureBestEffort:
    def test_bulk_create_error_increments_write_failed_and_no_raise(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(SystemLogEntry.objects, "bulk_create", _boom)

        for i in range(10):
            log_sink.enqueue_system_log({"event": f"e{i}", "level": "info"})
        # flush 不应冒泡异常。
        log_sink.flush_now()

        counters = log_sink.snapshot_counters()
        assert counters["write_failed"] == 10
        assert counters["written"] == 0
