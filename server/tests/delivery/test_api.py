"""delivery 最小 REST 端点测试（Phase 28-03 Task 1）。

覆盖手动 upsert（origin=manual）+ 读取 WorkItem（IsAuthenticated）：
- 认证用户 POST upsert（respx mock 回源）→ 200 + WorkItem 数据（含 sync_states 完整度）。
- 未认证 → 401/403。
- GET 读取已落库；不存在 → 404；非法 work_item_id → 400。

回源 upsert 经 sync_to_async 异步 ORM 写库（独立连接）→ 用 transaction=True。
所有回源经 respx mock，pytest-socket 隔离零真实网络。
"""

from __future__ import annotations

import httpx
import pytest
import respx
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken

pytestmark = pytest.mark.django_db(transaction=True)

# DOMAIN §16 实测自然键
PROJECT_KEY = "000000000000000000000001"
API_BASE = "https://project.feishu.cn"
STORY_ID = 1000000002
TARGET_PROJECT_ID = 1000000004

_STORY_FIELDS = [
    {
        "field_key": "field_000001",
        "field_name": "需求文档",
        "field_value": "https://tenant.feishu.cn/docx/doc_token_prd",
        "field_type_key": "link",
        "field_alias": "prd_url",
    },
    {
        "field_key": "field_000008",
        "field_name": "所属项目",
        "field_value": [TARGET_PROJECT_ID],
        "field_type_key": "work_item_related_multi_select",
        "field_alias": None,
    },
]


async def _make_user_headers() -> dict[str, str]:
    """创建测试用户 + JWT Bearer 头（async）。"""
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    user = await user_model.objects.acreate_user(
        username="delivery_api_user",
        password="delivery-pass-123",
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return {"authorization": f"Bearer {token.access_token}"}


async def _make_project():
    """创建带飞书插件凭证的 Space（供 create_feishu_client_for_project）。"""
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


def _mock_work_item(work_item_type: str = "story") -> None:
    item = {
        "id": STORY_ID,
        "name": "实现学习平台 A",
        "fields": _STORY_FIELDS,
        "work_item_status": {
            "state_key": "fi46o4r6m",
            "current_nodes": [{"id": "state_2", "name": "Sprint计划"}],
        },
    }
    respx.post(f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/{work_item_type}/query").mock(
        return_value=httpx.Response(200, json={"err_code": 0, "data": [item]})
    )


@respx.mock
async def test_upsert_authenticated_returns_work_item() -> None:
    """认证用户 POST upsert → 200 + WorkItem 数据（含 sync_states 完整度）。"""
    headers = await _make_user_headers()
    await _make_project()
    _mock_token()
    _mock_work_item()

    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/work-items/upsert/",
        data={
            "feishu_project_key": PROJECT_KEY,
            "work_item_type": "story",
            "work_item_id": STORY_ID,
        },
        content_type="application/json",
        headers=headers,
    )

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["work_item_id"] == STORY_ID
    assert body["work_item_type"] == "story"
    assert body["origin"] == "manual"
    assert body["title"] == "实现学习平台 A"
    # sync_states 完整度概要随读返回
    facets = {s["facet"]: s["status"] for s in body["sync_states"]}
    assert facets["basic_fields"] == "complete"


@respx.mock
async def test_upsert_unauthenticated_rejected() -> None:
    """未认证 POST upsert → 401/403（IsAuthenticated 守卫，T-28-08）。"""
    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/work-items/upsert/",
        data={
            "feishu_project_key": PROJECT_KEY,
            "work_item_type": "story",
            "work_item_id": STORY_ID,
        },
        content_type="application/json",
    )
    assert resp.status_code in (401, 403)


async def test_upsert_invalid_work_item_id_400() -> None:
    """非法 work_item_id（非正整数）→ 400。"""
    headers = await _make_user_headers()

    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/work-items/upsert/",
        data={
            "feishu_project_key": PROJECT_KEY,
            "work_item_type": "story",
            "work_item_id": 0,
        },
        content_type="application/json",
        headers=headers,
    )
    assert resp.status_code == 400


@respx.mock
async def test_get_reads_persisted_work_item() -> None:
    """GET 读取已落库 WorkItem → 200；读取路径不旁路 fetch（仅命中已落库行）。"""
    headers = await _make_user_headers()
    await _make_project()
    _mock_token()
    _mock_work_item()

    # 先经 upsert 落库
    from delivery.services import WorkItemIdentity, WorkItemService

    await WorkItemService().upsert(
        WorkItemIdentity(PROJECT_KEY, "story", STORY_ID), source="manual"
    )

    client = AsyncClient()
    resp = await client.get(
        "/api/delivery/work-items/",
        {
            "feishu_project_key": PROJECT_KEY,
            "work_item_type": "story",
            "work_item_id": STORY_ID,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["work_item_id"] == STORY_ID


async def test_get_missing_work_item_404() -> None:
    """读取不存在 WorkItem → 404。"""
    headers = await _make_user_headers()

    client = AsyncClient()
    resp = await client.get(
        "/api/delivery/work-items/",
        {
            "feishu_project_key": PROJECT_KEY,
            "work_item_type": "story",
            "work_item_id": 999999,
        },
        headers=headers,
    )
    assert resp.status_code == 404


async def test_get_invalid_work_item_id_400() -> None:
    """读取 work_item_id 非整数 → 400。"""
    headers = await _make_user_headers()

    client = AsyncClient()
    resp = await client.get(
        "/api/delivery/work-items/",
        {
            "feishu_project_key": PROJECT_KEY,
            "work_item_type": "story",
            "work_item_id": "abc",
        },
        headers=headers,
    )
    assert resp.status_code == 400
