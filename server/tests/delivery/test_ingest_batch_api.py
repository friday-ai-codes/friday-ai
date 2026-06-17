"""批量摄取 dispatch/status REST 端点测试（batch ingest）。

覆盖（IsAuthenticated 守卫 + 批量分组语义）：

- POST /delivery/ingest/batch/（合法 items 多组，已认证）→ 202 + {batch_id, runs[]}，
  每组建一条 IngestRun（共享同一 batch_id，running，steps 三项 pending）；
  run_in_background 对每组以 (run_id, board_url, mr_url) 派发 ingest_from_urls。
- 空 items / 任一组非 http(s) URL → 400，不建 run、不派发。
- GET /delivery/ingest/batch/{batch_id}/ → 200 + 聚合 status + 各 run（含 board/mr_url）；
  无该批 → 404。
- 未认证访问两端点 → 401/403。

run_in_background monkeypatch 为同步捕获，ingest_from_urls monkeypatch 为 recorder
验证每组派发入参。respx 不触网络，pytest-socket 第二保险。
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken

from delivery.models import IngestRun

pytestmark = pytest.mark.django_db(transaction=True)

BOARD_URL_1 = "https://project.feishu.cn/key123/story/detail/7010225564"
MR_URL_1 = "https://gitlab.com/test/repo/-/merge_requests/5"
BOARD_URL_2 = "https://project.feishu.cn/key123/story/detail/7010225565"
MR_URL_2 = "https://gitlab.com/test/repo/-/merge_requests/6"


async def _make_user_headers() -> dict[str, str]:
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    user = await user_model.objects.acreate_user(
        username="ingest_batch_api_user",
        password="ingest-pass-123",
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return {"authorization": f"Bearer {token.access_token}"}


@pytest.fixture
def capture_dispatch(monkeypatch: pytest.MonkeyPatch):
    """monkeypatch run_in_background（同步捕获）+ ingest_from_urls（recorder）。"""
    state: dict = {"names": []}
    recorder = MagicMock(return_value="dispatched-coro")

    def _fake_run_in_background(factory, *, name=None):
        state["names"].append(name)
        # 触发 factory → 调用 recorder（被 patch 的 ingest_from_urls），记录入参
        factory()
        return MagicMock()

    monkeypatch.setattr("delivery.api.views.ingest_from_urls", recorder)
    monkeypatch.setattr("delivery.api.views.run_in_background", _fake_run_in_background)
    state["recorder"] = recorder
    return state


# ============================================================================
# batch dispatch（POST）
# ============================================================================


async def test_batch_dispatch_returns_202_and_creates_runs(capture_dispatch) -> None:
    """合法多组 → 202 + {batch_id, runs[]}，建 N 条共享 batch_id 的 running run。"""
    headers = await _make_user_headers()

    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/ingest/batch/",
        data={
            "items": [
                {"board_url": BOARD_URL_1, "mr_url": MR_URL_1},
                {"board_url": BOARD_URL_2, "mr_url": MR_URL_2},
            ]
        },
        content_type="application/json",
        headers=headers,
    )

    assert resp.status_code == 202, resp.content
    body = resp.json()
    batch_id = body["batch_id"]
    assert batch_id
    assert len(body["runs"]) == 2
    assert {r["board_url"] for r in body["runs"]} == {BOARD_URL_1, BOARD_URL_2}

    runs = [run async for run in IngestRun.objects.filter(batch_id=batch_id)]
    assert len(runs) == 2
    for run in runs:
        assert run.status == IngestRun.Status.RUNNING
        assert str(run.batch_id) == batch_id
        assert all(step["status"] == "pending" for step in run.steps.values())

    # 每组 run_in_background 以 (run_id, board_url, mr_url) 派发 ingest_from_urls
    assert capture_dispatch["recorder"].call_count == 2
    dispatched = {
        (args[1], args[2]) for args, _ in capture_dispatch["recorder"].call_args_list
    }
    assert dispatched == {(BOARD_URL_1, MR_URL_1), (BOARD_URL_2, MR_URL_2)}


async def test_batch_dispatch_empty_items_400(capture_dispatch) -> None:
    """空 items → 400，不建 run、不派发。"""
    headers = await _make_user_headers()

    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/ingest/batch/",
        data={"items": []},
        content_type="application/json",
        headers=headers,
    )

    assert resp.status_code == 400
    assert await IngestRun.objects.acount() == 0
    capture_dispatch["recorder"].assert_not_called()


async def test_batch_dispatch_non_http_url_400(capture_dispatch) -> None:
    """任一组非 http(s) URL → 400，整批不建 run、不派发。"""
    headers = await _make_user_headers()

    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/ingest/batch/",
        data={
            "items": [
                {"board_url": BOARD_URL_1, "mr_url": MR_URL_1},
                {"board_url": "ftp://x/board", "mr_url": MR_URL_2},
            ]
        },
        content_type="application/json",
        headers=headers,
    )

    assert resp.status_code == 400
    assert "http" in str(resp.json()).lower()
    assert await IngestRun.objects.acount() == 0
    capture_dispatch["recorder"].assert_not_called()


async def test_batch_dispatch_unauthenticated_rejected() -> None:
    """未认证 POST → 401/403（IsAuthenticated 守卫）。"""
    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/ingest/batch/",
        data={"items": [{"board_url": BOARD_URL_1, "mr_url": MR_URL_1}]},
        content_type="application/json",
    )
    assert resp.status_code in (401, 403)


# ============================================================================
# batch status（GET）
# ============================================================================


async def test_batch_detail_returns_runs() -> None:
    """GET 批量状态端点 → 200 + 聚合 status + 各 run（含 board/mr_url）。"""
    headers = await _make_user_headers()
    batch_id = uuid.uuid4()
    await IngestRun.objects.acreate(
        batch_id=batch_id,
        board_url=BOARD_URL_1,
        mr_url=MR_URL_1,
        status=IngestRun.Status.COMPLETED,
    )
    await IngestRun.objects.acreate(
        batch_id=batch_id,
        board_url=BOARD_URL_2,
        mr_url=MR_URL_2,
        status=IngestRun.Status.RUNNING,
    )

    client = AsyncClient()
    resp = await client.get(f"/api/delivery/ingest/batch/{batch_id}/", headers=headers)

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["batch_id"] == str(batch_id)
    # 仍有 run running → 聚合 running
    assert body["status"] == "running"
    assert len(body["runs"]) == 2
    first = body["runs"][0]
    assert {"run_id", "board_url", "mr_url", "status", "steps"} <= set(first.keys())


async def test_batch_detail_all_terminal_completed() -> None:
    """全部 run 终态 → 聚合 completed。"""
    headers = await _make_user_headers()
    batch_id = uuid.uuid4()
    await IngestRun.objects.acreate(
        batch_id=batch_id,
        board_url=BOARD_URL_1,
        mr_url=MR_URL_1,
        status=IngestRun.Status.COMPLETED,
    )
    await IngestRun.objects.acreate(
        batch_id=batch_id,
        board_url=BOARD_URL_2,
        mr_url=MR_URL_2,
        status=IngestRun.Status.FAILED,
    )

    client = AsyncClient()
    resp = await client.get(f"/api/delivery/ingest/batch/{batch_id}/", headers=headers)

    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == "completed"


async def test_batch_detail_missing_404() -> None:
    """不存在的 batch_id → 404。"""
    headers = await _make_user_headers()
    client = AsyncClient()
    resp = await client.get(
        f"/api/delivery/ingest/batch/{uuid.uuid4()}/", headers=headers
    )
    assert resp.status_code == 404


async def test_batch_detail_unauthenticated_rejected() -> None:
    """未认证 GET 批量状态端点 → 401/403。"""
    batch_id = uuid.uuid4()
    await IngestRun.objects.acreate(
        batch_id=batch_id,
        board_url=BOARD_URL_1,
        mr_url=MR_URL_1,
        status=IngestRun.Status.RUNNING,
    )
    client = AsyncClient()
    resp = await client.get(f"/api/delivery/ingest/batch/{batch_id}/")
    assert resp.status_code in (401, 403)
