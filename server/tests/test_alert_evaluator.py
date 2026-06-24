"""系统告警评估器守护测试（ALERT-01 评估 + ALERT-02 firing/resolved/去重）。

覆盖 Requirement: ALERT-01 / ALERT-02
威胁参考: T-74-02-01（去重防风暴）、T-74-02-02（单规则隔离不反噬）、
          T-74-02-05（趋势类 gauge:* 默认不参与）

要点：
- 快照类规则超阈 → firing 去重一条（severity/title_zh/rule_info.expr）+ notify_channels 调一次；
- 重复超阈不新建第二条（current_value/last_seen_at 更新），cooldown 内 notify 不再调；
- 恢复不再超阈 → resolved（ended_at/duration_s 非空）；
- 时序类 ttft 超阈 → firing；series 空 → current=None 跳过不建事件；
- 趋势类 gauge:* → _resolve_current_value 返回 None 不评估；
- 单规则异常隔离：某规则取值抛错被吞，其它规则正常评估；
- runapscheduler 两 job 接线 smoke + 失败不冒泡。
"""

from __future__ import annotations

from typing import Any

import pytest

from system.models import SystemAlertRule

# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


def _host_snapshot(cpu: float | None = None, mem: float | None = None) -> dict[str, Any]:
    """构造最小快照（仅 host 块，其余源缺省 unavailable）。"""
    return {
        "host": {"available": True, "cpu_percent": cpu, "mem_percent": mem},
        "db": {"available": False},
        "redis": {"available": False},
        "qdrant": {"available": False},
        "concurrency": {"available": False},
        "generated_at": "2026-06-24T00:00:00+00:00",
    }


def _patch_snapshot(monkeypatch: pytest.MonkeyPatch, snapshot: dict[str, Any]) -> None:
    from system import snapshot_service

    async def _fake() -> dict[str, Any]:
        return snapshot

    monkeypatch.setattr(snapshot_service, "collect_snapshot", _fake)


def _patch_snapshot_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from system import snapshot_service

    async def _boom() -> dict[str, Any]:
        raise RuntimeError("snapshot down")

    monkeypatch.setattr(snapshot_service, "collect_snapshot", _boom)


def _patch_timeseries(monkeypatch: pytest.MonkeyPatch, series: list[dict[str, Any]]) -> None:
    from system import metrics_query

    def _fake(**kwargs: Any) -> dict[str, Any]:
        return {"series": series}

    monkeypatch.setattr(metrics_query, "query_timeseries", _fake)


def _patch_notify(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """monkeypatch notify_channels，记录每次调用 (event, channels)。"""
    from system import alert_notifier

    calls: list[Any] = []

    async def _fake(event: Any, channels: list[str]) -> dict[str, str]:
        calls.append((event, channels))
        return {}

    monkeypatch.setattr(alert_notifier, "notify_channels", _fake)
    return calls


async def _mk_rule(**overrides: Any) -> SystemAlertRule:
    defaults: dict[str, Any] = dict(
        name="r", metric="cpu", op="gt", value=80.0, severity="P1", channels=["email"]
    )
    defaults.update(overrides)
    return await SystemAlertRule.objects.acreate(**defaults)


# ---------------------------------------------------------------------------
# Task 1：评估 + 去重 + 恢复 + 时序 + 趋势跳过 + 单规则隔离
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestEvaluateLifecycle:
    async def test_snapshot_breach_opens_single_firing_and_notifies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(a) cpu>80 且 cpu=95 → 1 条 firing（title/expr 含 current）+ notify 调一次。"""
        from system.alert_evaluator import evaluate_system_alerts
        from system.models import AlertEvent

        await _mk_rule(metric="cpu", op="gt", value=80.0, title_template="CPU 高：当前 {current}")
        _patch_snapshot(monkeypatch, _host_snapshot(cpu=95.0))
        notify_calls = _patch_notify(monkeypatch)

        result = await evaluate_system_alerts()

        assert result["firing"] == 1
        events = [e async for e in AlertEvent.objects.all()]
        assert len(events) == 1
        ev = events[0]
        assert ev.status == "firing"
        assert ev.severity == "P1"
        assert "95" in ev.title_zh
        assert "current 95.00" in ev.rule_info["expr"]
        assert ev.current_value == 95.0
        assert len(notify_calls) == 1

    async def test_repeat_breach_does_not_duplicate_or_renotify(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(b) 再跑一轮仍超阈 → 不新建第二条（仍 1 条，值更新），notify 不再调。"""
        from system.alert_evaluator import evaluate_system_alerts
        from system.models import AlertEvent

        await _mk_rule(metric="cpu", op="gt", value=80.0)
        _patch_snapshot(monkeypatch, _host_snapshot(cpu=95.0))
        notify_calls = _patch_notify(monkeypatch)

        await evaluate_system_alerts()
        # 第二轮仍 95（仍超阈）。
        _patch_snapshot(monkeypatch, _host_snapshot(cpu=90.0))
        result = await evaluate_system_alerts()

        assert result["firing"] == 0  # 无新 firing
        firing = [e async for e in AlertEvent.objects.filter(status="firing")]
        assert len(firing) == 1
        assert firing[0].current_value == 90.0  # 仅更新当前值
        assert firing[0].last_seen_at is not None
        assert len(notify_calls) == 1  # cooldown 内不重复通知（仅首轮调了一次）

    async def test_recovery_closes_firing_to_resolved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(c) 下一轮 cpu=10（不超阈）→ firing 转 resolved（ended_at/duration_s 非空）。"""
        from system.alert_evaluator import evaluate_system_alerts
        from system.models import AlertEvent

        await _mk_rule(metric="cpu", op="gt", value=80.0)
        _patch_notify(monkeypatch)

        _patch_snapshot(monkeypatch, _host_snapshot(cpu=95.0))
        await evaluate_system_alerts()
        _patch_snapshot(monkeypatch, _host_snapshot(cpu=10.0))
        result = await evaluate_system_alerts()

        assert result["resolved"] == 1
        assert await AlertEvent.objects.filter(status="firing").acount() == 0
        resolved = await AlertEvent.objects.filter(status="resolved").afirst()
        assert resolved is not None
        assert resolved.ended_at is not None
        assert resolved.duration_s is not None
        assert resolved.duration_s >= 0

    async def test_timeseries_ttft_breach_fires(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """(d-1) ttft 最近桶 value 超阈 → firing。"""
        from system.alert_evaluator import evaluate_system_alerts
        from system.models import AlertEvent

        await _mk_rule(metric="ttft", op="gt", value=1000.0, window=300)
        _patch_timeseries(
            monkeypatch,
            [
                {"bucket": "2026-06-24T00:00:00", "dim": "__all__", "value": 500.0},
                {"bucket": "2026-06-24T00:05:00", "dim": "__all__", "value": 2500.0},
            ],
        )
        _patch_notify(monkeypatch)

        result = await evaluate_system_alerts()

        assert result["firing"] == 1
        ev = await AlertEvent.objects.filter(status="firing").afirst()
        assert ev is not None
        assert ev.current_value == 2500.0

    async def test_timeseries_empty_series_skips(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """(d-2) series 空 → current=None 跳过，不建事件。"""
        from system.alert_evaluator import evaluate_system_alerts
        from system.models import AlertEvent

        await _mk_rule(metric="ttft", op="gt", value=1000.0)
        _patch_timeseries(monkeypatch, [])
        _patch_notify(monkeypatch)

        result = await evaluate_system_alerts()

        assert result["firing"] == 0
        assert await AlertEvent.objects.acount() == 0

    async def test_gauge_trend_metric_not_evaluated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(e) 趋势类 gauge:* → _resolve_current_value 返回 None，不建事件。"""
        from system.alert_evaluator import _resolve_current_value, evaluate_system_alerts
        from system.models import AlertEvent

        rule = await _mk_rule(metric="gauge:queue.durable_doing", op="gt", value=5.0)
        _patch_notify(monkeypatch)

        assert await _resolve_current_value(rule) is None
        result = await evaluate_system_alerts()
        assert result["firing"] == 0
        assert await AlertEvent.objects.acount() == 0

    async def test_single_rule_failure_isolated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """(f) 某规则 collect_snapshot 抛错 → 该规则跳过，其它规则正常评估（不冒泡）。"""
        from system.alert_evaluator import evaluate_system_alerts
        from system.models import AlertEvent

        # cpu 规则依赖 collect_snapshot（将抛错被吞 → 跳过）。
        await _mk_rule(metric="cpu", op="gt", value=80.0)
        # ttft 规则依赖 query_timeseries（正常返回超阈值 → fires）。
        await _mk_rule(metric="ttft", op="gt", value=1000.0)
        _patch_snapshot_raises(monkeypatch)
        _patch_timeseries(
            monkeypatch, [{"bucket": "b", "dim": "__all__", "value": 2500.0}]
        )
        _patch_notify(monkeypatch)

        # 不抛 + ttft 规则正常 fire。
        result = await evaluate_system_alerts()

        assert result["evaluated"] == 2
        assert result["firing"] == 1
        ev = await AlertEvent.objects.filter(status="firing").afirst()
        assert ev is not None
        assert ev.rule_info["metric"] == "ttft"


# ---------------------------------------------------------------------------
# Task 2：runapscheduler 两 job 接线 smoke + 失败不冒泡
# ---------------------------------------------------------------------------


class TestSchedulerJobWiring:
    def test_evaluate_job_invokes_evaluator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """(a) evaluate_system_alerts_job 经 run_async_task 调评估器一次，不抛。"""
        from agents.management.commands import runapscheduler
        from system import alert_evaluator

        called: dict[str, int] = {"n": 0}

        async def _stub() -> dict[str, int]:
            called["n"] += 1
            return {"evaluated": 0}

        monkeypatch.setattr(alert_evaluator, "evaluate_system_alerts", _stub)
        runapscheduler.evaluate_system_alerts_job()
        assert called["n"] == 1

    def test_evaluate_job_swallows_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """(b) 评估器抛错 → job wrapper 吞掉不冒泡（scheduler 主循环不被打断）。"""
        from agents.management.commands import runapscheduler
        from system import alert_evaluator

        async def _boom() -> dict[str, int]:
            raise RuntimeError("eval blew up")

        monkeypatch.setattr(alert_evaluator, "evaluate_system_alerts", _boom)
        # 不抛即通过。
        runapscheduler.evaluate_system_alerts_job()

    def test_purge_job_invokes_retention(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """(c) purge_alert_events_job 接线 + 失败不冒泡。"""
        from agents.management.commands import runapscheduler
        from system import alert_retention

        called: dict[str, int] = {"n": 0}

        async def _stub() -> dict[str, int]:
            called["n"] += 1
            return {"by_age": 0, "by_size": 0}

        monkeypatch.setattr(alert_retention, "purge_alert_events", _stub)
        runapscheduler.purge_alert_events_job()
        assert called["n"] == 1

        async def _boom() -> dict[str, int]:
            raise RuntimeError("purge blew up")

        monkeypatch.setattr(alert_retention, "purge_alert_events", _boom)
        runapscheduler.purge_alert_events_job()  # 不抛即通过

    def test_jobs_registered_in_source(self) -> None:
        """两个 job 的 add_job 注册块出现在 runapscheduler.py 源码。"""
        from pathlib import Path

        from agents.management.commands import runapscheduler

        src = Path(runapscheduler.__file__).read_text(encoding="utf-8")
        assert 'id="evaluate_system_alerts"' in src
        assert 'id="purge_alert_events"' in src
        assert "evaluate_system_alerts_job" in src
        assert "purge_alert_events_job" in src
