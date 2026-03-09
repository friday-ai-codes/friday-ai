"""FetchGroupChatNode 和 JoinGroupChatNode 单元测试。
纯 mock 测试，不需要数据库。
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from workflows.nodes.base import ExecutionContext, NodeResult
from workflows.nodes.integrations.feishu_chat import (
 FetchGroupChatNode,
 JoinGroupChatNode,
)
def _make_context(
 config: dict | None = None,
 input_data: dict | None = None,
 workflow_execution: object | None = None,
) -> ExecutionContext:
 """构建 mock ExecutionContext。"""
 ctx = ExecutionContext(
 execution_id="exec-001",
 node_id="node-001",
 node_config=config or {},
 input_data=input_data or {},
 workflow_context={},
 previous_outputs={},
 workflow_execution=workflow_execution, # type: ignore[arg-type]
 )
 return ctx
def _mock_im_service(
 get_chat_id_return: dict | None = None,
 ensure_bot_return: dict | None = None,
) -> AsyncMock:
 """构建 AsyncMock FeishuIMService。"""
 service = AsyncMock
 service.get_chat_id_for_work_item = AsyncMock(return_value=get_chat_id_return)
 service.ensure_bot_in_chat = AsyncMock(return_value=ensure_bot_return)
 return service
# ==================== FetchGroupChatNode 测试 ====================
@pytest.mark.asyncio
async def test_fetch_group_chat_with_config_chat_id -> None:
 """配置了 chat_id 时直接返回 {chat_id, source: "config"}。"""
 node = FetchGroupChatNode
 ctx = _make_context(config={"chat_id": "oc_test123"})
 result = await node.execute(ctx)
 assert result.status == "completed"
 assert result.output["chat_id"] == "oc_test123"
 assert result.output["source"] == "config"
 assert result.next_handle == "default"
@pytest.mark.asyncio
async def test_fetch_group_chat_from_work_item -> None:
 """未配置 chat_id 时从工作项获取。"""
 node = FetchGroupChatNode
 mock_execution = MagicMock
 mock_execution.workflow = MagicMock
 mock_execution.workflow.project = MagicMock
 ctx = _make_context(
 config={
 "project_key": "TEST",
 "work_item_id": "12345",
 "work_item_type": "story",
 },
 workflow_execution=mock_execution,
 )
 mock_service = _mock_im_service(
 get_chat_id_return={
 "chat_id": "oc_from_item",
 "chat_name": "测试群",
 "owner_id": "user_001",
 "source": "work_item_api",
 },
 )
 with patch(
 "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
 return_value=mock_service,
 ):
 result = await node.execute(ctx)
 assert result.status == "completed"
 assert result.output["chat_id"] == "oc_from_item"
 assert result.output["source"] == "work_item_api"
 assert result.next_handle == "default"
@pytest.mark.asyncio
async def test_fetch_group_chat_no_chat_found -> None:
 """工作项也没群聊时返回 failed + error 端口。"""
 node = FetchGroupChatNode
 mock_execution = MagicMock
 mock_execution.workflow = MagicMock
 mock_execution.workflow.project = MagicMock
 ctx = _make_context(
 config={
 "project_key": "TEST",
 "work_item_id": "99999",
 "work_item_type": "story",
 },
 workflow_execution=mock_execution,
 )
 mock_service = _mock_im_service(get_chat_id_return=None)
 with patch(
 "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
 return_value=mock_service,
 ):
 result = await node.execute(ctx)
 assert result.status == "failed"
 assert result.error is not None
 assert result.next_handle == "error"
# ==================== JoinGroupChatNode 测试 ====================
@pytest.mark.asyncio
async def test_join_group_chat_success -> None:
 """ensure_bot_in_chat 返回 success=True 时成功。"""
 node = JoinGroupChatNode
 mock_execution = MagicMock
 mock_execution.workflow = MagicMock
 mock_execution.workflow.project = MagicMock
 ctx = _make_context(
 config={"chat_id": "oc_join_test"},
 workflow_execution=mock_execution,
 )
 mock_service = _mock_im_service(
 ensure_bot_return={"success": True, "already_member": False, "error": None},
 )
 with patch(
 "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
 return_value=mock_service,
 ):
 result = await node.execute(ctx)
 assert result.status == "completed"
 assert result.output["chat_id"] == "oc_join_test"
 assert result.output["already_member"] is False
 assert result.next_handle == "default"
@pytest.mark.asyncio
async def test_join_group_chat_already_member -> None:
 """已在群内时幂等成功（already_member=True）。"""
 node = JoinGroupChatNode
 mock_execution = MagicMock
 mock_execution.workflow = MagicMock
 mock_execution.workflow.project = MagicMock
 ctx = _make_context(
 config={"chat_id": "oc_already"},
 workflow_execution=mock_execution,
 )
 mock_service = _mock_im_service(
 ensure_bot_return={"success": True, "already_member": True, "error": None},
 )
 with patch(
 "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
 return_value=mock_service,
 ):
 result = await node.execute(ctx)
 assert result.status == "completed"
 assert result.output["already_member"] is True
 assert result.next_handle == "default"
@pytest.mark.asyncio
async def test_join_group_chat_permission_denied -> None:
 """权限不足时返回 failed + error 端口。"""
 node = JoinGroupChatNode
 mock_execution = MagicMock
 mock_execution.workflow = MagicMock
 mock_execution.workflow.project = MagicMock
 ctx = _make_context(
 config={"chat_id": "oc_no_perm"},
 workflow_execution=mock_execution,
 )
 mock_service = _mock_im_service(
 ensure_bot_return={
 "success": False,
 "already_member": False,
 "error": "Bot 加入群聊失败: 权限不足",
 },
 )
 with patch(
 "workflows.nodes.integrations.feishu_chat.FeishuIMService.create",
 return_value=mock_service,
 ):
 result = await node.execute(ctx)
 assert result.status == "failed"
 assert result.error is not None
 assert "权限不足" in (result.error or "")
 assert result.next_handle == "error"
