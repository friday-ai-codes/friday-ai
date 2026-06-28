"""BitableClient 守护测试（Phase 31-03 Task 3，REL-02）。

覆盖开放平台 token 复用 + bitable 端点形状 + token 缓存 + 凭证来源解耦：

- token 走开放平台：respx mock ``open.feishu.cn/.../tenant_access_token/internal`` →
  ``get_tenant_access_token`` 返回 token，且断言请求 host 为 ``open.feishu.cn``
  （**不是** ``project.feishu.cn`` plugin token）。
- list_records 端点形状：respx mock 开放平台 bitable records 端点 → 返回原始 data
  （含 items，未解析列结构）。
- token 缓存：二次取 token 不再打网络（call_count == 1）。
- 凭证来源独立：源码层守护 ``feishu_bitable.py`` 不取项目 plugin token 入口（REL-02）。

所有 HTTP 经 ``@respx.mock`` 拦截（先 mock token 端点再 mock 业务端点），pytest-socket
隔离下不发真实网络。
"""

from __future__ import annotations

import inspect
from pathlib import Path

import httpx
import respx

from services.feishu_bitable import BitableClient

OPEN_API_BASE = "https://open.feishu.cn/open-apis"
APP_TOKEN = "bascnAppTokenXYZ"
TABLE_ID = "tblTableId123"


def _mock_token() -> respx.Route:
    """mock 开放平台 tenant_access_token internal 端点（业务端点前置）。"""
    return respx.post(f"{OPEN_API_BASE}/auth/v3/tenant_access_token/internal").mock(
        return_value=httpx.Response(
            200,
            json={"code": 0, "tenant_access_token": "t", "expire": 7200},
        )
    )


@respx.mock
async def test_token_uses_open_platform_endpoint() -> None:
    """get_tenant_access_token 打到 open.feishu.cn internal 端点（非 project.feishu.cn）。"""
    route = _mock_token()
    client = BitableClient(app_id="app", app_secret="secret")

    token = await client.get_tenant_access_token()

    assert token == "t"
    assert route.called
    request = route.calls.last.request
    # 开放平台域守护：host 为 open.feishu.cn（非项目 plugin token 域）。
    assert request.url.host == "open.feishu.cn"
    assert request.url.path == "/open-apis/auth/v3/tenant_access_token/internal"


@respx.mock
async def test_list_records_endpoint_shape_returns_raw_data() -> None:
    """list_records 打到开放平台 bitable 端点，返回原始 data（含 items，未解析列）。"""
    _mock_token()
    items = [{"record_id": "rec1", "fields": {"status": "released"}}]
    route = respx.get(
        f"{OPEN_API_BASE}/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"items": items, "has_more": False, "page_token": ""},
            },
        )
    )
    client = BitableClient(app_id="app", app_secret="secret")

    data = await client.list_records(APP_TOKEN, TABLE_ID)

    assert route.called
    assert route.calls.last.request.url.host == "open.feishu.cn"
    # 原始 data 形状（含 items），骨架不解析列结构。
    assert data["items"] == items
    assert data["has_more"] is False


@respx.mock
async def test_list_records_passes_sort_param() -> None:
    """sort 入参以开放平台 JSON 字符串数组形态进 query（``["字段 DESC"]``）。"""
    _mock_token()
    route = respx.get(
        f"{OPEN_API_BASE}/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records"
    ).mock(
        return_value=httpx.Response(
            200, json={"code": 0, "data": {"items": [], "has_more": False}}
        )
    )
    client = BitableClient(app_id="app", app_secret="secret")

    await client.list_records(APP_TOKEN, TABLE_ID, sort=["上线日期 DESC"])

    assert route.called
    # httpx 解码后 query 携带 JSON 数组字符串（开放平台 sort 契约）。
    assert route.calls.last.request.url.params.get("sort") == '["上线日期 DESC"]'


@respx.mock
async def test_token_cached_single_network_call() -> None:
    """二次取 token 命中缓存，不再打网络（call_count == 1）。"""
    route = _mock_token()
    client = BitableClient(app_id="app", app_secret="secret")

    await client.get_tenant_access_token()
    await client.get_tenant_access_token()

    assert route.call_count == 1


@respx.mock
async def test_list_tables_passes_page_token() -> None:
    """list_tables 支持表分页游标，供大 Bitable 空间完整枚举。"""
    _mock_token()
    route = respx.get(f"{OPEN_API_BASE}/bitable/v1/apps/{APP_TOKEN}/tables").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [{"table_id": TABLE_ID}],
                    "has_more": False,
                    "page_token": "",
                },
            },
        )
    )
    client = BitableClient(app_id="app", app_secret="secret")

    data = await client.list_tables(APP_TOKEN, page_token="next-page")

    assert data["items"][0]["table_id"] == TABLE_ID
    assert route.calls.last.request.url.params.get("page_token") == "next-page"


def test_credential_source_decoupled_from_plugin_token() -> None:
    """源码守护：feishu_bitable 不取项目 plugin token 入口（REL-02 解耦核心）。"""
    src = Path(inspect.getfile(BitableClient)).read_text(encoding="utf-8")
    # 不 import / 调用 services.feishu 的 plugin client 入口。
    assert "create_feishu_client_for_project" not in src
    assert "from services.feishu import" not in src
    # 不取 plugin token 凭证。
    assert "plugin_token" not in src
