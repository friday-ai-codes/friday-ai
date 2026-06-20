"""index/graph/page_index durable 任务的双后端契约守护（Plan 61-01）。

锁定三类契约 / 陷阱：
- 双后端入参一致（研究 Pitfall 1）：in-process adapter 以 ``**payload`` 展开调任务体，
  与 procrastinate ``defer_async(**payload)`` 入参完全对齐，捕获 kwargs 键集合断言。
- page_index 占位 handler 幂等：重复执行恒等返回、零副作用（实际接入留 Phase 62）。
- has_active_by_key 两后端按 key 解析在途 job（BLOCKER：get+deterministic-key 误判 vs
  has_active_by_key 正确判定），为 Plan 03 reconcile 不误杀提供正确接口。

Test 1-3 + Test 5 默认 SQLite / in-process 路径跑；Test 4 / Test 6 带 postgres_queue
标记，默认套件经 addopts 排除（需真实 Postgres）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from durable.handlers import register_business_handlers
from durable.queues import QUEUE_GRAPH, QUEUE_INDEX
from durable.service import DurableTaskService
from services import background_runner

# ---------------------------------------------------------------------------
# Test 1-2：in-process 入参契约（adapter **payload 展开调任务体）
# ---------------------------------------------------------------------------


async def test_index_adapter_calls_task_with_expanded_kwargs(settings, monkeypatch) -> None:
    """durable_index：in-process adapter 以展开 kwargs 调 run_index，键集合精确匹配 payload。"""
    settings.DURABLE_TASK_BACKEND = "auto"  # SQLite 默认即 in-process，显式声明更稳
    register_business_handlers()

    captured = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr("durable.tasks_impl.run_index", captured)

    payload = {"repository_id": "R", "history_id": None, "branch": None, "trigger": "manual"}
    await DurableTaskService.defer(
        "durable_index", payload, queue=QUEUE_INDEX, idempotency_key="index:R"
    )
    background_runner.wait_for_pending(timeout=5.0)

    # 不抛 TypeError 且以 kwargs 调用：键集合 == payload 键（证明 **payload 展开一致）。
    captured.assert_awaited_once()
    assert captured.await_args.args == ()
    assert set(captured.await_args.kwargs) == {"repository_id", "history_id", "branch", "trigger"}


async def test_graph_adapter_calls_task_with_expanded_kwargs(settings, monkeypatch) -> None:
    """durable_graph：in-process adapter 以展开 kwargs 调 run_graph，同形断言。"""
    settings.DURABLE_TASK_BACKEND = "auto"
    register_business_handlers()

    captured = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr("durable.tasks_impl.run_graph", captured)

    payload = {"repository_id": "R", "history_id": None, "branch": None, "trigger": "manual"}
    await DurableTaskService.defer(
        "durable_graph", payload, queue=QUEUE_GRAPH, idempotency_key="graph:R"
    )
    background_runner.wait_for_pending(timeout=5.0)

    captured.assert_awaited_once()
    assert captured.await_args.args == ()
    assert set(captured.await_args.kwargs) == {"repository_id", "history_id", "branch", "trigger"}


# ---------------------------------------------------------------------------
# Test 3：page_index hash 未变重复执行幂等（恒等 skipped、不调 build_full）
# ---------------------------------------------------------------------------


async def test_page_index_idempotent_when_hash_unchanged(monkeypatch) -> None:
    """run_page_index：target_hash 命中当前 hash → 连续两次恒等 skipped，不调 build_full。"""
    from codegraph.services.corpus_tree import CorpusTreeService
    from durable.tasks_impl import run_page_index

    build_spy = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr(CorpusTreeService, "build_full", build_spy)
    monkeypatch.setattr(
        CorpusTreeService, "compute_source_hash", AsyncMock(return_value="H")
    )

    first = await run_page_index(target_id="page-1", target_hash="H")
    second = await run_page_index(target_id="page-1", target_hash="H")

    expected = {"status": "skipped", "reason": "hash_unchanged", "target_id": "page-1"}
    assert first == second == expected
    build_spy.assert_not_called()
    assert isinstance(first, dict)


# ---------------------------------------------------------------------------
# Test 4：@app.task 显式 name 一致性（postgres_queue）
# ---------------------------------------------------------------------------


@pytest.mark.postgres_queue
@pytest.mark.enable_socket
def test_app_tasks_registered_with_explicit_names(procrastinate_app) -> None:
    """procrastinate app.tasks 含三任务裸名键（验证 backends.defer 裸名查找可命中）。"""
    for name in ("durable_index", "durable_graph", "durable_page_index"):
        assert name in procrastinate_app.tasks


# ---------------------------------------------------------------------------
# Test 5：has_active_by_key in-process 路径（按 key 解析在途，不走数字 id get）
# ---------------------------------------------------------------------------


async def test_has_active_by_key_inprocess(settings) -> None:
    """in-process 门面按 key 读 _jobs 状态：pending/running 为 True，终态 / 未知为 False。"""
    settings.DURABLE_TASK_BACKEND = "auto"
    from durable import backends

    backends._set_job_state("k-running", status="running")
    assert await DurableTaskService.has_active_by_key("k-running") is True

    backends._set_job_state("k-done", status="succeeded")
    assert await DurableTaskService.has_active_by_key("k-done") is False

    # 未知 key（从未 defer 过）→ False，绝不抛、绝不走数字 id get。
    assert await DurableTaskService.has_active_by_key("k-missing") is False


# ---------------------------------------------------------------------------
# Test 6：has_active_by_key procrastinate 路径（postgres_queue）
# ---------------------------------------------------------------------------


@pytest.mark.postgres_queue
@pytest.mark.enable_socket
@pytest.mark.django_db(transaction=True)
async def test_has_active_by_key_procrastinate(procrastinate_app, durable_service) -> None:
    """procrastinate 门面按 queueing_lock 查在途为 True；并反证 get(deterministic key) 返 unknown。"""
    key = "index:repo-active"
    await durable_service.defer(
        "durable_ping",
        {"payload": {"k": "v"}},
        queue="maintenance",
        idempotency_key=key,
    )

    # 按 queueing_lock 查在途（todo）→ True；无对应 lock → False。
    assert await durable_service.has_active_by_key(key) is True
    assert await durable_service.has_active_by_key("index:repo-none") is False

    # 反证 BLOCKER：get 按 int(job_id) 查，传 deterministic key 恒返 unknown（误判根因）。
    state = await durable_service.get(key)
    assert state["status"] == "unknown"
