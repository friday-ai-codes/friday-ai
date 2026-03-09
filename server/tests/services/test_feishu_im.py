"""FeishuIMClient 群聊方法单元测试。"""
import time
from unittest.mock import AsyncMock, Mock, patch
import pytest
from services.feishu import WorkItemInfo
from services.feishu_im import FeishuIMClient, FeishuIMError, FeishuIMService
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
# ============================================================================
# get_chat_id_for_work_item 测试
# ============================================================================
def _make_work_item_info(fields: dict) -> WorkItemInfo:
 """辅助函数：创建模拟的 WorkItemInfo。"""
 return WorkItemInfo(
 id=12345,
 name="测试需求",
 description="描述",
 status="open",
 project_key="test-proj",
 work_item_type="story",
 fields=fields,
 )
def _make_service_with_mock_project_client(
 work_item_info: WorkItemInfo | None = None,
 get_work_item_side_effect: Exception | None = None,
) -> tuple[FeishuIMService, AsyncMock]:
 """辅助函数：创建带 mock project_client 的 FeishuIMService。"""
 im_client = FeishuIMClient(app_id="cli_test", app_secret="secret")
 mock_project_client = AsyncMock
 if get_work_item_side_effect:
 mock_project_client.get_work_item.side_effect = get_work_item_side_effect
 elif work_item_info:
 mock_project_client.get_work_item.return_value = work_item_info
 service = FeishuIMService(client=im_client, project_client=mock_project_client)
 return service, mock_project_client
@pytest.mark.asyncio
async def test_get_chat_id_for_work_item_success:
 """成功获取工作项关联群聊 ID，返回结构化结果。"""
 fields = {
 "chat_group": [{"chat_id": "oc_chat_123", "name": "需求群聊"}],
 }
 work_item = _make_work_item_info(fields)
 service, _ = _make_service_with_mock_project_client(work_item_info=work_item)
 result = await service.get_chat_id_for_work_item("test-proj", 12345)
 assert result is not None
 assert result["chat_id"] == "oc_chat_123"
 assert result["source"] == "work_item_api"
@pytest.mark.asyncio
async def test_get_chat_id_for_work_item_no_chat:
 """工作项无关联群聊时返回 None。"""
 fields = {"priority": "P1", "status": "open"}
 work_item = _make_work_item_info(fields)
 service, _ = _make_service_with_mock_project_client(work_item_info=work_item)
 result = await service.get_chat_id_for_work_item("test-proj", 12345)
 assert result is None
@pytest.mark.asyncio
async def test_get_chat_id_for_work_item_multiple_chats:
 """一个工作项关联多个群聊时只取第一个。"""
 fields = {
 "chat_group": [
 {"chat_id": "oc_first", "name": "第一个群"},
 {"chat_id": "oc_second", "name": "第二个群"},
 ],
 }
 work_item = _make_work_item_info(fields)
 service, _ = _make_service_with_mock_project_client(work_item_info=work_item)
 result = await service.get_chat_id_for_work_item("test-proj", 12345)
 assert result is not None
 assert result["chat_id"] == "oc_first"
@pytest.mark.asyncio
async def test_get_chat_id_for_work_item_api_failure:
 """API 调用失败时返回 None。"""
 service, _ = _make_service_with_mock_project_client(
 get_work_item_side_effect=Exception("API 连接超时")
 )
 result = await service.get_chat_id_for_work_item("test-proj", 12345)
 assert result is None
