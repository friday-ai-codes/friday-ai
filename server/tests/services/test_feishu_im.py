"""FeishuIMClient 群聊方法单元测试。"""
import time
from unittest.mock import AsyncMock, Mock, patch
import pytest
from services.feishu_im import FeishuIMClient, FeishuIMError
# ============================================================================
# get_chat_members 测试
# ============================================================================
@pytest.mark.asyncio
async def test_get_chat_members_returns_member_list:
 """get_chat_members 返回群聊成员 ID 列表。"""
 client = FeishuIMClient(app_id="cli_test", app_secret="secret")
 client._tenant_token = "mock_token"
 client._token_expires_at = time.time + 3600
 mock_response = Mock
 mock_response.json.return_value = {
 "code": 0,
 "data": {
 "items": [
 {"member_id": "cli_test", "member_id_type": "app_id", "name": "Test Bot"},
 {"member_id": "cli_other", "member_id_type": "app_id", "name": "Other"},
 ]
 },
 }
 with patch("httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
 mock_client.get.return_value = mock_response
 result = await client.get_chat_members("oc_test_chat")
 assert len(result) == 2
 assert result[0]["member_id"] == "cli_test"
# ============================================================================
# add_bot_to_chat 测试
# ============================================================================
@pytest.mark.asyncio
async def test_add_bot_to_chat_success:
 """add_bot_to_chat 成功加入群聊返回正确响应。"""
 client = FeishuIMClient(app_id="cli_test", app_secret="secret")
 client._tenant_token = "mock_token"
 client._token_expires_at = time.time + 3600
 mock_response = Mock
 mock_response.json.return_value = {"code": 0, "data": {}}
 with patch("httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
 mock_client.post.return_value = mock_response
 result = await client.add_bot_to_chat("oc_test_chat")
 assert result == {}
@pytest.mark.asyncio
async def test_add_bot_to_chat_already_member:
 """add_bot_to_chat 已是成员时抛出 FeishuIMError（幂等处理在 ensure 层）。"""
 client = FeishuIMClient(app_id="cli_test", app_secret="secret")
 client._tenant_token = "mock_token"
 client._token_expires_at = time.time + 3600
 mock_response = Mock
 # 飞书 API 返回 10007（已是成员）
 mock_response.json.return_value = {
 "code": 10007,
 "msg": "member already in chat",
 }
 with patch("httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
 mock_client.post.return_value = mock_response
 with pytest.raises(FeishuIMError) as exc_info:
 await client.add_bot_to_chat("oc_test_chat")
 assert exc_info.value.code == 10007
# ============================================================================
# is_bot_in_chat 测试
# ============================================================================
@pytest.mark.asyncio
async def test_is_bot_in_chat_returns_true:
 """is_bot_in_chat 返回 True 当 Bot 在群内。"""
 client = FeishuIMClient(app_id="cli_test", app_secret="secret")
 client._tenant_token = "mock_token"
 client._token_expires_at = time.time + 3600
 mock_response = Mock
 mock_response.json.return_value = {
 "code": 0,
 "data": {
 "items": [
 {"member_id": "cli_test", "member_id_type": "app_id"},
 {"member_id": "cli_other", "member_id_type": "app_id"},
 ]
 },
 }
 with patch("httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
 mock_client.get.return_value = mock_response
 result = await client.is_bot_in_chat("oc_test_chat")
 assert result is True
@pytest.mark.asyncio
async def test_is_bot_in_chat_returns_false:
 """is_bot_in_chat 返回 False 当 Bot 不在群内。"""
 client = FeishuIMClient(app_id="cli_test", app_secret="secret")
 client._tenant_token = "mock_token"
 client._token_expires_at = time.time + 3600
 mock_response = Mock
 mock_response.json.return_value = {
 "code": 0,
 "data": {
 "items": [
 {"member_id": "cli_other", "member_id_type": "app_id"},
 ]
 },
 }
 with patch("httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
 mock_client.get.return_value = mock_response
 result = await client.is_bot_in_chat("oc_test_chat")
 assert result is False
# ============================================================================
# ensure_bot_in_chat 测试
# ============================================================================
@pytest.mark.asyncio
async def test_ensure_bot_in_chat_success:
 """ensure_bot_in_chat 成功加入返回 {success: True, already_member: False}。"""
 client = FeishuIMClient(app_id="cli_test", app_secret="secret")
 client._tenant_token = "mock_token"
 client._token_expires_at = time.time + 3600
 # Mock is_bot_in_chat -> False, add_bot_to_chat -> success
 mock_get_response = Mock
 mock_get_response.json.return_value = {
 "code": 0,
 "data": {"items": },
 }
 mock_post_response = Mock
 mock_post_response.json.return_value = {"code": 0, "data": {}}
 with patch("httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
 mock_client.get.return_value = mock_get_response
 mock_client.post.return_value = mock_post_response
 result = await client.ensure_bot_in_chat("oc_test_chat")
 assert result["success"] is True
 assert result["already_member"] is False
 assert result["error"] is None
@pytest.mark.asyncio
async def test_ensure_bot_in_chat_already_member:
 """ensure_bot_in_chat 已是成员返回 {success: True, already_member: True}。"""
 client = FeishuIMClient(app_id="cli_test", app_secret="secret")
 client._tenant_token = "mock_token"
 client._token_expires_at = time.time + 3600
 mock_response = Mock
 mock_response.json.return_value = {
 "code": 0,
 "data": {
 "items": [
 {"member_id": "cli_test", "member_id_type": "app_id"},
 ]
 },
 }
 with patch("httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
 mock_client.get.return_value = mock_response
 result = await client.ensure_bot_in_chat("oc_test_chat")
 assert result["success"] is True
 assert result["already_member"] is True
 assert result["error"] is None
@pytest.mark.asyncio
async def test_ensure_bot_in_chat_permission_denied:
 """ensure_bot_in_chat 权限受限返回 {success: False, error: '...'}。"""
 client = FeishuIMClient(app_id="cli_test", app_secret="secret")
 client._tenant_token = "mock_token"
 client._token_expires_at = time.time + 3600
 # Mock is_bot_in_chat -> False
 mock_get_response = Mock
 mock_get_response.json.return_value = {
 "code": 0,
 "data": {"items": },
 }
 # Mock add_bot_to_chat -> permission denied
 mock_post_response = Mock
 mock_post_response.json.return_value = {
 "code": 10003,
 "msg": "no permission to add member",
 }
 with patch("httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
 mock_client.get.return_value = mock_get_response
 mock_client.post.return_value = mock_post_response
 result = await client.ensure_bot_in_chat("oc_test_chat")
 assert result["success"] is False
 assert result["already_member"] is False
 assert result["error"] is not None
 assert "permission" in result["error"].lower or "10003" in result["error"]
