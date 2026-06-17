"""CardKit v1 原生流式封装 httpx 形状单测（Phase 58 Wave 1）。

覆盖 `FeishuIMClient` 4 个 CardKit 方法的端点 / payload / sequence 严格递增 /
uuid 幂等 / 全量 content / code!=0 → FeishuIMError：
- create_card_entity → POST /cardkit/v1/cards（type=card_json + 转义 2.0 JSON）
- send_card_entity → 复用 send_message（interactive + card_id）
- stream_card_content → PUT .../elements/{element_id}/content（全量文本 + sequence）
- settle_card_stream → PATCH .../settings（streaming_mode=false）

所有 HTTP 经 `@respx.mock` 拦截；token 缓存预置，避免真实鉴权请求与 token 端点 mock。
N-3：create_card_entity 的 schema 2.0 断言内联 2.0 dict，不依赖 Task 2 的
build_streaming_card_v2 产物，保证 Task 顺序可独立跑绿。
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from services.feishu_im import FeishuIMClient, FeishuIMError

OPEN_API_BASE = "https://open.feishu.cn/open-apis"


def _make_client() -> FeishuIMClient:
    """构造 client 并预置 token 缓存（避免真实鉴权请求）。"""
    client = FeishuIMClient(app_id="cli_x", app_secret="x")
    client._tenant_token = "fake_token"
    client._token_expires_at = time.time() + 3600
    return client


def _inline_streaming_card_2_0() -> dict[str, object]:
    """内联 schema 2.0 流式卡 dict（N-3：不依赖 Task 2 产物）。"""
    return {
        "schema": "2.0",
        "config": {
            "streaming_mode": True,
            "update_multi": True,
            "streaming_config": {
                "print_frequency_ms": {"default": 70},
                "print_step": {"default": 1},
                "print_strategy": "fast",
            },
        },
        "header": {"title": {"tag": "plain_text", "content": "Friday"}, "template": "blue"},
        "body": {
            "elements": [{"tag": "markdown", "content": "思考中...", "element_id": "md_body"}]
        },
    }


# === create_card_entity ===


@pytest.mark.asyncio
@respx.mock
async def test_create_card_entity_posts_escaped_2_0_json() -> None:
    """POST /cardkit/v1/cards：type=card_json + data 为可还原的 2.0 JSON 串，返回 card_id。"""
    route = respx.post(f"{OPEN_API_BASE}/cardkit/v1/cards").mock(
        return_value=httpx.Response(200, json={"code": 0, "data": {"card_id": "c_1"}})
    )
    client = _make_client()

    card_id = await client.create_card_entity(_inline_streaming_card_2_0())

    assert card_id == "c_1"
    body = json.loads(route.calls.last.request.content)
    assert body["type"] == "card_json"
    restored = json.loads(body["data"])
    assert restored["schema"] == "2.0"
    assert restored["config"]["streaming_mode"] is True
    assert restored["body"]["elements"][0]["element_id"] == "md_body"
    assert "uuid" not in body


@pytest.mark.asyncio
@respx.mock
async def test_create_card_entity_raises_on_permission_error() -> None:
    """code!=0（99991672 权限错）→ FeishuIMError，携带 code。"""
    respx.post(f"{OPEN_API_BASE}/cardkit/v1/cards").mock(
        return_value=httpx.Response(
            400, json={"code": 99991672, "msg": "no permission"}
        )
    )
    client = _make_client()

    with pytest.raises(FeishuIMError) as exc_info:
        await client.create_card_entity(_inline_streaming_card_2_0())
    assert exc_info.value.code == 99991672


@pytest.mark.asyncio
@respx.mock
async def test_create_card_entity_includes_uuid_when_provided() -> None:
    """uuid 非空 → body 含 uuid。"""
    route = respx.post(f"{OPEN_API_BASE}/cardkit/v1/cards").mock(
        return_value=httpx.Response(200, json={"code": 0, "data": {"card_id": "c_1"}})
    )
    client = _make_client()

    await client.create_card_entity(_inline_streaming_card_2_0(), uuid="abc")

    body = json.loads(route.calls.last.request.content)
    assert body["uuid"] == "abc"


# === send_card_entity ===


@pytest.mark.asyncio
async def test_send_card_entity_reuses_send_message_interactive() -> None:
    """复用 send_message：msg_type=interactive + content={type:card,data:{card_id}}。"""
    client = _make_client()

    with patch.object(
        client, "send_message", new=AsyncMock(return_value={"message_id": "om_1"})
    ) as mock_send:
        message_id = await client.send_card_entity(
            receive_id="oc_1", receive_id_type="chat_id", card_id="c_1"
        )

    assert message_id == "om_1"
    mock_send.assert_awaited_once_with(
        receive_id="oc_1",
        receive_id_type="chat_id",
        msg_type="interactive",
        content={"type": "card", "data": {"card_id": "c_1"}},
    )


# === stream_card_content ===


@pytest.mark.asyncio
@respx.mock
async def test_stream_card_content_puts_full_content_with_sequence() -> None:
    """PUT .../elements/{id}/content：body 含全量 content + sequence。"""
    route = respx.put(
        f"{OPEN_API_BASE}/cardkit/v1/cards/c_1/elements/md_body/content"
    ).mock(return_value=httpx.Response(200, json={"code": 0, "data": {}}))
    client = _make_client()

    ok = await client.stream_card_content("c_1", "md_body", "你好", 1)

    assert ok is True
    body = json.loads(route.calls.last.request.content)
    assert body == {"content": "你好", "sequence": 1}


@pytest.mark.asyncio
@respx.mock
async def test_stream_card_content_sequence_strictly_increasing_full_text() -> None:
    """同一卡多次推送：sequence 严格递增、content 为传入全量（P-2/P-4 形状契约）。"""
    route = respx.put(
        f"{OPEN_API_BASE}/cardkit/v1/cards/c_1/elements/md_body/content"
    ).mock(return_value=httpx.Response(200, json={"code": 0, "data": {}}))
    client = _make_client()

    await client.stream_card_content("c_1", "md_body", "你", 1)
    await client.stream_card_content("c_1", "md_body", "你好", 2)
    await client.stream_card_content("c_1", "md_body", "你好世界", 3)

    bodies = [json.loads(call.request.content) for call in route.calls]
    sequences = [b["sequence"] for b in bodies]
    contents = [b["content"] for b in bodies]
    assert sequences == [1, 2, 3]
    assert all(sequences[i] < sequences[i + 1] for i in range(len(sequences) - 1))
    assert contents == ["你", "你好", "你好世界"]


@pytest.mark.asyncio
@respx.mock
async def test_stream_card_content_includes_uuid_when_provided() -> None:
    """uuid 非空 → body 含 uuid。"""
    route = respx.put(
        f"{OPEN_API_BASE}/cardkit/v1/cards/c_1/elements/md_body/content"
    ).mock(return_value=httpx.Response(200, json={"code": 0, "data": {}}))
    client = _make_client()

    await client.stream_card_content("c_1", "md_body", "你好", 1, uuid="abc")

    body = json.loads(route.calls.last.request.content)
    assert body["uuid"] == "abc"


@pytest.mark.asyncio
@respx.mock
async def test_stream_card_content_raises_on_sequence_error() -> None:
    """code=300317（sequence 未递增）→ FeishuIMError。"""
    respx.put(
        f"{OPEN_API_BASE}/cardkit/v1/cards/c_1/elements/md_body/content"
    ).mock(return_value=httpx.Response(400, json={"code": 300317, "msg": "bad sequence"}))
    client = _make_client()

    with pytest.raises(FeishuIMError) as exc_info:
        await client.stream_card_content("c_1", "md_body", "你好", 1)
    assert exc_info.value.code == 300317


# === settle_card_stream ===


@pytest.mark.asyncio
@respx.mock
async def test_settle_card_stream_patches_settings_streaming_off() -> None:
    """PATCH .../settings：settings 串还原后 streaming_mode=false，带 sequence。"""
    route = respx.patch(f"{OPEN_API_BASE}/cardkit/v1/cards/c_1/settings").mock(
        return_value=httpx.Response(200, json={"code": 0, "data": {}})
    )
    client = _make_client()

    ok = await client.settle_card_stream("c_1", 4)

    assert ok is True
    body = json.loads(route.calls.last.request.content)
    assert body["sequence"] == 4
    settings = json.loads(body["settings"])
    assert settings["config"]["streaming_mode"] is False


@pytest.mark.asyncio
@respx.mock
async def test_settle_card_stream_raises_on_error() -> None:
    """code!=0 → FeishuIMError。"""
    respx.patch(f"{OPEN_API_BASE}/cardkit/v1/cards/c_1/settings").mock(
        return_value=httpx.Response(400, json={"code": 300309, "msg": "stream closed"})
    )
    client = _make_client()

    with pytest.raises(FeishuIMError) as exc_info:
        await client.settle_card_stream("c_1", 4)
    assert exc_info.value.code == 300309
