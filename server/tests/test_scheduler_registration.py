"""initial implementation contract 测试 — APScheduler 注册行为。

关键验证：
1. runapscheduler Command 模块定义了 cleanup_orchestration_checkpoints_job 函数
2. FF_ENABLE_SCHEDULER=False 时测试环境不起 BackgroundScheduler（autouse fixture 守护）
3. cleanup_orchestration_checkpoints job 源码中含 add_job 注册块
4. job wrapper 通过 call_command 调 cleanup_orchestration_checkpoints

对齐 VALIDATION.md L1049 `test_disabled_no_start` 命名锁。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from django.conf import settings


def test_disabled_no_start() -> None:
    """contract 测试环境默认 FF_ENABLE_SCHEDULER=False（conftest autouse 守护）。

    对应 security mitigation-03 Availability mitigation：
    pytest 进程必须不起 BackgroundScheduler 后台线程。
    """
    assert settings.FF_ENABLE_SCHEDULER is False, (
        "pytest 环境必须禁用 APScheduler（conftest._disable_scheduler_in_tests 应 autouse）"
    )


def test_cleanup_orchestration_checkpoints_job_defined() -> None:
    """contract runapscheduler 模块定义了 cleanup_orchestration_checkpoints_job 函数。"""
    from agents.management.commands import runapscheduler

    assert hasattr(runapscheduler, "cleanup_orchestration_checkpoints_job")
    job_fn = runapscheduler.cleanup_orchestration_checkpoints_job
    assert callable(job_fn)


def test_cleanup_orchestration_checkpoints_job_calls_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """contract job wrapper 通过 django call_command 调用 cleanup_orchestration_checkpoints。"""
    from agents.management.commands import runapscheduler

    called: dict[str, Any] = {"cmd": None}

    def _fake_call_command(name: str, *args: Any, **kwargs: Any) -> None:
        called["cmd"] = name

    # 函数内部 `from django.core.management import call_command` → 打源头
    monkeypatch.setattr(
        "django.core.management.call_command", _fake_call_command
    )

    runapscheduler.cleanup_orchestration_checkpoints_job()

    assert called["cmd"] == "cleanup_orchestration_checkpoints"


def test_add_job_registration_block_present() -> None:
    """contract runapscheduler.py 源码含 cleanup_orchestration_checkpoints 的 add_job 注册块。

    用源码 grep 替代启动真 scheduler（保持 pytest 零后台线程）。
    """
    path = (
        Path(__file__).parent.parent
        / "agents"
        / "management"
        / "commands"
        / "runapscheduler.py"
    )
    src = path.read_text(encoding="utf-8")

    assert 'id="cleanup_orchestration_checkpoints"' in src, (
        "未找到 id=\"cleanup_orchestration_checkpoints\" 的 add_job 注册块"
    )
    # 允许 3:00 或 3:30 等 minute 变体（Claude's Discretion）
    assert "CronTrigger(hour=3" in src, "CronTrigger hour=3 未找到"
    assert "cleanup_orchestration_checkpoints_job" in src, "job 函数名未在文件内引用"
