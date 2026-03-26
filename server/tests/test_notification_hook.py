"""Tests for NotificationHook behavior."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from workflows.hooks.builtin import NotificationHook
@pytest.fixture
def hook -> NotificationHook:
 return NotificationHook
@pytest.fixture
def execution -> SimpleNamespace:
 workflow = SimpleNamespace(project="workflow-project")
 return SimpleNamespace(
 id="execution-001",
 context={"chat_id": "oc_test_chat"},
 input_data={},
 is_debug=False,
 workflow=workflow,
 project="execution-project",
 error_message="",
 feishu_message_id="",
 asave=AsyncMock,
 )
@pytest.fixture
def node_execution -> SimpleNamespace:
 node = SimpleNamespace(
 name="审批节点",
 config={"description_template": "请审批本次变更"},
 )
 return SimpleNamespace(node=node)
@pytest.mark.asyncio
@pytest.mark.parametrize(
 ("event", "error_message", "expected_color", "expected_texts", "use_node_execution"),
 [
 (
 "execution_completed",
 "",
 "green",
 ["工作流执行完成"],
 False,
 ),
 (
 "execution_failed",
 "调用模型失败",
 "red",
 ["工作流执行失败", "调用模型失败"],
 False,
 ),
 (
 "node_waiting_approval",
 "",
 "orange",
 ["等待审批", "审批节点", "请审批本次变更"],
 True,
 ),
 ],
)
async def test_target_events_send_feishu_card_and_persist_message_id(
 hook: NotificationHook,
 execution: SimpleNamespace,
 node_execution: SimpleNamespace,
 event: str,
 error_message: str,
 expected_color: str,
 expected_texts: list[str],
 use_node_execution: bool,
) -> None:
 execution.error_message = error_message
 mock_service = AsyncMock
 mock_service.send_card = AsyncMock(return_value="msg_123")
 kwargs = {"execution": execution}
 if use_node_execution:
 kwargs["node_execution"] = node_execution
 with patch(
 "services.feishu_im.FeishuIMService.create",
 new_callable=AsyncMock,
 return_value=mock_service,
 ) as mock_create:
 await hook.execute(event, **kwargs)
 mock_create.assert_awaited_once_with(execution.workflow.project)
 mock_service.send_card.assert_awaited_once
 send_kwargs = mock_service.send_card.await_args.kwargs
 assert send_kwargs["receive_id"] == "oc_test_chat"
 assert send_kwargs["receive_id_type"] == "chat_id"
 card = send_kwargs["card"]
 assert card["header"]["title"]["content"] == "工作流通知"
 assert card["header"]["template"] == expected_color
 content = card["elements"][0]["content"]
 for text in expected_texts:
 assert text in content
 assert execution.feishu_message_id == "msg_123"
 execution.asave.assert_awaited_once_with(update_fields=["feishu_message_id"])
@pytest.mark.asyncio
async def test_non_target_event_returns_without_send(
 hook: NotificationHook,
 execution: SimpleNamespace,
) -> None:
 with patch("services.feishu_im.FeishuIMService.create", new_callable=AsyncMock) as mock_create:
 await hook.execute("node_started", execution=execution)
 mock_create.assert_not_called
 execution.asave.assert_not_awaited
@pytest.mark.asyncio
async def test_debug_execution_skips_notification_without_dirty_data(
 hook: NotificationHook,
 execution: SimpleNamespace,
) -> None:
 execution.is_debug = True
 execution.feishu_message_id = "existing-message"
 with patch("services.feishu_im.FeishuIMService.create", new_callable=AsyncMock) as mock_create:
 await hook.execute("execution_completed", execution=execution)
 mock_create.assert_not_called
 execution.asave.assert_not_awaited
 assert execution.feishu_message_id == "existing-message"
@pytest.mark.asyncio
async def test_missing_chat_id_skips_silently(
 hook: NotificationHook,
 execution: SimpleNamespace,
) -> None:
 execution.context = {}
 execution.input_data = {}
 with patch("services.feishu_im.FeishuIMService.create", new_callable=AsyncMock) as mock_create:
 await hook.execute("execution_completed", execution=execution)
 mock_create.assert_not_called
 execution.asave.assert_not_awaited
 assert execution.feishu_message_id == ""
@pytest.mark.asyncio
async def test_chat_id_falls_back_to_input_data(
 hook: NotificationHook,
 execution: SimpleNamespace,
) -> None:
 execution.context = {}
 execution.input_data = {"chat_id": "oc_chat_from_input"}
 mock_service = AsyncMock
 mock_service.send_card = AsyncMock(return_value="msg_from_input")
 with patch(
 "services.feishu_im.FeishuIMService.create",
 new_callable=AsyncMock,
 return_value=mock_service,
 ):
 await hook.execute("execution_completed", execution=execution)
 send_kwargs = mock_service.send_card.await_args.kwargs
 assert send_kwargs["receive_id"] == "oc_chat_from_input"
 assert execution.feishu_message_id == "msg_from_input"
 execution.asave.assert_awaited_once_with(update_fields=["feishu_message_id"])
@pytest.mark.asyncio
@pytest.mark.parametrize("create_raises", [True, False])
async def test_feishu_errors_are_swallowed_without_overwriting_message_id(
 hook: NotificationHook,
 execution: SimpleNamespace,
 create_raises: bool,
) -> None:
 execution.feishu_message_id = "existing-message"
 if create_raises:
 create_patch = patch(
 "services.feishu_im.FeishuIMService.create",
 new_callable=AsyncMock,
 side_effect=RuntimeError("create failed"),
 )
 else:
 mock_service = AsyncMock
 mock_service.send_card = AsyncMock(side_effect=RuntimeError("send failed"))
 create_patch = patch(
 "services.feishu_im.FeishuIMService.create",
 new_callable=AsyncMock,
 return_value=mock_service,
 )
 with create_patch:
 await hook.execute("execution_failed", execution=execution)
 assert execution.feishu_message_id == "existing-message"
 execution.asave.assert_not_awaited
