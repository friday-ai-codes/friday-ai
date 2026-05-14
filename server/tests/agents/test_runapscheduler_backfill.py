"""``runapscheduler`` Phase Plan / ½ —— APScheduler
DateTrigger 启动时一次性 backfill ChunkEdge 单测。
覆盖 must_haves 四条真相：
1. ``test_backfill_chunk_edges_job_calls_command`` —— scheduler 启动时自动调
 ``call_command('rebuild_chunk_edges', all=True)``（与
 ``cleanup_orchestration_checkpoints_job`` 同 ``call_command`` 模式）。
2. ``test_backfill_chunk_edges_job_exception_isolated`` —— 任务体内 ``call_command``
 异常被 ``log.exception`` 捕获 + swallow，不阻塞 scheduler 主流程（DjangoJobStore
 持久化 + 下次启动自动重试）。
3. ``test_scheduler_registers_backfill_job`` —— ``Command.handle`` 启动后
 scheduler ``get_jobs`` 含 ``id="backfill_chunk_edges"`` + ``trigger`` 为
 ``DateTrigger``；与 v23.0 IntervalTrigger ``poll_repository_updates`` 共存
 （新增 id 不冲突）。
4. ``test_backfill_date_trigger_runs_once`` —— ``DateTrigger(run_date=now)``
 首次 ``get_next_fire_time`` 返 datetime；第二次（``previous_fire_time``
 传入即视为已 fire）返 None ——单次 trigger 启动跑一次即结束，不会周期重复
 占用资源（per CONTEXT Claude Discretion）。
测试隔离：MemoryJobStore 替换 DjangoJobStore（避免触碰
``django_apscheduler`` 表）+ ``BackgroundScheduler.start`` 注入 ``paused=True``
后立即抛 ``KeyboardInterrupt`` 让 ``handle`` 走 except 分支干净退出
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
 mock_call = MagicMock
 monkeypatch.setattr("django.core.management.call_command", mock_call)
 backfill_chunk_edges_job
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
 with structlog.testing.capture_logs as captured:
 backfill_chunk_edges_job
 error_events = [
 e for e in captured if e.get("event") == "job_error" and e.get("log_level") == "error"
 ]
 assert error_events, f"未捕获 job_error 事件；captured={captured}"
 assert error_events[0].get("job") == "backfill_chunk_edges"
 assert "boom" in error_events[0].get("error", "")
def test_scheduler_registers_backfill_job(monkeypatch: pytest.MonkeyPatch) -> None:
 """``Command.handle`` 启动后 ``backfill_chunk_edges`` 注册为 DateTrigger。"""
 from agents.management.commands import runapscheduler as mod
 monkeypatch.setattr(mod, "DjangoJobStore", MemoryJobStore)
 captured: dict[str, list[Any]] = {"jobs": }
 real_start = BackgroundScheduler.start
 def stop_start(self: BackgroundScheduler, *args: Any, **kwargs: Any) -> None:
 real_start(self, paused=True)
 captured["jobs"] = list(self.get_jobs)
 raise KeyboardInterrupt
 monkeypatch.setattr(BackgroundScheduler, "start", stop_start)
 cmd = mod.Command
 cmd.handle
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
def test_backfill_date_trigger_runs_once -> None:
 """``DateTrigger(run_date=now)`` 单次语义：首次 fire 后不再触发。"""
 now = datetime.now
 trigger = DateTrigger(run_date=now)
 first_fire = trigger.get_next_fire_time(None, now)
 assert first_fire is not None, "首次 get_next_fire_time 应返回 datetime"
 assert isinstance(first_fire, datetime)
 second_fire = trigger.get_next_fire_time(first_fire, datetime.now)
 assert second_fire is None, (
 "DateTrigger 是单次 trigger；previous_fire_time 非 None 时应返 None"
 )
