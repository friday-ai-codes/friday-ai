"""delivery 入口接线测试（Phase 28-03 Task 2）。

- 跨入口收敛（WIT-01）：manual 与 feishu_webhook 两入口对同一三元组 upsert →
  收敛唯一 canonical WorkItem。
- webhook handler 接线：飞书工作项事件 handler 在保留既有 knowledge ingestion 投递
  （INV-3）的同时，经 run_in_background 后台调 WorkItemService.upsert(source=
  "feishu_webhook")。
- 三元组不全（缺 work_item_type）→ 跳过 delivery upsert 投递，不抛。

回源经 respx mock；handler 接线测试用 SimpleNamespace project + mock，不触 DB / 网络。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

PROJECT_KEY = "000000000000000000000001"
API_BASE = "https://project.feishu.cn"
STORY_ID = 1000000002


# ============================================================================
# 跨入口收敛（WIT-01）—— 触 DB，需 transaction=True
# ============================================================================


async def _make_project():
    from common.encryption import encrypt_value
    from projects.models import Space

    return await Space.objects.acreate(
        name="example_platform",
        feishu_project_key=PROJECT_KEY,
        feishu_plugin_id="plugin_test_id",
        feishu_plugin_secret_encrypted=encrypt_value("plugin_test_secret"),
        feishu_user_key="user_key_test",
    )


def _mock_token() -> None:
    respx.post(f"{API_BASE}/open_api/authen/plugin_token").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {"token": "plugin_token_xyz", "expire_time": 7200},
                "error": {"code": 0, "msg": "success"},
            },
        )
    )


def _mock_work_item() -> None:
    item = {
        "id": STORY_ID,
        "name": "实现学习平台 A",
        "fields": [],
        "work_item_status": {"state_key": "fi46o4r6m"},
    }
    respx.post(f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/story/query").mock(
        return_value=httpx.Response(200, json={"err_code": 0, "data": [item]})
    )


@pytest.mark.django_db(transaction=True)
@respx.mock
async def test_cross_entry_convergence_manual_and_webhook() -> None:
    """WIT-01：manual 与 feishu_webhook 两入口同三元组 upsert → 唯一 WorkItem。"""
    from delivery.models import WorkItem
    from delivery.services import WorkItemIdentity, WorkItemService

    await _make_project()
    _mock_token()
    _mock_work_item()

    identity = WorkItemIdentity(PROJECT_KEY, "story", STORY_ID)
    service = WorkItemService()
    wi_manual = await service.upsert(identity, source="manual")
    wi_webhook = await service.upsert(identity, source="feishu_webhook")

    assert wi_manual.id == wi_webhook.id  # 收敛同一 canonical
    assert await WorkItem.objects.acount() == 1
    converged = await WorkItem.objects.aget(work_item_id=STORY_ID)
    assert converged.origin == "manual"  # origin 仅首次落，不被后续覆盖


# ============================================================================
# webhook handler 接线（不触 DB / 网络）
# ============================================================================


def _make_view():
    from feishu.views import FeishuWebhookView

    return FeishuWebhookView()


async def test_create_handler_wires_delivery_upsert_and_keeps_ingestion() -> None:
    """create handler：保留 knowledge ingestion（INV-3）+ 后台调 upsert(source=feishu_webhook)。"""
    from delivery.services import WorkItemService

    view = _make_view()
    view._fetch_and_update_work_item = AsyncMock(return_value=None)
    project = SimpleNamespace(feishu_project_key=PROJECT_KEY)
    payload = {"id": STORY_ID, "work_item_type_key": "story"}

    captured: dict = {}

    def _fake_rib(factory, *, name=None, initiated_by_user_id=None):
        captured["factory"] = factory
        captured["name"] = name
        captured["initiated_by_user_id"] = initiated_by_user_id
        return MagicMock()

    with (
        patch("knowledge.ingestion.aschedule_ingestion", new=AsyncMock()) as mock_ingest,
        patch("services.background_runner.run_in_background", new=_fake_rib),
    ):
        await view._handle_workitem_create(project, payload, MagicMock())

    # INV-3：既有 knowledge 投影投递仍在
    mock_ingest.assert_awaited_once()
    # delivery 后台 upsert 已投递
    assert "factory" in captured
    # CTX-02：webhook 无真实触发用户，后台任务必须显式归因到 system
    assert captured["initiated_by_user_id"] == "system"

    # 执行后台 factory，断言以 source="feishu_webhook" 调 upsert
    with patch.object(WorkItemService, "upsert", new=AsyncMock(return_value=None)) as mock_upsert:
        await captured["factory"]()
    mock_upsert.assert_awaited_once()
    identity_arg = mock_upsert.await_args.args[0]
    assert identity_arg.feishu_project_key == PROJECT_KEY
    assert identity_arg.work_item_type == "story"
    assert identity_arg.work_item_id == STORY_ID
    assert mock_upsert.await_args.kwargs["source"] == "feishu_webhook"


def test_schedule_delivery_upsert_skips_incomplete_identity() -> None:
    """三元组不全（缺 work_item_type）→ 跳过 delivery upsert 投递，不抛、不调度。"""
    view = _make_view()
    project = SimpleNamespace(feishu_project_key=PROJECT_KEY)

    with patch("services.background_runner.run_in_background") as mock_rib:
        view._schedule_delivery_upsert(project, STORY_ID, "")  # 缺 work_item_type
        view._schedule_delivery_upsert(project, None, "story")  # 缺 work_item_id

    mock_rib.assert_not_called()
