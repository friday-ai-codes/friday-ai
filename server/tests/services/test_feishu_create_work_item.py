"""FeishuClient 写 API 单元测试（87-01 BOARD-01）。

覆盖看板拆分地基三方法（端点 / 请求体 [ASSUMED]，autonomous 路径 respx 全覆盖）：
- ``create_work_item``：err_code==0 + data.id → 返回 int；err_code!=0 → fail-loud 抛
  且异常文本不含明文 token；非 JSON → fail-loud；缺 id → 抛。
- ``add_work_item_relation``：err_code==0 → True；err_code!=0 → 抛（relation_type=1 关联）。
- ``detect_relation_capability``：命中父子 → parent_child=True；解析失败 / err_code 非 0 →
  保守降级（parent_child=False）且不抛（fail-soft）。

飞书响应经 respx mock（先 token 后写端点），pytest-socket 隔离不发真实网络，不依赖真实凭证。
"""

from __future__ import annotations

import httpx
import pytest
import respx

from services.feishu import FeishuClient
from services.feishu_parsing import FeishuResponseError

API_BASE = "https://project.feishu.cn"
PROJECT_KEY = "split-pk-001"
WORK_ITEM_TYPE = "story"
NEW_ID = 7700001
PARENT_ID = 9000001


def _client() -> FeishuClient:
    return FeishuClient(
        plugin_id="pid", plugin_secret="psecret", project_key=PROJECT_KEY, user_key="uk"
    )


def _mock_token() -> None:
    respx.post(f"{API_BASE}/open_api/authen/plugin_token").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {"token": "ptok-SECRET", "expire_time": 7200},
                "error": {"code": 0, "msg": "success"},
            },
        )
    )


# === create_work_item ===


@respx.mock
async def test_create_work_item_success_returns_id() -> None:
    _mock_token()
    route = respx.post(
        f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/{WORK_ITEM_TYPE}/create"
    ).mock(return_value=httpx.Response(200, json={"err_code": 0, "data": {"id": NEW_ID}}))

    new_id = await _client().create_work_item(
        PROJECT_KEY,
        WORK_ITEM_TYPE,
        "登录功能",
        description="用户可用账号密码登录",
    )

    assert new_id == NEW_ID
    # 请求体形状：name + field_value_pairs（description 落富文本）
    sent = route.calls.last.request
    import json as _json

    body = _json.loads(sent.content)
    assert body["name"] == "登录功能"
    assert any(p["field_key"] == "description" for p in body["field_value_pairs"])


@respx.mock
async def test_create_work_item_alt_id_field() -> None:
    """返回 id 字段名为 work_item_id（[ASSUMED] 备选）亦可解析。"""
    _mock_token()
    respx.post(
        f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/{WORK_ITEM_TYPE}/create"
    ).mock(
        return_value=httpx.Response(200, json={"err_code": 0, "data": {"work_item_id": NEW_ID}})
    )
    new_id = await _client().create_work_item(PROJECT_KEY, WORK_ITEM_TYPE, "X")
    assert new_id == NEW_ID


@respx.mock
async def test_create_work_item_err_code_raises_redacted() -> None:
    """err_code 非 0 → fail-loud 抛，且异常文本不含明文 token（脱敏断言）。"""
    _mock_token()
    respx.post(
        f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/{WORK_ITEM_TYPE}/create"
    ).mock(
        return_value=httpx.Response(
            200, json={"err_code": 1254000, "err_msg": "permission denied"}
        )
    )
    with pytest.raises(Exception) as exc_info:
        await _client().create_work_item(PROJECT_KEY, WORK_ITEM_TYPE, "X")
    assert "ptok-SECRET" not in str(exc_info.value)


@respx.mock
async def test_create_work_item_non_json_fail_loud() -> None:
    _mock_token()
    respx.post(
        f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/{WORK_ITEM_TYPE}/create"
    ).mock(
        return_value=httpx.Response(
            200, text="<html>502</html>", headers={"content-type": "text/html"}
        )
    )
    with pytest.raises(FeishuResponseError):
        await _client().create_work_item(PROJECT_KEY, WORK_ITEM_TYPE, "X")


@respx.mock
async def test_create_work_item_missing_id_raises() -> None:
    _mock_token()
    respx.post(
        f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/{WORK_ITEM_TYPE}/create"
    ).mock(return_value=httpx.Response(200, json={"err_code": 0, "data": {}}))
    with pytest.raises(Exception):
        await _client().create_work_item(PROJECT_KEY, WORK_ITEM_TYPE, "X")


# === add_work_item_relation ===


@respx.mock
async def test_add_relation_success() -> None:
    _mock_token()
    route = respx.post(
        f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/{WORK_ITEM_TYPE}/{NEW_ID}/relation"
    ).mock(return_value=httpx.Response(200, json={"err_code": 0}))

    ok = await _client().add_work_item_relation(
        PROJECT_KEY,
        WORK_ITEM_TYPE,
        NEW_ID,
        relation_type=1,
        target_id=PARENT_ID,
    )
    assert ok is True
    import json as _json

    body = _json.loads(route.calls.last.request.content)
    assert body["relation_type"] == 1
    assert body["target_id"] == PARENT_ID


@respx.mock
async def test_add_relation_err_code_raises() -> None:
    _mock_token()
    respx.post(
        f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/{WORK_ITEM_TYPE}/{NEW_ID}/relation"
    ).mock(
        return_value=httpx.Response(
            200, json={"err_code": 500, "err_msg": "relation type not configured"}
        )
    )
    with pytest.raises(Exception) as exc_info:
        await _client().add_work_item_relation(
            PROJECT_KEY, WORK_ITEM_TYPE, NEW_ID, relation_type=1, target_id=PARENT_ID
        )
    assert "ptok-SECRET" not in str(exc_info.value)


# === detect_relation_capability ===


@respx.mock
async def test_capability_hit_parent_child() -> None:
    _mock_token()
    respx.get(f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/{WORK_ITEM_TYPE}/meta").mock(
        return_value=httpx.Response(
            200,
            json={
                "err_code": 0,
                "data": {"relation_types": [{"type_key": "parent_child"}, "project_track"]},
            },
        )
    )
    cap = await _client().detect_relation_capability(PROJECT_KEY, WORK_ITEM_TYPE)
    assert cap["parent_child"] is True
    assert cap["project_track"] is True


@respx.mock
async def test_capability_err_code_degrades_no_raise() -> None:
    """err_code 非 0 → 保守降级 parent_child=False，绝不抛。"""
    _mock_token()
    respx.get(f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/{WORK_ITEM_TYPE}/meta").mock(
        return_value=httpx.Response(200, json={"err_code": 1254000, "err_msg": "denied"})
    )
    cap = await _client().detect_relation_capability(PROJECT_KEY, WORK_ITEM_TYPE)
    assert cap["parent_child"] is False
    assert cap["project_track"] is True


@respx.mock
async def test_capability_non_json_degrades_no_raise() -> None:
    """非 JSON 响应 → fail-soft 降级，不抛。"""
    _mock_token()
    respx.get(f"{API_BASE}/open_api/{PROJECT_KEY}/work_item/{WORK_ITEM_TYPE}/meta").mock(
        return_value=httpx.Response(
            200, text="<html>oops</html>", headers={"content-type": "text/html"}
        )
    )
    cap = await _client().detect_relation_capability(PROJECT_KEY, WORK_ITEM_TYPE)
    assert cap["parent_child"] is False
    assert cap["raw"] is None
