"""DurableTaskService 的 SQLite / in-process fallback 行为守护。

覆盖（DURABLE-01）：
- `_use_procrastinate` 纯函数真值表全分支
- `use_procrastinate_backend()` 在 SQLite 默认下回退 fallback；
  `backend=procrastinate` 而引擎非 postgresql 时记 warning 且 fail-soft（不 raise）
- `DurableTaskService.defer/get/cancel/retry_stalled` 在 fallback 下可用、
  不触达 Postgres（pytest-socket 不报 SocketBlockedError）
"""

from __future__ import annotations

from unittest import mock

import pytest

from durable.service import (
    DurableTaskService,
    _use_procrastinate,
    use_procrastinate_backend,
)
from services import background_runner

# ---------------------------------------------------------------------------
# _use_procrastinate 纯函数真值表（唯一权威判定）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("engine", "backend", "expected"),
    [
        ("django.db.backends.sqlite3", "auto", False),
        ("django.db.backends.postgresql", "auto", True),
        ("django.db.backends.postgresql", "procrastinate", True),
        ("django.db.backends.postgresql", "inprocess", False),
        ("django.db.backends.sqlite3", "procrastinate", False),
    ],
)
def test_use_procrastinate_truth_table(engine: str, backend: str, expected: bool) -> None:
    assert _use_procrastinate(engine, backend) is expected


def test_use_procrastinate_normalizes_inputs() -> None:
    # 大小写 / 空白归一，且空值安全（不抛）。
    assert _use_procrastinate("Django.DB.Backends.PostgreSQL", "  AUTO ") is True
    assert _use_procrastinate("", "auto") is False
    assert _use_procrastinate("postgresql", "") is True  # backend 空视作 auto


# ---------------------------------------------------------------------------
# use_procrastinate_backend()：读 settings 后委托判定
# ---------------------------------------------------------------------------


def test_use_procrastinate_backend_false_under_sqlite_default(settings) -> None:
    # 测试 DB 默认即 SQLite，DURABLE_TASK_BACKEND 默认 auto → fallback。
    settings.DURABLE_TASK_BACKEND = "auto"
    assert use_procrastinate_backend() is False


def test_use_procrastinate_backend_fail_soft_warns_on_non_postgres(settings) -> None:
    # 显式 procrastinate 但引擎非 postgresql：记 warning 且回退 False，绝不 raise。
    settings.DURABLE_TASK_BACKEND = "procrastinate"
    fake_logger = mock.MagicMock()
    with mock.patch("structlog.get_logger", return_value=fake_logger):
        result = use_procrastinate_backend()
    assert result is False
    fake_logger.warning.assert_called_once()
    assert fake_logger.warning.call_args.args[0] == "durable_backend_fallback_non_postgres"


# ---------------------------------------------------------------------------
# DurableTaskService 适配层（SQLite fallback 路径）
# ---------------------------------------------------------------------------


async def test_defer_returns_nonempty_job_id(settings) -> None:
    settings.DURABLE_TASK_BACKEND = "auto"
    job_id = await DurableTaskService.defer("durable.tests.noop", {"x": 1}, queue="maintenance")
    assert isinstance(job_id, str) and job_id
    background_runner.wait_for_pending(timeout=5.0)


async def test_defer_uses_idempotency_key_as_job_id(settings) -> None:
    settings.DURABLE_TASK_BACKEND = "auto"
    job_id = await DurableTaskService.defer(
        "durable.tests.noop",
        {"x": 1},
        queue="index",
        idempotency_key="index:repo-42",
    )
    assert job_id == "index:repo-42"
    background_runner.wait_for_pending(timeout=5.0)


async def test_get_returns_structured_status(settings) -> None:
    settings.DURABLE_TASK_BACKEND = "auto"
    job_id = await DurableTaskService.defer("durable.tests.noop", {"x": 1}, queue="maintenance")
    background_runner.wait_for_pending(timeout=5.0)
    state = await DurableTaskService.get(job_id)
    assert isinstance(state, dict)
    assert state["job_id"] == job_id
    assert state["status"] in {"pending", "running", "succeeded", "failed", "unknown"}


async def test_get_unknown_job_never_raises(settings) -> None:
    settings.DURABLE_TASK_BACKEND = "auto"
    state = await DurableTaskService.get("nonexistent-job-id")
    assert state == {"job_id": "nonexistent-job-id", "status": "unknown"}


async def test_cancel_returns_bool(settings) -> None:
    settings.DURABLE_TASK_BACKEND = "auto"
    result = await DurableTaskService.cancel("nonexistent-job-id")
    assert isinstance(result, bool)
    assert result is False  # 不存在 / 已完成 → 取消失败


async def test_retry_stalled_is_zero_noop(settings) -> None:
    settings.DURABLE_TASK_BACKEND = "auto"
    assert await DurableTaskService.retry_stalled() == 0
