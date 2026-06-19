"""启动 reconcile 的 durable 在途判定守护（Plan 61-03，MIGRATE-02）。

锁定"标 RUNNING→FAILED 前先查 durable 接管"的语义，绝不误杀在途任务：

- helper 级（``durable.reconcile.has_active_durable_job_sync``）：
  - 真实 durable 路径（``postgres_queue``）：defer 落一个 queueing_lock=key 的真实
    job → helper 为 True；不存在的 key → False（**不 monkeypatch get**）。
  - durable 分支门面委托（SQLite，monkeypatch ``has_active_by_key``）：强制走 durable
    分支验证 helper 经 ``DurableTaskService.has_active_by_key`` 委托。
  - 非 durable 维持旧行为（默认 SQLite）：``use_procrastinate_backend()`` False →
    即便 in-process 有在跑 job，helper 恒 False（维持旧标 FAILED，不留僵尸）。
  - fail-safe：门面抛异常 → False。
- reconcile 级（repositories / codegraph 两处）：
  - 有在途 durable job（helper True）→ 仓库 / History 保留 RUNNING（不误杀）。
  - 无（helper False）→ 标 FAILED（不留僵尸），与改造前一致。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock

import pytest

from durable.reconcile import has_active_durable_job_sync


@pytest.fixture(autouse=True)
def _reset_durable_inprocess_jobs() -> Iterator[None]:
    """每测试后清空 in-process 后端的 job 状态注册表（与 durable conftest 同模式）。"""
    yield
    from durable import backends

    backends._reset_for_tests()


def _is_postgres() -> bool:
    from django.conf import settings

    return "postgresql" in str(settings.DATABASES["default"]["ENGINE"]).lower()


@pytest.fixture
def procrastinate_app() -> Any:
    """返回 ``procrastinate.contrib.django.app``（仅 postgres_queue 测试消费）。"""
    if not _is_postgres():
        pytest.skip(
            "postgres_queue 测试需真实 Postgres："
            "设 DATABASE_URL=postgres://... DURABLE_TASK_BACKEND=procrastinate"
        )
    from procrastinate.contrib.django import app

    return app


# ---------------------------------------------------------------------------
# helper 级 Test 1：真实 durable 路径（postgres_queue，按 queueing_lock 查在途）
# ---------------------------------------------------------------------------


@pytest.mark.postgres_queue
@pytest.mark.enable_socket
@pytest.mark.django_db(transaction=True)
def test_has_active_durable_job_sync_real_job(procrastinate_app) -> None:
    """defer 真实 queueing_lock=key 的 job → helper 同步入口为 True；未知 key → False。"""
    from asgiref.sync import async_to_sync

    from durable.queues import QUEUE_INDEX
    from durable.service import DurableTaskService

    key = "index:repo-active"
    async_to_sync(DurableTaskService.defer)(
        "durable_index",
        {"repository_id": "R", "history_id": None, "branch": None, "trigger": "manual"},
        queue=QUEUE_INDEX,
        idempotency_key=key,
    )

    assert has_active_durable_job_sync(key) is True
    assert has_active_durable_job_sync("index:repo-none") is False


# ---------------------------------------------------------------------------
# helper 级 Test 2：durable 分支经 has_active_by_key 门面委托（SQLite）
# ---------------------------------------------------------------------------


def test_has_active_durable_job_sync_delegates_to_facade(monkeypatch) -> None:
    """强制 durable 分支：helper 经 ``DurableTaskService.has_active_by_key`` 委托判定。"""
    from durable import service

    monkeypatch.setattr(service, "use_procrastinate_backend", lambda: True)
    facade = AsyncMock(return_value=True)
    monkeypatch.setattr(service.DurableTaskService, "has_active_by_key", facade)

    assert has_active_durable_job_sync("index:R") is True
    facade.assert_awaited_once_with("index:R")

    facade_false = AsyncMock(return_value=False)
    monkeypatch.setattr(service.DurableTaskService, "has_active_by_key", facade_false)
    assert has_active_durable_job_sync("index:R") is False


# ---------------------------------------------------------------------------
# helper 级 Test 3：非 durable（默认 SQLite）恒 False，维持旧标 FAILED
# ---------------------------------------------------------------------------


def test_has_active_durable_job_sync_non_durable_always_false(settings) -> None:
    """非 durable 后端：即便 in-process 有在跑 job，helper 恒 False（短路在门面之前）。"""
    settings.DURABLE_TASK_BACKEND = "auto"  # SQLite + auto → use_procrastinate False
    from durable import backends

    backends._set_job_state("index:R", status="running")
    # use_procrastinate_backend() False → 首句短路，绝不查 in-process _jobs。
    assert has_active_durable_job_sync("index:R") is False


# ---------------------------------------------------------------------------
# helper 级 Test 4：fail-safe —— 门面抛异常 → False
# ---------------------------------------------------------------------------


def test_has_active_durable_job_sync_fail_safe(monkeypatch) -> None:
    """durable 分支门面抛异常 → fail-safe 返回 False（绝不保留僵尸 RUNNING）。"""
    from durable import service

    monkeypatch.setattr(service, "use_procrastinate_backend", lambda: True)

    async def _boom(_key: str) -> bool:
        raise RuntimeError("facade boom")

    monkeypatch.setattr(service.DurableTaskService, "has_active_by_key", _boom)
    assert has_active_durable_job_sync("index:R") is False
