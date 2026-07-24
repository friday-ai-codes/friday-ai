"""run_crawl_ingest 双后端契约 + at-least-once 幂等守护（Phase 62-01，CRAWL-01）。

锁定三类契约：

- Test 1：重复执行 ``run_crawl_ingest(batch_id=...)`` 两次——按 DB 真相源驱动摄取，
  不在 IngestRun 之外另建行（at-least-once：重复执行允许重复 dispatch，幂等由被封装
  的 ``ingest_from_urls`` 内核承载，此处 stub 内核断言驱动契约）。
- Test 2：只处理该 batch 内非 COMPLETED 的 IngestRun 行；COMPLETED 行不再二次摄取
  （resume 安全）。
- Test 3：in-process 后端经 ``register_business_handlers`` 注册后，handler(payload) →
  ``run_crawl_ingest(**payload)`` 入参对齐不抛 TypeError（双后端契约，研究 Pitfall 1）。

Test 1-2 stub ``ingest_from_urls``（局部 import 自 orchestrator 模块属性，故 patch 模块
属性即生效）以聚焦 run_crawl_ingest 的 DB 驱动契约；真正的「无重复 WorkItem」由内核
三元组 unique upsert 承载（既有 ingest_orchestrator 范式，不在本任务体重复）。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from delivery.models import IngestRun
from durable.handlers import register_business_handlers
from durable.queues import QUEUE_CRAWL_INGEST
from durable.service import DurableTaskService
from services import background_runner

pytestmark = pytest.mark.django_db(transaction=True)

BOARD_URL_1 = "https://project.feishu.cn/key123/story/detail/1000000002"
MR_URL_1 = "https://gitlab.com/test/repo/-/merge_requests/5"
BOARD_URL_2 = "https://project.feishu.cn/key123/story/detail/1000000003"
MR_URL_2 = "https://gitlab.com/test/repo/-/merge_requests/6"


@pytest.fixture
def stub_ingest(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    """stub ``ingest_from_urls``（记录每次 dispatch 入参），不触真实摄取内核。"""
    calls: list[tuple[str, str, str]] = []

    async def _fake(run_id: str, board_url: str, mr_url: str) -> None:
        calls.append((run_id, board_url, mr_url))

    monkeypatch.setattr(
        "delivery.services.ingest_orchestrator.ingest_from_urls", _fake
    )
    return calls


async def test_duplicate_execution_drives_db_truth_source(stub_ingest) -> None:
    """重复执行两次：均按 DB 重建并 dispatch（at-least-once），不在 IngestRun 之外建行。"""
    from durable.tasks_impl import run_crawl_ingest

    batch_id = uuid.uuid4()
    run = await IngestRun.objects.acreate(
        batch_id=batch_id,
        board_url=BOARD_URL_1,
        mr_url=MR_URL_1,
        status=IngestRun.Status.QUEUED,
    )

    r1 = await run_crawl_ingest(batch_id=str(batch_id))
    r2 = await run_crawl_ingest(batch_id=str(batch_id))

    assert r1 == {"status": "ok", "batch_id": str(batch_id), "count": 1}
    assert r2["count"] == 1
    # at-least-once：两次执行均 dispatch 该行（幂等由内核 upsert 承载，非禁止重复执行）。
    assert len(stub_ingest) == 2
    assert all(c[0] == str(run.id) for c in stub_ingest)
    assert all(c[1:] == (BOARD_URL_1, MR_URL_1) for c in stub_ingest)
    # DB 真相源不被任务体复制：仍是单条行。
    assert await IngestRun.objects.filter(batch_id=batch_id).acount() == 1


async def test_completed_rows_skipped(stub_ingest) -> None:
    """COMPLETED 行不再二次摄取（resume 安全），仅非终态行被处理。"""
    from durable.tasks_impl import run_crawl_ingest

    batch_id = uuid.uuid4()
    done = await IngestRun.objects.acreate(
        batch_id=batch_id,
        board_url=BOARD_URL_1,
        mr_url=MR_URL_1,
        status=IngestRun.Status.COMPLETED,
    )
    queued = await IngestRun.objects.acreate(
        batch_id=batch_id,
        board_url=BOARD_URL_2,
        mr_url=MR_URL_2,
        status=IngestRun.Status.QUEUED,
    )

    result = await run_crawl_ingest(batch_id=str(batch_id))

    assert result["count"] == 1
    assert [c[0] for c in stub_ingest] == [str(queued.id)]
    # COMPLETED 行状态未被改写（既不重做、也不被 mark RUNNING）。
    refreshed = await IngestRun.objects.aget(id=done.id)
    assert refreshed.status == IngestRun.Status.COMPLETED


async def test_inprocess_adapter_param_alignment(settings, monkeypatch) -> None:
    """in-process adapter 以展开 kwargs 调 run_crawl_ingest，键集合精确匹配 payload，不抛。"""
    settings.DURABLE_TASK_BACKEND = "auto"  # SQLite 默认即 in-process，显式声明更稳
    register_business_handlers()

    captured = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr("durable.tasks_impl.run_crawl_ingest", captured)

    await DurableTaskService.defer(
        "durable_crawl_ingest",
        {"batch_id": "B", "concurrency": 3},
        queue=QUEUE_CRAWL_INGEST,
        idempotency_key="crawl_ingest:B",
    )
    background_runner.wait_for_pending(timeout=5.0)

    captured.assert_awaited_once()
    assert captured.await_args.args == ()
    assert set(captured.await_args.kwargs) == {"batch_id", "concurrency"}
