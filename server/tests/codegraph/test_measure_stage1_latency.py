"""measure_stage1_latency management command 测试（107-02 Task 1，O-6 查询管线）。

数据源是 `SystemLogEntry` 的 `repo_router_v2_stage1_completed` 事件 payload 里的
`duration_ms`——Stage 1 直调 `build_chat_model(...).ainvoke(...)`，不经
`record_model_usage` 的 chokepoint，故 `ModelUsageRecord` 里查不到该调用
（107-RESEARCH §9 VERIFIED）。

本地测试库是 SQLite（无 `percentile_cont`）→ 走命令的 Python 侧分位回退分支；
Postgres 侧 `percentile_cont` 分支在生产执行时才生效（口径与运维大盘一致，
LOGGING-SPEC §4.3）。分位数值本身只做**结构性验证**，生产分布见
`107-MEASUREMENTS.md`（deferred）。
"""

from __future__ import annotations

import io
import json
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from system.models import SystemLogEntry

STAGE1_EVENT = "repo_router_v2_stage1_completed"


def _mk_entry(
    *,
    payload: dict | None,
    event: str = STAGE1_EVENT,
    days_ago: float = 0.0,
) -> SystemLogEntry:
    return SystemLogEntry.objects.create(
        ts=timezone.now() - timedelta(days=days_ago),
        level="info",
        component="repo_router_v2",
        category="sampling",
        event=event,
        message=event,
        payload=payload if payload is not None else {},
    )


def _run(*args: str) -> str:
    out = io.StringIO()
    call_command("measure_stage1_latency", *args, stdout=out)
    return out.getvalue()


def _run_json(*args: str) -> dict:
    return json.loads(_run("--json", *args))


@pytest.mark.django_db
def test_quantiles_over_five_samples() -> None:
    """5 条 1000..5000ms → n=5 且 p50 落在 [2900, 3100]（SQLite 走 Python 分位）。"""
    for value in (1000, 2000, 3000, 4000, 5000):
        _mk_entry(payload={"duration_ms": value})

    report = _run_json("--days", "7")

    assert report["n"] == 5
    assert 2900 <= report["p50_ms"] <= 3100
    assert report["p90_ms"] >= report["p50_ms"]
    assert report["p99_ms"] >= report["p90_ms"]


@pytest.mark.django_db
def test_rows_outside_window_are_excluded() -> None:
    """时间窗过滤：早于 --days 窗口的行不计入 n。"""
    _mk_entry(payload={"duration_ms": 1000})
    _mk_entry(payload={"duration_ms": 9000}, days_ago=30)

    report = _run_json("--days", "7")

    assert report["n"] == 1
    assert report["window_days"] == 7


@pytest.mark.django_db
def test_other_events_are_excluded() -> None:
    """事件名过滤：非目标事件的行不计入 n。"""
    _mk_entry(payload={"duration_ms": 1000})
    _mk_entry(payload={"duration_ms": 8000}, event="other_event")

    report = _run_json()

    assert report["n"] == 1
    assert report["event"] == STAGE1_EVENT


@pytest.mark.django_db
def test_missing_or_non_numeric_duration_is_skipped() -> None:
    """payload 缺 duration_ms 或值非数值 → 跳过该行，不抛异常。"""
    _mk_entry(payload={"duration_ms": 1500})
    _mk_entry(payload={"candidate_count": 8})  # 缺键
    _mk_entry(payload={"duration_ms": None})
    _mk_entry(payload={"duration_ms": "unparsable"})
    _mk_entry(payload=None)  # 空 payload（JSONField default=dict）

    report = _run_json()

    assert report["n"] == 1
    assert report["p50_ms"] == pytest.approx(1500.0, abs=1.0)


@pytest.mark.django_db
def test_zero_samples_does_not_raise() -> None:
    """零样本：退出码 0（call_command 不抛）+ 人读输出含 n=0 与排查提示。"""
    output = _run("--days", "7")

    assert "n=0" in output
    assert "sampling" in output  # 提示语指向采样配置与组件日志级别

    report = _run_json("--days", "7")
    assert report["n"] == 0
    assert report["p50_ms"] is None
    assert report["p99_ms"] is None
    assert report["note"]


@pytest.mark.django_db
def test_json_mode_keys() -> None:
    """--json 输出单个可解析对象，键含 n / p50_ms / p90_ms / p99_ms / window_days / event / db_vendor。"""
    _mk_entry(payload={"duration_ms": 1234})

    report = _run_json()

    for key in ("n", "p50_ms", "p90_ms", "p99_ms", "window_days", "event", "db_vendor"):
        assert key in report, f"缺少输出键: {key}"
    assert isinstance(report, dict)


@pytest.mark.django_db
def test_output_contains_no_secret_material() -> None:
    """输出只含聚合量：payload 里的凭证样本串不得出现在 stdout（T-107-02）。"""
    _mk_entry(
        payload={
            "duration_ms": 2000,
            "model": "test-model",
            "error": "Bearer abcdef123456",
            "api_key": "sk-should-never-be-printed",
            "google_key": "AIzaSyDummyValue",
        }
    )

    for output in (_run(), _run("--json")):
        assert "sk-" not in output
        assert "Bearer " not in output
        assert "AIza" not in output
        assert "abcdef123456" not in output
