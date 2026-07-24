"""near-dup `feishu.client.FeishuClient` respx 单测（FIX-01/03/04）。

覆盖 Plan 27-03 全部 behavior，并与 Plan 27-02 的 canonical `services.feishu`
单测**结果一致**（同输入同输出），佐证两份 client 接入同一共享 helper、无解析漂移：
- FIX-01：`get_work_item` / `get_comments` 不传 `work_item_type` → `TypeError`（必填、
  fail-loud），传真实 type 按 type 取数（不再静默落 story）。
- FIX-04：`WorkItemInfo.feishu_fields` 完整对象数组（含 field_name/type/alias），旧
  `fields` 拍平 dict 向后兼容。
- FIX-03：`get_comments` 遇非 JSON → `[]` + warning（fail-soft），正常响应逐条解析。
- 硬取数路径（`get_work_item`）遇非 JSON → 抛 `FeishuResponseError`（fail-loud）。

本 client 无独立 relation 端点（无 `get_work_item_relations`），故不覆盖 FIX-02。

所有 HTTP 经 `@respx.mock` 拦截（先 mock token 端点再 mock 业务端点），pytest-socket
隔离下不发真实网络。fixture 字段形状取 DOMAIN-MODEL.md §16 实测值（issue 1000000006，
project_key 000000000000000000000001）。
"""

from __future__ import annotations

import httpx
import pytest
import respx

from feishu.client import FeishuClient, WorkItemInfo
from services.feishu_parsing import FeishuResponseError

API_BASE = "https://project.feishu.cn"
PROJECT_KEY = "000000000000000000000001"
WORK_ITEM_ID = 1000000006


# === DOMAIN §16 实测字段 fixture（与 services client 测试同源）===

ISSUE_RAW_FIELDS = [
    {
        "field_key": "field_000001",
        "field_name": "需求文档",
        "field_value": "https://tenant.feishu.cn/docx/doc_token_abc",
        "field_type_key": "link",
        "field_alias": "prd_url",
    },
    {
        "field_key": "field_000002",
        "field_name": "小组",
        "field_value": {"label": "示例组A", "value": "opt_1"},
        "field_type_key": "select",
        "field_alias": "example_platform_group",
    },
    {
        "field_key": "field_000008",
        "field_name": "所属项目",
        "field_value": [1000000004],
        "field_type_key": "work_item_related_multi_select",
        "field_alias": None,
    },
    {
        "field_key": "description",
        "field_name": "需求描述",
        "field_value": {
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "实现学习平台 A"}],
                }
            ]
        },
        "field_type_key": "rich_text",
        "field_alias": None,
    },
]


def _make_client() -> FeishuClient:
    """直接传凭证构造 client（绕过 DB 工厂）。"""
    return FeishuClient(
        plugin_id="plugin_test_id",
        plugin_secret="plugin_test_secret",
        project_key=PROJECT_KEY,
        user_key="user_key_test",
    )


def _mock_token() -> None:
    """mock plugin_token 端点（业务端点前置）。"""
    respx.post(f"{API_BASE}/open_api/authen/plugin_token").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {"token": "plugin_token_xyz", "expire_time": 7200},
                "error": {"code": 0, "msg": "success"},
            },
        )
    )


def _work_item_query_url(work_item_type: str) -> str:
    return f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/{work_item_type}/query"


def _comment_list_url(work_item_type: str) -> str:
    return (
        f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/{work_item_type}/{WORK_ITEM_ID}/comment/list"
    )


# === FIX-01：work_item_type 必填、fail-loud ===


@pytest.mark.asyncio
async def test_get_work_item_requires_work_item_type() -> None:
    """不传 work_item_type → TypeError（必填，PF-09，无静默 story）。"""
    client = _make_client()
    with pytest.raises(TypeError):
        await client.get_work_item(PROJECT_KEY, WORK_ITEM_ID)  # type: ignore[call-arg]


@pytest.mark.asyncio
@respx.mock
async def test_get_work_item_uses_real_type() -> None:
    """按传入的真实 type（issue）取数，work_item_type 不默认 story。"""
    _mock_token()
    respx.post(_work_item_query_url("issue")).mock(
        return_value=httpx.Response(
            200,
            json={
                "err_code": 0,
                "data": [{"id": WORK_ITEM_ID, "name": "示例需求", "fields": ISSUE_RAW_FIELDS}],
            },
        )
    )

    client = _make_client()
    info = await client.get_work_item(PROJECT_KEY, WORK_ITEM_ID, work_item_type="issue")

    assert isinstance(info, WorkItemInfo)
    assert info.work_item_type == "issue"


# === FIX-04：feishu_fields 完整对象保留 + fields 拍平向后兼容 ===


@pytest.mark.asyncio
@respx.mock
async def test_get_work_item_preserves_full_feishu_fields() -> None:
    """feishu_fields 为完整对象数组（含 field_name/type/alias）；fields 仍拍平 dict。

    断言与 services client 测试结果一致（同输入同输出），佐证无漂移。
    """
    _mock_token()
    respx.post(_work_item_query_url("issue")).mock(
        return_value=httpx.Response(
            200,
            json={
                "err_code": 0,
                "data": [
                    {
                        "id": WORK_ITEM_ID,
                        "name": "示例需求",
                        "fields": ISSUE_RAW_FIELDS,
                        "work_item_status": {"state_key": "in_progress"},
                    }
                ],
            },
        )
    )

    client = _make_client()
    info = await client.get_work_item(PROJECT_KEY, WORK_ITEM_ID, work_item_type="issue")

    # feishu_fields：完整对象保留元数据
    assert isinstance(info.feishu_fields, list)
    prd = next(f for f in info.feishu_fields if f["field_alias"] == "prd_url")
    assert prd["field_key"] == "field_000001"
    assert prd["field_name"] == "需求文档"
    assert prd["field_type_key"] == "link"

    # fields：向后兼容拍平 {field_key: field_value}
    assert info.fields["field_000001"] == "https://tenant.feishu.cn/docx/doc_token_abc"
    assert info.fields["field_000002"] == {"label": "示例组A", "value": "opt_1"}

    # status 仍取 work_item_status.state_key
    assert info.status == "in_progress"
    # 描述经富文本解析
    assert info.description == "实现学习平台 A"


# === 硬路径防御解析：非 JSON 抛 FeishuResponseError ===


@pytest.mark.asyncio
@respx.mock
async def test_get_work_item_non_json_raises() -> None:
    """硬取数路径遇非 JSON 响应 → 抛 FeishuResponseError（fail-loud）。"""
    _mock_token()
    respx.post(_work_item_query_url("issue")).mock(
        return_value=httpx.Response(
            200,
            text="<html>502 Bad Gateway</html>",
            headers={"content-type": "text/html"},
        )
    )

    client = _make_client()
    with pytest.raises(FeishuResponseError) as exc_info:
        await client.get_work_item(PROJECT_KEY, WORK_ITEM_ID, work_item_type="issue")

    # 异常消息不含凭证
    msg = str(exc_info.value)
    assert "plugin_token_xyz" not in msg
    assert "plugin_test_secret" not in msg


# === FIX-03：get_comments 防御解析 fail-soft + 正常解析 + type 必填 ===


@pytest.mark.asyncio
async def test_get_comments_requires_work_item_type() -> None:
    """get_comments 不传 work_item_type → TypeError（与 get_work_item 一致，FIX-01）。"""
    client = _make_client()
    with pytest.raises(TypeError):
        await client.get_comments(PROJECT_KEY, WORK_ITEM_ID)  # type: ignore[call-arg]


@pytest.mark.asyncio
@respx.mock
async def test_get_comments_non_json_returns_empty() -> None:
    """get_comments 遇非 JSON（Extra data）→ 返回 [] 且不抛（fail-soft，FIX-03）。"""
    _mock_token()
    respx.get(_comment_list_url("issue")).mock(
        return_value=httpx.Response(
            200,
            text="Extra data: line 1 column 5",
            headers={"content-type": "text/plain"},
        )
    )

    client = _make_client()
    result = await client.get_comments(PROJECT_KEY, WORK_ITEM_ID, work_item_type="issue")
    assert result == []


@pytest.mark.asyncio
@respx.mock
async def test_get_comments_parses_normal_response() -> None:
    """get_comments 正常响应逐条解析 id/content/created_at/author/thread_parent_id。

    与 services client 测试同输入同输出（含纯文本回复 + 富文本 + 线程父 id）。
    """
    _mock_token()
    respx.get(_comment_list_url("issue")).mock(
        return_value=httpx.Response(
            200,
            json={
                "err_code": 0,
                "data": {
                    "comments": [
                        {
                            "id": 1001,
                            "content": {
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "请尽快处理"}],
                                    }
                                ]
                            },
                            "created_at": 1700000000,
                            "author": {"name": "张三"},
                            "parent_id": "",
                        },
                        {
                            "id": 1002,
                            "content": "纯文本回复",
                            "created_at": 1700000100,
                            "author": {"name": "李四"},
                            "parent_id": 1001,
                        },
                    ]
                },
            },
        )
    )

    client = _make_client()
    comments = await client.get_comments(PROJECT_KEY, WORK_ITEM_ID, work_item_type="issue")

    assert len(comments) == 2
    assert comments[0]["id"] == 1001
    assert comments[0]["content"] == "请尽快处理"
    assert comments[0]["created_at"] == 1700000000
    assert comments[0]["author"] == "张三"
    assert comments[0]["thread_parent_id"] == ""
    assert comments[1]["content"] == "纯文本回复"
    assert comments[1]["thread_parent_id"] == 1001


# === WR-01：合法 JSON 但非 dict（[]/标量）也 fail-soft，绝不抛 AttributeError ===


@pytest.mark.asyncio
@respx.mock
async def test_get_comments_non_dict_json_returns_empty() -> None:
    """get_comments 遇合法 JSON 但为 list（[]）→ 返回 [] 且不抛（WR-01）。"""
    _mock_token()
    respx.get(_comment_list_url("issue")).mock(return_value=httpx.Response(200, json=[]))

    client = _make_client()
    result = await client.get_comments(PROJECT_KEY, WORK_ITEM_ID, work_item_type="issue")
    assert result == []


@pytest.mark.asyncio
@respx.mock
async def test_get_comments_scalar_json_returns_empty() -> None:
    """get_comments 遇合法 JSON 但为标量字符串 → 返回 [] 且不抛（WR-01）。"""
    _mock_token()
    respx.get(_comment_list_url("issue")).mock(return_value=httpx.Response(200, json="err"))

    client = _make_client()
    result = await client.get_comments(PROJECT_KEY, WORK_ITEM_ID, work_item_type="issue")
    assert result == []
