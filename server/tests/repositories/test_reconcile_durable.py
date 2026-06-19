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


# ---------------------------------------------------------------------------
# reconcile 级 Test 5-6：repositories._reset_stuck_indexing 接入判定
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_reset_stuck_indexing_keeps_running_when_durable_active(monkeypatch) -> None:
    """有在途 durable index job（helper True）→ 仓库保留 INDEXING、IndexHistory 保留 RUNNING。"""
    from django.utils import timezone

    import durable.reconcile as reconcile_mod
    from repositories.apps import RepositoriesConfig
    from repositories.models import (
        IndexHistory,
        IndexHistoryStatus,
        IndexStatus,
        Repository,
        TriggerType,
    )

    repo = Repository.objects.create(
        name="durable-active-repo",
        git_url="https://github.com/test/durable-active.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXING,
    )
    history = IndexHistory.objects.create(
        repository=repo,
        trigger_type=TriggerType.MANUAL,
        status=IndexHistoryStatus.RUNNING,
        started_at=timezone.now(),
    )

    monkeypatch.setattr(reconcile_mod, "has_active_durable_job_sync", lambda key: True)

    RepositoriesConfig._reset_stuck_indexing()

    repo.refresh_from_db()
    history.refresh_from_db()
    assert repo.index_status == IndexStatus.INDEXING
    assert history.status == IndexHistoryStatus.RUNNING


@pytest.mark.django_db(transaction=True)
def test_reset_stuck_indexing_marks_failed_when_no_durable(monkeypatch) -> None:
    """无在途 durable job（helper False）→ 仓库 / IndexHistory 标 FAILED（旧行为不留僵尸）。"""
    from django.utils import timezone

    import durable.reconcile as reconcile_mod
    from repositories.apps import RepositoriesConfig
    from repositories.models import (
        IndexHistory,
        IndexHistoryStatus,
        IndexStatus,
        Repository,
        TriggerType,
    )

    repo = Repository.objects.create(
        name="no-durable-repo",
        git_url="https://github.com/test/no-durable.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXING,
    )
    history = IndexHistory.objects.create(
        repository=repo,
        trigger_type=TriggerType.MANUAL,
        status=IndexHistoryStatus.RUNNING,
        started_at=timezone.now(),
    )

    monkeypatch.setattr(reconcile_mod, "has_active_durable_job_sync", lambda key: False)

    RepositoriesConfig._reset_stuck_indexing()

    repo.refresh_from_db()
    history.refresh_from_db()
    assert repo.index_status == IndexStatus.FAILED
    assert history.status == IndexHistoryStatus.FAILED
    assert history.finished_at is not None


# ---------------------------------------------------------------------------
# reconcile 级 Test 7-8：codegraph.reconcile_orphaned_graph_builds 接入判定
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_reconcile_graph_keeps_running_when_durable_active(monkeypatch) -> None:
    """有在途 durable graph job（helper True）→ orphan RUNNING 保留、仓库聚合态不归位。"""
    from django.utils import timezone

    import durable.reconcile as reconcile_mod
    from codegraph.apps import reconcile_orphaned_graph_builds
    from repositories.models import (
        GraphBuildHistory,
        GraphBuildHistoryStatus,
        GraphBuildHistoryTrigger,
        IndexStatus,
        Repository,
        RepositoryGraphStatus,
    )

    repo = Repository.objects.create(
        name="durable-graph-active",
        git_url="https://github.com/test/durable-graph.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
        graph_build_status=RepositoryGraphStatus.RUNNING,
    )
    stale = GraphBuildHistory.objects.create(
        repository=repo,
        trigger_type=GraphBuildHistoryTrigger.AUTO_AFTER_INDEX,
        status=GraphBuildHistoryStatus.RUNNING,
        started_at=timezone.now() - timezone.timedelta(minutes=120),
    )

    monkeypatch.setattr(reconcile_mod, "has_active_durable_job_sync", lambda key: True)

    reconciled = reconcile_orphaned_graph_builds(timeout_minutes=30)

    assert reconciled == 0
    stale.refresh_from_db()
    repo.refresh_from_db()
    assert stale.status == GraphBuildHistoryStatus.RUNNING
    assert repo.graph_build_status == RepositoryGraphStatus.RUNNING


@pytest.mark.django_db(transaction=True)
def test_reconcile_graph_marks_failed_when_no_durable(monkeypatch) -> None:
    """无在途 durable graph job（helper False）→ orphan RUNNING 回收 FAILED（旧行为）。"""
    from django.utils import timezone

    import durable.reconcile as reconcile_mod
    from codegraph.apps import reconcile_orphaned_graph_builds
    from repositories.models import (
        GraphBuildHistory,
        GraphBuildHistoryStatus,
        GraphBuildHistoryTrigger,
        IndexStatus,
        Repository,
        RepositoryGraphStatus,
    )

    repo = Repository.objects.create(
        name="no-durable-graph",
        git_url="https://github.com/test/no-durable-graph.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
        graph_build_status=RepositoryGraphStatus.RUNNING,
    )
    stale = GraphBuildHistory.objects.create(
        repository=repo,
        trigger_type=GraphBuildHistoryTrigger.AUTO_AFTER_INDEX,
        status=GraphBuildHistoryStatus.RUNNING,
        started_at=timezone.now() - timezone.timedelta(minutes=120),
    )

    monkeypatch.setattr(reconcile_mod, "has_active_durable_job_sync", lambda key: False)

    reconciled = reconcile_orphaned_graph_builds(timeout_minutes=30)

    assert reconciled == 1
    stale.refresh_from_db()
    repo.refresh_from_db()
    assert stale.status == GraphBuildHistoryStatus.FAILED
    assert repo.graph_build_status == RepositoryGraphStatus.FAILED
