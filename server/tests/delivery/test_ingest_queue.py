"""爬取入库 durable 队列动作端点测试（Phase 62-01，CRAWL-01）。

覆盖（全端点 IsAuthenticated + DB 真相源 + durable defer/cancel 契约）：

- POST queue/（enqueue）→ 对 resolved 项建 IngestRun(QUEUED) 共享 batch_id +
  DurableTaskService.defer("durable_crawl_ingest", {batch_id,concurrency},
  queue=QUEUE_CRAWL_INGEST, idempotency_key="crawl_ingest:{batch_id}")，回写
  durable_job_id/idempotency_key，202。
- GET queue/（list）→ 从 IngestRun（DB）按 batch_id 分组重建队列列表（聚合
  status/progress/durable_job_id），不依赖内存——test_list_restores_from_db。
- POST queue/{batch_id}/stop/ → cancel(durable_job_id) + 非终态行 STOPPED；
  retry/start → 同 idempotency_key 重新 defer——test_stop / test_retry。
- detail / 非法 action / 不存在 batch / 未认证 边界。

DurableTaskService.defer/cancel 用 AsyncMock 桩捕获入参（patch 类属性，import 路径无关），
aresolve_items 桩返回受控 resolved 列表以聚焦队列契约（空间解析另有 test_json_ingest 守护），
DB 行真实落库。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken

from delivery.models import IngestRun
from durable import QUEUE_CRAWL_INGEST, DurableTaskService

pytestmark = pytest.mark.django_db(transaction=True)

BOARD_URL_1 = "https://project.feishu.cn/key123/story/detail/7010225564"
MR_URL_1 = "https://gitlab.com/test/repo/-/merge_requests/5"
BOARD_URL_2 = "https://project.feishu.cn/key123/story/detail/7010225565"
MR_URL_2 = "https://gitlab.com/test/repo/-/merge_requests/6"


async def _make_user_headers() -> dict[str, str]:
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    user = await user_model.objects.acreate_user(
        username="ingest_queue_api_user",
        password="ingest-pass-123",
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return {"authorization": f"Bearer {token.access_token}"}


@pytest.fixture
def stub_durable(monkeypatch: pytest.MonkeyPatch) -> dict:
    """桩 DurableTaskService.defer/cancel（AsyncMock，捕获入参）。"""
    defer = AsyncMock(return_value="job-xyz")
    cancel = AsyncMock(return_value=True)
    monkeypatch.setattr(DurableTaskService, "defer", defer)
    monkeypatch.setattr(DurableTaskService, "cancel", cancel)
    return {"defer": defer, "cancel": cancel}


def _stub_resolve(monkeypatch: pytest.MonkeyPatch, resolved: list[dict]) -> None:
    """桩 aresolve_items 返回受控 resolved 列表（聚焦队列契约，不触空间解析）。"""

    async def _fake(items: list[dict]) -> list[dict]:
        return resolved

    monkeypatch.setattr("delivery.services.json_ingest.aresolve_items", _fake)


def _resolved_item(board_url: str, mr_url: str, *, ok: bool = True, error: str = "") -> dict:
    return {
        "space": "key123",
        "space_id": "",
        "space_name": "空间 S",
        "feishu_project_key": "key123",
        "work_item_id": 7010225564,
        "work_item_type": "story",
        "mr_url": mr_url,
        "board_url": board_url if ok else "",
        "match_reason": "",
        "resolved": ok,
        "error": error,
    }


# ============================================================================
# enqueue（POST queue/）
# ============================================================================


async def test_enqueue_creates_queued_runs_and_defers(stub_durable, monkeypatch) -> None:
    """合法入队 → 建 QUEUED run + defer 契约 + 回写 durable_job_id/idempotency_key + 202。"""
    headers = await _make_user_headers()
    _stub_resolve(monkeypatch, [_resolved_item(BOARD_URL_1, MR_URL_1)])

    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/ingest/queue/",
        data={"items": [{"space": "key123", "work_item_id": 7010225564}]},
        content_type="application/json",
        headers=headers,
    )

    assert resp.status_code == 202, resp.content
    body = resp.json()
    batch_id = body["batch_id"]
    assert batch_id
    assert body["dispatched"] is True
    assert len(body["runs"]) == 1

    # defer 入参契约
    stub_durable["defer"].assert_awaited_once()
    args, kwargs = stub_durable["defer"].call_args
    assert args[0] == "durable_crawl_ingest"
    assert args[1] == {"batch_id": batch_id, "concurrency": 3}
    assert kwargs["queue"] == QUEUE_CRAWL_INGEST
    assert kwargs["idempotency_key"] == f"crawl_ingest:{batch_id}"

    # DB 行真实落库 + 回写
    runs = [r async for r in IngestRun.objects.filter(batch_id=batch_id)]
    assert len(runs) == 1
    run = runs[0]
    assert run.status == IngestRun.Status.QUEUED
    assert run.durable_job_id == "job-xyz"
    assert run.idempotency_key == f"crawl_ingest:{batch_id}"
    assert run.board_url == BOARD_URL_1


async def test_enqueue_skips_unresolved_no_dispatch(stub_durable, monkeypatch) -> None:
    """全部不可解析 → 不建行、不 defer、202 + skipped。"""
    headers = await _make_user_headers()
    _stub_resolve(
        monkeypatch, [_resolved_item(BOARD_URL_1, MR_URL_1, ok=False, error="未找到对应空间")]
    )

    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/ingest/queue/",
        data={"items": [{"space": "nope", "work_item_id": 1}]},
        content_type="application/json",
        headers=headers,
    )

    assert resp.status_code == 202, resp.content
    body = resp.json()
    assert body["dispatched"] is False
    assert body["runs"] == []
    assert len(body["skipped"]) == 1
    stub_durable["defer"].assert_not_awaited()
    assert await IngestRun.objects.acount() == 0


async def test_enqueue_unauthenticated_rejected() -> None:
    """未认证 enqueue → 401/403。"""
    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/ingest/queue/",
        data={"items": [{"space": "k", "work_item_id": 1}]},
        content_type="application/json",
    )
    assert resp.status_code in (401, 403)


# ============================================================================
# list（GET queue/）—— DB 真相源重建（CRAWL-01 断点恢复命门）
# ============================================================================


async def test_list_restores_from_db() -> None:
    """仅建 IngestRun 行（无内存态）→ list 按 batch_id 分组重建聚合队列项。"""
    headers = await _make_user_headers()
    batch_id = uuid.uuid4()
    key = f"crawl_ingest:{batch_id}"
    await IngestRun.objects.acreate(
        batch_id=batch_id,
        board_url=BOARD_URL_1,
        mr_url=MR_URL_1,
        status=IngestRun.Status.RUNNING,
        durable_job_id="job-1",
        idempotency_key=key,
    )
    await IngestRun.objects.acreate(
        batch_id=batch_id,
        board_url=BOARD_URL_2,
        mr_url=MR_URL_2,
        status=IngestRun.Status.COMPLETED,
    )

    client = AsyncClient()
    resp = await client.get("/api/delivery/ingest/queue/", headers=headers)

    assert resp.status_code == 200, resp.content
    items = resp.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["batch_id"] == str(batch_id)
    # 任一 RUNNING → 聚合 running
    assert item["status"] == "running"
    assert item["total"] == 2
    assert item["done"] == 1
    assert item["url_count"] == 2
    assert item["durable_job_id"] == "job-1"
    assert item["idempotency_key"] == key


async def test_list_unauthenticated_rejected() -> None:
    """未认证 list → 401/403。"""
    client = AsyncClient()
    resp = await client.get("/api/delivery/ingest/queue/")
    assert resp.status_code in (401, 403)


# ============================================================================
# detail（GET queue/{batch_id}/）
# ============================================================================


async def test_detail_returns_runs() -> None:
    """detail → 200 + 聚合 status + 各 run 明细；含 board/mr_url。"""
    headers = await _make_user_headers()
    batch_id = uuid.uuid4()
    await IngestRun.objects.acreate(
        batch_id=batch_id,
        board_url=BOARD_URL_1,
        mr_url=MR_URL_1,
        status=IngestRun.Status.QUEUED,
    )

    client = AsyncClient()
    resp = await client.get(
        f"/api/delivery/ingest/queue/{batch_id}/", headers=headers
    )

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["batch_id"] == str(batch_id)
    assert body["status"] == "queued"
    assert len(body["runs"]) == 1
    assert {"run_id", "board_url", "mr_url", "status", "steps"} <= set(body["runs"][0])


async def test_detail_missing_404() -> None:
    """不存在 batch → 404。"""
    headers = await _make_user_headers()
    client = AsyncClient()
    resp = await client.get(
        f"/api/delivery/ingest/queue/{uuid.uuid4()}/", headers=headers
    )
    assert resp.status_code == 404


# ============================================================================
# action（POST queue/{batch_id}/{action}/）—— stop=cancel+STOPPED / retry=同 key 重 defer
# ============================================================================


async def test_stop_cancels_and_marks_stopped(stub_durable) -> None:
    """stop → cancel(durable_job_id) + 非终态行 STOPPED。"""
    headers = await _make_user_headers()
    batch_id = uuid.uuid4()
    await IngestRun.objects.acreate(
        batch_id=batch_id,
        board_url=BOARD_URL_1,
        mr_url=MR_URL_1,
        status=IngestRun.Status.RUNNING,
        durable_job_id="job-9",
        idempotency_key=f"crawl_ingest:{batch_id}",
    )

    client = AsyncClient()
    resp = await client.post(
        f"/api/delivery/ingest/queue/{batch_id}/stop/",
        content_type="application/json",
        headers=headers,
    )

    assert resp.status_code == 200, resp.content
    stub_durable["cancel"].assert_awaited_once_with("job-9")
    run = await IngestRun.objects.aget(batch_id=batch_id)
    assert run.status == IngestRun.Status.STOPPED


async def test_retry_redefers_same_key(stub_durable) -> None:
    """retry → 同 idempotency_key 重新 defer，FAILED 行置回 QUEUED + 回写 durable_job_id。"""
    headers = await _make_user_headers()
    batch_id = uuid.uuid4()
    await IngestRun.objects.acreate(
        batch_id=batch_id,
        board_url=BOARD_URL_1,
        mr_url=MR_URL_1,
        status=IngestRun.Status.FAILED,
        idempotency_key=f"crawl_ingest:{batch_id}",
    )

    client = AsyncClient()
    resp = await client.post(
        f"/api/delivery/ingest/queue/{batch_id}/retry/",
        content_type="application/json",
        headers=headers,
    )

    assert resp.status_code == 200, resp.content
    stub_durable["defer"].assert_awaited_once()
    args, kwargs = stub_durable["defer"].call_args
    assert args[0] == "durable_crawl_ingest"
    assert kwargs["queue"] == QUEUE_CRAWL_INGEST
    assert kwargs["idempotency_key"] == f"crawl_ingest:{batch_id}"

    run = await IngestRun.objects.aget(batch_id=batch_id)
    assert run.status == IngestRun.Status.QUEUED
    assert run.durable_job_id == "job-xyz"


async def test_start_redefers(stub_durable) -> None:
    """start → 同 retry 语义重新 defer（同 key）。"""
    headers = await _make_user_headers()
    batch_id = uuid.uuid4()
    await IngestRun.objects.acreate(
        batch_id=batch_id,
        board_url=BOARD_URL_1,
        mr_url=MR_URL_1,
        status=IngestRun.Status.STOPPED,
        idempotency_key=f"crawl_ingest:{batch_id}",
    )

    client = AsyncClient()
    resp = await client.post(
        f"/api/delivery/ingest/queue/{batch_id}/start/",
        content_type="application/json",
        headers=headers,
    )

    assert resp.status_code == 200, resp.content
    stub_durable["defer"].assert_awaited_once()
    run = await IngestRun.objects.aget(batch_id=batch_id)
    assert run.status == IngestRun.Status.QUEUED


async def test_action_invalid_400(stub_durable) -> None:
    """非法 action → 400。"""
    headers = await _make_user_headers()
    batch_id = uuid.uuid4()
    await IngestRun.objects.acreate(
        batch_id=batch_id,
        board_url=BOARD_URL_1,
        mr_url=MR_URL_1,
        status=IngestRun.Status.QUEUED,
    )

    client = AsyncClient()
    resp = await client.post(
        f"/api/delivery/ingest/queue/{batch_id}/bogus/",
        content_type="application/json",
        headers=headers,
    )
    assert resp.status_code == 400
    stub_durable["defer"].assert_not_awaited()


async def test_action_missing_batch_404(stub_durable) -> None:
    """不存在 batch 的合法 action → 404。"""
    headers = await _make_user_headers()
    client = AsyncClient()
    resp = await client.post(
        f"/api/delivery/ingest/queue/{uuid.uuid4()}/stop/",
        content_type="application/json",
        headers=headers,
    )
    assert resp.status_code == 404


async def test_action_unauthenticated_rejected() -> None:
    """未认证 action → 401/403。"""
    batch_id = uuid.uuid4()
    await IngestRun.objects.acreate(
        batch_id=batch_id,
        board_url=BOARD_URL_1,
        mr_url=MR_URL_1,
        status=IngestRun.Status.QUEUED,
    )
    client = AsyncClient()
    resp = await client.post(
        f"/api/delivery/ingest/queue/{batch_id}/stop/",
        content_type="application/json",
    )
    assert resp.status_code in (401, 403)
