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
# ==================== GroupChatQuestionNode 测试 ====================
@pytest.mark.asyncio
async def test_chat_question_node_returns_waiting_event -> None:
 """Test 6: GroupChatQuestionNode 执行后返回 waiting_event 状态。"""
 from workflows.nodes.integrations.chat_question import GroupChatQuestionNode
 node = GroupChatQuestionNode
 mock_execution = MagicMock
 mock_execution.workflow = MagicMock
 mock_execution.workflow.project = MagicMock
 ctx = _make_context(
 config={
 "chat_id": "oc_question_test",
 "question": "选择哪个方案？",
 "options": ["方案 A", "方案 B"],
 "work_item_name": "",
 },
 workflow_execution=mock_execution,
 )
 mock_im_client = AsyncMock
 mock_im_client.send_card = AsyncMock(return_value="msg_12345")
 with patch(
 "workflows.nodes.integrations.chat_question.FeishuIMClient",
 return_value=mock_im_client,
 ), patch(
 "workflows.nodes.integrations.chat_question._get_feishu_credentials",
 return_value=("app_id", "app_secret"),
 ):
 result = await node.execute(ctx)
 assert result.status == "waiting_event"
 assert result.output["message_id"] == "msg_12345"
 assert result.output["question"] == "选择哪个方案？"
 assert result.output["chat_id"] == "oc_question_test"
 # 确认 send_card 被调用
 mock_im_client.send_card.assert_called_once
 call_kwargs = mock_im_client.send_card.call_args[1]
 assert call_kwargs["receive_id"] == "oc_question_test"
 assert call_kwargs["receive_id_type"] == "chat_id"
@pytest.mark.asyncio
async def test_chat_question_node_missing_question -> None:
 """缺少 question 配置时返回 failed。"""
 from workflows.nodes.integrations.chat_question import GroupChatQuestionNode
 node = GroupChatQuestionNode
 ctx = _make_context(config={"chat_id": "oc_test"})
 result = await node.execute(ctx)
 assert result.status == "failed"
 assert result.error is not None
@pytest.mark.asyncio
async def test_chat_question_node_missing_chat_id -> None:
 """缺少 chat_id 配置时返回 failed。"""
 from workflows.nodes.integrations.chat_question import GroupChatQuestionNode
 node = GroupChatQuestionNode
 ctx = _make_context(config={"question": "问题"})
 result = await node.execute(ctx)
 assert result.status == "failed"
 assert result.error is not None
