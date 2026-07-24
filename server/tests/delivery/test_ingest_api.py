"""一键摄取 dispatch/status REST 端点测试（Phase 32-02 Task 2，ING-01）。

覆盖（IsAuthenticated 守卫 + UI-SPEC API 契约对齐）：

- POST /delivery/ingest/（合法 board_url+mr_url，已认证）→ 202 + {run_id, dispatched}，
  并建一条 IngestRun(running, steps 三项 pending)；run_in_background 以
  (run_id, board_url, mr_url) 派发 ingest_from_urls。
- 空 / 非 http(s) URL → 400，不建 run、不派发。
- GET /delivery/ingest/{run_id}/ → 200 + status/steps/started_at/completed_at；
  不存在 → 404。
- 未认证访问两端点 → 401/403。

run_in_background monkeypatch 为同步捕获（避免真实后台抖动），ingest_from_urls
monkeypatch 为 recorder 验证派发入参。respx 不触网络，pytest-socket 第二保险。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken

from delivery.models import IngestRun

pytestmark = pytest.mark.django_db(transaction=True)

BOARD_URL = "https://project.feishu.cn/key123/story/detail/1000000002"
MR_URL = "https://gitlab.com/test/repo/-/merge_requests/5"


async def _make_user_headers() -> dict[str, str]:
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    user = await user_model.objects.acreate_user(
        username="ingest_api_user",
        password="ingest-pass-123",
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return {"authorization": f"Bearer {token.access_token}"}


@pytest.fixture
def capture_dispatch(monkeypatch: pytest.MonkeyPatch):
    """monkeypatch run_in_background（同步捕获）+ ingest_from_urls（recorder）。"""
    state: dict = {}
    recorder = MagicMock(return_value="dispatched-coro")

    def _fake_run_in_background(factory, *, name=None):
        state["name"] = name
        # 触发 factory → 调用 recorder（被 patch 的 ingest_from_urls），记录入参
        state["result"] = factory()
        return MagicMock()

    monkeypatch.setattr("delivery.api.views.ingest_from_urls", recorder)
    monkeypatch.setattr("delivery.api.views.run_in_background", _fake_run_in_background)
    state["recorder"] = recorder
    return state


# ============================================================================
# dispatch（POST）
# ============================================================================


async def test_dispatch_returns_202_and_creates_run(capture_dispatch) -> None:
    """合法请求 → 202 + {run_id, dispatched}，建 running run（steps 三项 pending）。"""
    headers = await _make_user_headers()

    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/ingest/",
        data={"board_url": BOARD_URL, "mr_url": MR_URL},
        content_type="application/json",
        headers=headers,
    )

    assert resp.status_code == 202, resp.content
    body = resp.json()
    assert body["dispatched"] is True
    run_id = body["run_id"]
    assert run_id

    run = await IngestRun.objects.aget(id=run_id)
    assert run.status == IngestRun.Status.RUNNING
    assert run.board_url == BOARD_URL
    assert run.mr_url == MR_URL
    assert set(run.steps.keys()) == {"work_item", "document", "mr_diff"}
    assert all(step["status"] == "pending" for step in run.steps.values())

    # run_in_background 以 (run_id, board_url, mr_url) 派发 ingest_from_urls
    assert capture_dispatch["name"] == f"ingest:{run_id}"
    capture_dispatch["recorder"].assert_called_once_with(run_id, BOARD_URL, MR_URL)


async def test_dispatch_empty_url_400_no_run(capture_dispatch) -> None:
    """空 URL → 400，不建 run、不派发。"""
    headers = await _make_user_headers()

    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/ingest/",
        data={"board_url": "", "mr_url": MR_URL},
        content_type="application/json",
        headers=headers,
    )

    assert resp.status_code == 400
    assert await IngestRun.objects.acount() == 0
    capture_dispatch["recorder"].assert_not_called()


async def test_dispatch_non_http_url_400(capture_dispatch) -> None:
    """非 http(s) URL → 400 + 中文校验错误，不建 run。"""
    headers = await _make_user_headers()

    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/ingest/",
        data={"board_url": "ftp://x/board", "mr_url": MR_URL},
        content_type="application/json",
        headers=headers,
    )

    assert resp.status_code == 400
    assert "http" in str(resp.json()).lower()
    assert await IngestRun.objects.acount() == 0
    capture_dispatch["recorder"].assert_not_called()


async def test_dispatch_unauthenticated_rejected() -> None:
    """未认证 POST → 401/403（IsAuthenticated 守卫，T-32-03）。"""
    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/ingest/",
        data={"board_url": BOARD_URL, "mr_url": MR_URL},
        content_type="application/json",
    )
    assert resp.status_code in (401, 403)


# ============================================================================
# status（GET）
# ============================================================================


async def test_status_returns_run_steps() -> None:
    """GET 状态端点 → 200 + status/steps/started_at/completed_at（字段名对齐 UI-SPEC）。"""
    headers = await _make_user_headers()
    run = await IngestRun.objects.acreate(
        board_url=BOARD_URL, mr_url=MR_URL, status=IngestRun.Status.RUNNING
    )

    client = AsyncClient()
    resp = await client.get(f"/api/delivery/ingest/{run.id}/", headers=headers)

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["run_id"] == str(run.id)
    assert body["status"] == "running"
    assert set(body["steps"].keys()) == {"work_item", "document", "mr_diff"}
    assert "started_at" in body
    assert "completed_at" in body


async def test_status_missing_run_404() -> None:
    """不存在的 run_id → 404。"""
    headers = await _make_user_headers()
    import uuid

    client = AsyncClient()
    resp = await client.get(f"/api/delivery/ingest/{uuid.uuid4()}/", headers=headers)
    assert resp.status_code == 404


async def test_status_unauthenticated_rejected() -> None:
    """未认证 GET 状态端点 → 401/403。"""
    run = await IngestRun.objects.acreate(
        board_url=BOARD_URL, mr_url=MR_URL, status=IngestRun.Status.RUNNING
    )
    client = AsyncClient()
    resp = await client.get(f"/api/delivery/ingest/{run.id}/")
    assert resp.status_code in (401, 403)
