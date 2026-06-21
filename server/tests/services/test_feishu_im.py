"""FeishuIMClient 群聊方法单元测试。

覆盖：
- get_chat_members：获取群聊成员列表
- is_bot_in_chat：检查 Bot 是否在群聊中
- add_bot_to_chat：将 Bot 加入群聊
- ensure_bot_in_chat：幂等加入 + 降级处理
"""

import time
from unittest.mock import AsyncMock, Mock, patch

import pytest

from services.feishu_im import (
    FeishuIMClient,
    FeishuIMError,
    FeishuIMService,
    RateLimitError,
)


def _make_client() -> FeishuIMClient:
    """创建预设 token 的测试客户端。"""
    client = FeishuIMClient(app_id="cli_test_app", app_secret="secret")
    client._tenant_token = "mock_token"
    client._token_expires_at = time.time() + 3600
    return client


def _mock_response(data: dict) -> Mock:
    """创建模拟的 httpx Response。"""
    resp = Mock()
    resp.json = Mock(return_value=data)
    return resp


def _mock_binary_response(content: bytes, *, content_type: str = "image/png") -> Mock:
    """创建模拟的二进制 httpx Response。"""
    resp = Mock()
    resp.content = content
    resp.headers = {"content-type": content_type}
    resp.json = Mock(side_effect=ValueError("not json"))
    return resp


# ============================================================================
# get_chat_members
# ============================================================================


@pytest.mark.asyncio
async def test_get_chat_members_success():
    """get_chat_members 返回群聊成员列表。"""
    client = _make_client()
    members = [
        {"member_id": "cli_test_app", "name": "Test Bot"},
        {"member_id": "cli_other", "name": "Other App"},
    ]

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_http.get.return_value = _mock_response(
            {"code": 0, "data": {"items": members}}
        )

        result = await client.get_chat_members("oc_test_chat")

    assert len(result) == 2
    assert result[0]["member_id"] == "cli_test_app"


@pytest.mark.asyncio
async def test_get_chat_members_api_error():
    """get_chat_members API 错误时抛出 FeishuIMError。"""
    client = _make_client()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_http.get.return_value = _mock_response(
            {"code": 99991, "msg": "chat not found"}
        )

        with pytest.raises(FeishuIMError, match="获取群聊成员失败"):
            await client.get_chat_members("oc_bad")


@pytest.mark.asyncio
async def test_download_message_resource_success():
    """download_message_resource 调用消息资源接口并返回 bytes + mime。"""
    client = _make_client()
    payload = b"\x89PNG\r\n\x1a\nfake"

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_http.get.return_value = _mock_binary_response(payload, content_type="image/png")

        result = await client.download_message_resource(
            message_id="msg_1",
            file_key="img_1",
            resource_type="image",
        )

    assert result.content == payload
    assert result.mime_type == "image/png"
    mock_http.get.assert_awaited_once()
    assert mock_http.get.await_args.args[0].endswith("/im/v1/messages/msg_1/resources/img_1")
    assert mock_http.get.await_args.kwargs["params"] == {"type": "image"}


@pytest.mark.asyncio
async def test_download_message_resource_api_error():
    """download_message_resource API 错误时抛出 FeishuIMError。"""
    client = _make_client()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_http.get.return_value = _mock_response({"code": 234043, "msg": "resource not found"})

        with pytest.raises(FeishuIMError, match="获取消息资源失败"):
            await client.download_message_resource(
                message_id="msg_1",
                file_key="bad_img",
                resource_type="image",
            )


# ============================================================================
# add_bot_to_chat
# ============================================================================


@pytest.mark.asyncio
async def test_add_bot_to_chat_success():
    """add_bot_to_chat 成功加入群聊。"""
    client = _make_client()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_http.post.return_value = _mock_response({"code": 0, "data": {}})

        result = await client.add_bot_to_chat("oc_test_chat")

    assert result == {}


@pytest.mark.asyncio
async def test_add_bot_to_chat_permission_denied():
    """add_bot_to_chat 权限受限时抛出 FeishuIMError。"""
    client = _make_client()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_http.post.return_value = _mock_response(
            {"code": 230001, "msg": "no permission"}
        )

        with pytest.raises(FeishuIMError, match="Bot 加入群聊失败"):
            await client.add_bot_to_chat("oc_restricted")


# ============================================================================
# create_chat（建群即拉人单步）
# ============================================================================


@pytest.mark.asyncio
async def test_create_chat_success():
    """create_chat 成功建群并返回含 chat_id 的 data；端点/params/body 形状正确。"""
    client = _make_client()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_http.post.return_value = _mock_response(
            {"code": 0, "data": {"chat_id": "oc_new", "name": "需求群"}}
        )

        result = await client.create_chat("需求群", user_id_list=["ou_a", "ou_b"])

    assert result["chat_id"] == "oc_new"
    assert mock_http.post.await_args.args[0].endswith("/im/v1/chats")
    assert mock_http.post.await_args.kwargs["params"] == {"user_id_type": "open_id"}
    assert mock_http.post.await_args.kwargs["json"]["name"] == "需求群"
    assert mock_http.post.await_args.kwargs["json"]["user_id_list"] == ["ou_a", "ou_b"]


@pytest.mark.asyncio
async def test_create_chat_omits_empty_fields():
    """create_chat 不传 owner_id/description 时 body 不含这两个字段。"""
    client = _make_client()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_http.post.return_value = _mock_response(
            {"code": 0, "data": {"chat_id": "oc_new"}}
        )

        await client.create_chat("群", user_id_list=["ou_a"])

    body = mock_http.post.await_args.kwargs["json"]
    assert "owner_id" not in body
    assert "description" not in body


@pytest.mark.asyncio
async def test_create_chat_user_id_type_passthrough():
    """create_chat 透传 user_id_type 到 query。"""
    client = _make_client()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_http.post.return_value = _mock_response(
            {"code": 0, "data": {"chat_id": "oc_new"}}
        )

        await client.create_chat("群", user_id_list=["u1"], user_id_type="user_id")

    assert mock_http.post.await_args.kwargs["params"]["user_id_type"] == "user_id"


@pytest.mark.asyncio
async def test_create_chat_owner_and_set_bot_manager():
    """create_chat 带 owner_id + set_bot_manager 时 body 含 owner_id、query 含 set_bot_manager。"""
    client = _make_client()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_http.post.return_value = _mock_response(
            {"code": 0, "data": {"chat_id": "oc_new"}}
        )

        await client.create_chat(
            "群",
            user_id_list=["ou_a"],
            owner_id="ou_owner",
            set_bot_manager=True,
        )

    assert mock_http.post.await_args.kwargs["json"]["owner_id"] == "ou_owner"
    assert "set_bot_manager" in mock_http.post.await_args.kwargs["params"]


@pytest.mark.asyncio
async def test_create_chat_api_error():
    """create_chat code!=0 时抛出 FeishuIMError 并带 code。"""
    client = _make_client()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_http.post.return_value = _mock_response(
            {"code": 230002, "msg": "no permission"}
        )

        with pytest.raises(FeishuIMError, match="创建群聊失败") as exc_info:
            await client.create_chat("群", user_id_list=["ou_a"])

    assert exc_info.value.code == 230002


@pytest.mark.asyncio
async def test_create_chat_rate_limit():
    """create_chat 触发 rate limit（99991400）时抛出 RateLimitError。"""
    client = _make_client()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_http.post.return_value = _mock_response(
            {"code": 99991400, "msg": "rate limit"}
        )

        with pytest.raises(RateLimitError):
            await client.create_chat("群", user_id_list=["ou_a"])


# ============================================================================
# is_bot_in_chat
# ============================================================================


@pytest.mark.asyncio
async def test_is_bot_in_chat_true():
    """is_bot_in_chat 返回 True 当 Bot 在群内。"""
    client = _make_client()

    with patch.object(
        client, "get_chat_members", return_value=[{"member_id": "cli_test_app"}]
    ):
        assert await client.is_bot_in_chat("oc_chat") is True


@pytest.mark.asyncio
async def test_is_bot_in_chat_false():
    """is_bot_in_chat 返回 False 当 Bot 不在群内。"""
    client = _make_client()

    with patch.object(
        client, "get_chat_members", return_value=[{"member_id": "cli_other"}]
    ):
        assert await client.is_bot_in_chat("oc_chat") is False


@pytest.mark.asyncio
async def test_is_bot_in_chat_error_returns_false():
    """is_bot_in_chat 查询失败时降级返回 False。"""
    client = _make_client()

    with patch.object(
        client, "get_chat_members", side_effect=FeishuIMError("network error")
    ):
        assert await client.is_bot_in_chat("oc_chat") is False


# ============================================================================
# ensure_bot_in_chat
# ============================================================================


@pytest.mark.asyncio
async def test_ensure_bot_in_chat_already_member():
    """ensure_bot_in_chat 已是成员返回 {success: True, already_member: True}。"""
    client = _make_client()

    with patch.object(client, "is_bot_in_chat", return_value=True):
        result = await client.ensure_bot_in_chat("oc_chat")

    assert result["success"] is True
    assert result["already_member"] is True
    assert result["error"] is None


@pytest.mark.asyncio
async def test_ensure_bot_in_chat_join_success():
    """ensure_bot_in_chat 成功加入返回 {success: True, already_member: False}。"""
    client = _make_client()

    with (
        patch.object(client, "is_bot_in_chat", return_value=False),
        patch.object(client, "add_bot_to_chat", return_value={}),
    ):
        result = await client.ensure_bot_in_chat("oc_chat")

    assert result["success"] is True
    assert result["already_member"] is False
    assert result["error"] is None


@pytest.mark.asyncio
async def test_ensure_bot_in_chat_permission_denied():
    """ensure_bot_in_chat 权限受限返回 {success: False, error: "..."}。"""
    client = _make_client()

    with (
        patch.object(client, "is_bot_in_chat", return_value=False),
        patch.object(
            client,
            "add_bot_to_chat",
            side_effect=FeishuIMError("no permission", code=230001),
        ),
    ):
        result = await client.ensure_bot_in_chat("oc_restricted")

    assert result["success"] is False
    assert result["already_member"] is False
    assert "no permission" in result["error"]


# ============================================================================
# get_chat_id_for_work_item (FeishuIMService)
# ============================================================================


def _make_service_with_project_client() -> tuple[FeishuIMService, Mock]:
    """创建带 mock project_client 的 FeishuIMService。"""
    client = _make_client()
    project_client = AsyncMock()
    service = FeishuIMService(client=client, project_client=project_client)
    return service, project_client


def _work_item_info(fields: dict) -> Mock:
    """创建模拟的 WorkItemInfo。"""
    info = Mock()
    info.fields = fields
    return info


@pytest.mark.asyncio
async def test_get_chat_id_for_work_item_success():
    """get_chat_id_for_work_item 成功返回结构化结果。"""
    service, project_client = _make_service_with_project_client()
    project_client.get_work_item.return_value = _work_item_info(
        {"chat_id": "oc_abc123", "title": "需求标题"}
    )

    result = await service.get_chat_id_for_work_item("proj_key", 12345)

    assert result is not None
    assert result["chat_id"] == "oc_abc123"
    assert result["source"] == "work_item_api"


@pytest.mark.asyncio
async def test_get_chat_id_for_work_item_no_chat():
    """工作项无关联群聊时返回 None。"""
    service, project_client = _make_service_with_project_client()
    project_client.get_work_item.return_value = _work_item_info(
        {"title": "需求标题", "status": "open"}
    )

    result = await service.get_chat_id_for_work_item("proj_key", 12345)
    assert result is None


@pytest.mark.asyncio
async def test_get_chat_id_for_work_item_multiple_chats():
    """多个群聊时只取第一个。"""
    service, project_client = _make_service_with_project_client()
    project_client.get_work_item.return_value = _work_item_info(
        {
            "group_list": [
                {"chat_id": "oc_first", "name": "群1"},
                {"chat_id": "oc_second", "name": "群2"},
            ],
        }
    )

    result = await service.get_chat_id_for_work_item("proj_key", 12345)

    assert result is not None
    assert result["chat_id"] == "oc_first"
    assert result["chat_name"] == "群1"


@pytest.mark.asyncio
async def test_get_chat_id_for_work_item_group_id_field():
    """语义字段 group_id 含合法 oc_ 群 ID → 正确取出（项目跟踪类型场景）。"""
    service, project_client = _make_service_with_project_client()
    project_client.get_work_item.return_value = _work_item_info(
        {
            "group_type": "bind",
            "group_id": "oc_88aa55c5263514cbf285f8a6a3a08f27",
            "chat_group": "oc_88aa55c5263514cbf285f8a6a3a08f27",
        }
    )

    result = await service.get_chat_id_for_work_item("proj_key", 7019341893)

    assert result is not None
    assert result["chat_id"] == "oc_88aa55c5263514cbf285f8a6a3a08f27"


@pytest.mark.asyncio
async def test_get_chat_id_for_work_item_group_type_disabled_rejected():
    """未绑定：group_type='disabled' 不是合法 oc_ 群 ID → 返回 None（修复误报）。

    历史 bug：key 含 'group' 的 group_type 字段值 'disabled' 被当成 chat_id 返回。
    oc_ 正则校验后，'disabled' 被拒，正确判为未绑定。
    """
    service, project_client = _make_service_with_project_client()
    project_client.get_work_item.return_value = _work_item_info(
        {"group_type": "disabled", "title": "需求标题"}
    )

    result = await service.get_chat_id_for_work_item("proj_key", 6659791768)
    assert result is None


@pytest.mark.asyncio
async def test_get_chat_id_for_work_item_invalid_format_rejected():
    """字段值非 oc_ 格式（如普通字符串）→ 拒绝，返回 None。"""
    service, project_client = _make_service_with_project_client()
    project_client.get_work_item.return_value = _work_item_info(
        {"chat_id": "not_a_chat_id"}
    )

    result = await service.get_chat_id_for_work_item("proj_key", 12345)
    assert result is None


@pytest.mark.asyncio
async def test_get_chat_id_for_work_item_api_failure():
    """API 调用失败时返回 None。"""
    service, project_client = _make_service_with_project_client()
    project_client.get_work_item.side_effect = Exception("API timeout")

    result = await service.get_chat_id_for_work_item("proj_key", 12345)
    assert result is None


@pytest.mark.asyncio
async def test_get_chat_id_for_work_item_no_project_client():
    """无 project_client 时返回 None。"""
    client = _make_client()
    service = FeishuIMService(client=client, project_client=None)

    result = await service.get_chat_id_for_work_item("proj_key", 12345)
    assert result is None
