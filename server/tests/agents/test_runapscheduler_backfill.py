"""``runapscheduler`` implementation / work item ½ —— APScheduler
DateTrigger 启动时一次性 backfill ChunkEdge 单测。

覆盖 must_haves 四条真相：

1. ``test_backfill_chunk_edges_job_calls_command`` —— scheduler 启动时自动调
   ``call_command('rebuild_chunk_edges', all=True)``（与
   ``cleanup_orchestration_checkpoints_job`` 同 ``call_command`` 模式）。
2. ``test_backfill_chunk_edges_job_exception_isolated`` —— 任务体内 ``call_command``
   异常被 ``log.exception`` 捕获 + swallow，不阻塞 scheduler 主流程（DjangoJobStore
   持久化 + 下次启动自动重试）。
3. ``test_scheduler_registers_backfill_job`` —— ``Command.handle()`` 启动后
   scheduler ``get_jobs()`` 含 ``id="backfill_chunk_edges"`` + ``trigger`` 为
   ``DateTrigger``；与 v23.0 IntervalTrigger ``poll_repository_updates`` 共存
   （新增 id 不冲突）。
4. ``test_backfill_date_trigger_runs_once`` —— ``DateTrigger(run_date=now())``
   首次 ``get_next_fire_time`` 返 datetime；第二次（``previous_fire_time``
   传入即视为已 fire）返 None ——单次 trigger 启动跑一次即结束，不会周期重复
   占用资源（per context contract Claude Discretion）。

测试隔离：MemoryJobStore 替换 DjangoJobStore（避免触碰
``django_apscheduler`` 表）+ ``BackgroundScheduler.start`` 注入 ``paused=True``
后立即抛 ``KeyboardInterrupt`` 让 ``handle()`` 走 except 分支干净退出
（不 spawn 真实后台线程跑 job）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
import structlog
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger


def test_backfill_chunk_edges_job_calls_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """job wrapper 调 ``call_command('rebuild_chunk_edges', all=True)`` 一次。"""
    from agents.management.commands.runapscheduler import backfill_chunk_edges_job

    mock_call = MagicMock()
    monkeypatch.setattr("django.core.management.call_command", mock_call)

    backfill_chunk_edges_job()

    mock_call.assert_called_once_with("rebuild_chunk_edges", all=True)


def test_backfill_chunk_edges_job_exception_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``call_command`` 抛异常 → wrapper 不向上传播 + 走 ``log.exception`` 路径。"""
    from agents.management.commands.runapscheduler import backfill_chunk_edges_job

    monkeypatch.setattr(
        "django.core.management.call_command",
        MagicMock(side_effect=RuntimeError("boom")),
    )

    with structlog.testing.capture_logs() as captured:
        backfill_chunk_edges_job()

    error_events = [
        e for e in captured if e.get("event") == "job_error" and e.get("log_level") == "error"
    ]
    assert error_events, f"未捕获 job_error 事件；captured={captured}"
    assert error_events[0].get("job") == "backfill_chunk_edges"
    assert "boom" in error_events[0].get("error", "")


def test_backfill_chunk_edges_job_command_error_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """work item 回归：``CommandError`` / ``ImproperlyConfigured`` re-raise 给 APScheduler。

    启动级错误（参数互斥 / settings 缺失等）需暴露到 ``DjangoJobExecution`` 让
    运维监控可见；单 repo 运行时失败保持 swallow + log 路径不动。
    """
    from django.core.management.base import CommandError

    from agents.management.commands.runapscheduler import backfill_chunk_edges_job

    monkeypatch.setattr(
        "django.core.management.call_command",
        MagicMock(side_effect=CommandError("--repo 与 --all 互斥")),
    )

    with structlog.testing.capture_logs() as captured:
        with pytest.raises(CommandError):
            backfill_chunk_edges_job()

    misconfigured_events = [
        e
        for e in captured
        if e.get("event") == "job_misconfigured" and e.get("log_level") == "error"
    ]
    assert misconfigured_events, f"CommandError 应走 job_misconfigured 路径；captured={captured}"


def test_backfill_chunk_edges_job_systemexit_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """work item + contract：命令 sys.exit(1) → wrapper 捕获 + log job_failed_exit_code，
    不打断 scheduler 主循环。"""
    from agents.management.commands.runapscheduler import backfill_chunk_edges_job

    monkeypatch.setattr(
        "django.core.management.call_command",
        MagicMock(side_effect=SystemExit(1)),
    )

    with structlog.testing.capture_logs() as captured:
        backfill_chunk_edges_job()

    failed_events = [
        e
        for e in captured
        if e.get("event") == "job_failed_exit_code" and e.get("log_level") == "error"
    ]
    assert failed_events, f"SystemExit(1) 应走 job_failed_exit_code 路径；captured={captured}"
    assert failed_events[0].get("exit_code") == 1


def test_scheduler_registers_backfill_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """``Command.handle()`` 启动后 ``backfill_chunk_edges`` 注册为 DateTrigger。"""
    from agents.management.commands import runapscheduler as mod

    monkeypatch.setattr(mod, "DjangoJobStore", MemoryJobStore)

    captured: dict[str, list[Any]] = {"jobs": []}
    real_start = BackgroundScheduler.start

    def stop_start(self: BackgroundScheduler, *args: Any, **kwargs: Any) -> None:
        real_start(self, paused=True)
        captured["jobs"] = list(self.get_jobs())
        raise KeyboardInterrupt()

    monkeypatch.setattr(BackgroundScheduler, "start", stop_start)

    cmd = mod.Command()
    cmd.handle()

    job_ids = [j.id for j in captured["jobs"]]
    assert "backfill_chunk_edges" in job_ids, (
        f"backfill_chunk_edges 未注册到 scheduler；现有 jobs={job_ids}"
    )
    backfill_job = next(j for j in captured["jobs"] if j.id == "backfill_chunk_edges")
    assert isinstance(backfill_job.trigger, DateTrigger), (
        f"trigger 非 DateTrigger: type={type(backfill_job.trigger).__name__}"
    )

    assert "poll_repository_updates" in job_ids, (
        "v23.0 IntervalTrigger poll_repository_updates 应与新增 DateTrigger 共存"
    )
    assert "cleanup_orchestration_checkpoints" in job_ids


def test_backfill_date_trigger_runs_once() -> None:
    """``DateTrigger(run_date=now())`` 单次语义：首次 fire 后不再触发。"""
    now = datetime.now()
    trigger = DateTrigger(run_date=now)

    first_fire = trigger.get_next_fire_time(None, now)
    assert first_fire is not None, "首次 get_next_fire_time 应返回 datetime"
    assert isinstance(first_fire, datetime)

    second_fire = trigger.get_next_fire_time(first_fire, datetime.now())
    assert second_fire is None, "DateTrigger 是单次 trigger；previous_fire_time 非 None 时应返 None"


def test_scheduler_single_instance_lock(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """contract 回归：第二份 scheduler 启动时 flock 拒绝。

    implementation REVIEW contract 指出多 scheduler 进程会从 DjangoJobStore 拉到同一个
    backfill job 并独立执行 → RAM 双倍 + context contract OOM 风险。修复后
    handle() 开头 fcntl.flock advisory lock，重复进程立即 SystemExit(1)。
    """
    import fcntl

    from agents.management.commands import runapscheduler as mod

    monkeypatch.setattr(mod, "DjangoJobStore", MemoryJobStore)
    monkeypatch.setattr(
        mod.settings,
        "APSCHEDULER_LOCK_PATH",
        str(tmp_path / "scheduler.lock"),
        raising=False,
    )

    # 模拟另一进程已占锁：在测试中先占住 lock。
    holder_fd = open(tmp_path / "scheduler.lock", "w")
    fcntl.flock(holder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    try:
        cmd = mod.Command()
        with pytest.raises(SystemExit) as exit_info:
            cmd.handle()
        assert exit_info.value.code == 1, "contract：lock 被占时 scheduler 应以 SystemExit(1) 退出"
    finally:
        fcntl.flock(holder_fd, fcntl.LOCK_UN)
        holder_fd.close()


def test_backfill_date_trigger_is_timezone_aware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """work item 回归：``backfill_chunk_edges`` job 的 DateTrigger.run_date 必须是
    timezone-aware datetime。

    implementation REVIEW work item 揭示裸 ``datetime.now()`` 是 naive，UTC 容器部署时
    APScheduler 按 scheduler tz (``Asia/Shanghai``) 解释 → 落到 8 小时前的
    时间点，misfire 窗口外被丢弃 → backfill 永不触发。修复后用
    ``django.utils.timezone.now()`` 返 aware datetime。
    """
    from agents.management.commands import runapscheduler as mod

    monkeypatch.setattr(mod, "DjangoJobStore", MemoryJobStore)

    captured: dict[str, list[Any]] = {"jobs": []}
    real_start = BackgroundScheduler.start

    def stop_start(self: BackgroundScheduler, *args: Any, **kwargs: Any) -> None:
        real_start(self, paused=True)
        captured["jobs"] = list(self.get_jobs())
        raise KeyboardInterrupt()

    monkeypatch.setattr(BackgroundScheduler, "start", stop_start)

    cmd = mod.Command()
    cmd.handle()

    backfill_job = next(j for j in captured["jobs"] if j.id == "backfill_chunk_edges")
    run_date = backfill_job.trigger.run_date
    assert run_date.tzinfo is not None, (
        f"DateTrigger.run_date 必须 timezone-aware；实际 tzinfo={run_date.tzinfo!r}"
    )
    assert backfill_job.misfire_grace_time == 3600, (
        "misfire_grace_time 应为 3600 秒兜底 scheduler 启动慢场景"
    )


def test_expire_pending_clarifications_job_calls_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """澄清超时出口 job wrapper 调 ``call_command('expire_pending_clarifications')`` 一次。"""
    from agents.management.commands.runapscheduler import (
        expire_pending_clarifications_job,
    )

    mock_call = MagicMock()
    monkeypatch.setattr("django.core.management.call_command", mock_call)

    expire_pending_clarifications_job()

    mock_call.assert_called_once_with("expire_pending_clarifications")


def test_expire_pending_clarifications_job_swallows_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """命令抛异常 → wrapper 吞掉记 job_error，scheduler 主循环不受影响（RELY-02）。"""
    from agents.management.commands.runapscheduler import (
        expire_pending_clarifications_job,
    )

    monkeypatch.setattr(
        "django.core.management.call_command",
        MagicMock(side_effect=RuntimeError("boom")),
    )

    with structlog.testing.capture_logs() as captured:
        expire_pending_clarifications_job()

    errors = [
        e for e in captured if e.get("event") == "job_error" and e.get("log_level") == "error"
    ]
    assert errors, f"未捕获 job_error 事件；captured={captured}"
    assert errors[0].get("job") == "expire_pending_clarifications"


def test_scheduler_registers_expire_pending_clarifications_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``expire_pending_clarifications`` 注册为 IntervalTrigger，间隔取配置，max_instances=1。"""
    from apscheduler.triggers.interval import IntervalTrigger
    from django.conf import settings

    from agents.management.commands import runapscheduler as mod

    monkeypatch.setattr(mod, "DjangoJobStore", MemoryJobStore)

    captured: dict[str, list[Any]] = {"jobs": []}
    real_start = BackgroundScheduler.start

    def stop_start(self: BackgroundScheduler, *args: Any, **kwargs: Any) -> None:
        real_start(self, paused=True)
        captured["jobs"] = list(self.get_jobs())
        raise KeyboardInterrupt()

    monkeypatch.setattr(BackgroundScheduler, "start", stop_start)

    cmd = mod.Command()
    cmd.handle()

    job_ids = [j.id for j in captured["jobs"]]
    assert "expire_pending_clarifications" in job_ids, (
        f"expire_pending_clarifications 未注册到 scheduler；现有 jobs={job_ids}"
    )
    job = next(j for j in captured["jobs"] if j.id == "expire_pending_clarifications")
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval.total_seconds() == float(
        settings.CLARIFICATION_EXPIRY_CHECK_INTERVAL_SECONDS
    )
    assert job.max_instances == 1
