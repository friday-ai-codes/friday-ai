"""群聊提问回调处理器测试。"""
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from feishu.callbacks.chat_question_callback import handle_chat_question_answer
from feishu.views import CardCallback
def _make_callback(
 action_value: dict[str, Any] | str,
 user_open_id: str = "ou_test_user",
 form_value: dict[str, Any] | None = None,
) -> CardCallback:
 """构造 CardCallback 测试对象。"""
 cb = CardCallback(
 action_value=action_value,
 user_open_id=user_open_id,
 message_id="msg_test",
 chat_id="oc_test",
 tenant_key="test_tenant",
 )
 if form_value is not None:
 cb.form_value = form_value
 return cb
class TestHandleChatQuestionAnswer:
 """handle_chat_question_answer 回调处理器测试。"""
 @patch("feishu.callbacks.chat_question_callback._schedule_chat_answer_completion")
 @patch("feishu.callbacks.chat_question_callback._get_question_from_node")
 def test_extracts_ids_and_answer_from_button(
 self, mock_get_question: MagicMock, mock_schedule: MagicMock
 ) -> None:
 """Test 1: 从 callback 提取 execution_id + node_id + answer。"""
 mock_get_question.return_value = "选择方案"
 callback = _make_callback({
 "action": "chat_question_answer",
 "execution_id": "exec-1",
 "node_id": "node-1",
 "answer": "方案 A",
 })
 result = handle_chat_question_answer(callback)
 mock_schedule.assert_called_once
 call_kwargs = mock_schedule.call_args[1]
 assert call_kwargs["execution_id"] == "exec-1"
 assert call_kwargs["node_id"] == "node-1"
 assert call_kwargs["answer"] == "方案 A"
 assert result is not None
 @patch("feishu.callbacks.chat_question_callback._schedule_chat_answer_completion")
 @patch("feishu.callbacks.chat_question_callback._get_question_from_node")
 def test_button_click_answer_from_action_value(
 self, mock_get_question: MagicMock, mock_schedule: MagicMock
 ) -> None:
 """Test 2: 按钮点击时 answer 从 action_value.answer 提取。"""
 mock_get_question.return_value = "问题"
 callback = _make_callback({
 "action": "chat_question_answer",
 "execution_id": "exec-1",
 "node_id": "node-1",
 "answer": "选项 B",
 })
 handle_chat_question_answer(callback)
 call_kwargs = mock_schedule.call_args[1]
 assert call_kwargs["answer"] == "选项 B"
 @patch("feishu.callbacks.chat_question_callback._schedule_chat_answer_completion")
 @patch("feishu.callbacks.chat_question_callback._get_question_from_node")
 def test_form_submit_answer_from_custom_answer(
 self, mock_get_question: MagicMock, mock_schedule: MagicMock
 ) -> None:
 """Test 3: 表单提交时 answer 从 action_value.custom_answer 提取。
 CardCallbackView 在分发前已将 form_value 合并到 action_value 中，
 所以 custom_answer 直接出现在 action_value dict 中。
 """
 mock_get_question.return_value = "问题"
 # 模拟 CardCallbackView 合并后的 action_value
 callback = _make_callback(
 action_value={
 "action": "chat_question_answer",
 "execution_id": "exec-1",
 "node_id": "node-1",
 "custom_answer": "自定义回复内容",
 },
 )
 handle_chat_question_answer(callback)
 call_kwargs = mock_schedule.call_args[1]
 assert call_kwargs["answer"] == "自定义回复内容"
 @patch("feishu.callbacks.chat_question_callback._schedule_chat_answer_completion")
 @patch("feishu.callbacks.chat_question_callback._get_question_from_node")
 def test_returns_answered_card(
 self, mock_get_question: MagicMock, mock_schedule: MagicMock
 ) -> None:
 """Test 4: 回调返回 build_chat_answered_card 更新卡片。"""
 mock_get_question.return_value = "选择方案"
 callback = _make_callback({
 "action": "chat_question_answer",
 "execution_id": "exec-1",
 "node_id": "node-1",
 "answer": "方案 A",
 })
 result = handle_chat_question_answer(callback)
 assert result is not None
 assert result["header"]["template"] == "grey"
 assert "已收到回复" in result["header"]["title"]["content"]
 @patch("feishu.callbacks.chat_question_callback._schedule_chat_answer_completion")
 def test_missing_ids_returns_none(self, mock_schedule: MagicMock) -> None:
 """Test 5 辅助: 缺少 execution_id 或 node_id 时返回 None。"""
 callback = _make_callback({
 "action": "chat_question_answer",
 "answer": "A",
 })
 result = handle_chat_question_answer(callback)
 assert result is None
 mock_schedule.assert_not_called
 @patch("feishu.callbacks.chat_question_callback._schedule_chat_answer_completion")
 def test_missing_answer_returns_none(self, mock_schedule: MagicMock) -> None:
 """缺少 answer 时返回 None。"""
 callback = _make_callback({
 "action": "chat_question_answer",
 "execution_id": "exec-1",
 "node_id": "node-1",
 })
 result = handle_chat_question_answer(callback)
 assert result is None
 mock_schedule.assert_not_called
class TestMultiRoundChat:
 """多轮追问回调测试。"""
 @pytest.mark.asyncio
 async def test_multi_round_continues_when_not_last(self) -> None:
 """非最后一轮：更新 output_data + 发新卡片 + 保持 waiting_event。"""
 from feishu.callbacks.chat_question_callback import _do_chat_answer_async
 mock_ne = MagicMock
 mock_ne.id = "ne-multi-1"
 mock_ne.workflow_execution_id = "we-multi-1"
 mock_ne.node_id = "node-multi-1"
 mock_ne.status = "waiting_event"
 mock_ne.output_data = {
 "question": "第一轮问题",
 "max_rounds": 3,
 "current_round": 1,
 "rounds":,
 "chat_id": "oc_multi",
 "work_item_name": "",
 "mention_user_id": "ou_user1",
 }
 mock_ne.asave = AsyncMock
 mock_im_client = AsyncMock
 mock_im_client.send_card = AsyncMock(return_value="msg_new")
 with patch(
 "feishu.callbacks.chat_question_callback.NodeExecution"
 ) as mock_ne_cls, patch(
 "feishu.callbacks.chat_question_callback.FeishuIMClient",
 return_value=mock_im_client,
 ), patch(
 "feishu.callbacks.chat_question_callback.create_feishu_im_client_for_project",
 return_value=mock_im_client,
 ):
 mock_ne_cls.objects.filter.return_value.select_related.return_value.afirst = AsyncMock(return_value=mock_ne)
 await _do_chat_answer_async(
 execution_id="we-multi-1",
 node_id="node-multi-1",
 answer="第一轮回答",
 responder_id="ou_responder",
 )
 # 验证 output_data 更新：current_round 增加，rounds 添加
 mock_ne.asave.assert_called
 updated_output = mock_ne.output_data
 assert updated_output["current_round"] == 2
 assert len(updated_output["rounds"]) == 1
 assert updated_output["rounds"][0]["answer"] == "第一轮回答"
 # 发了新卡片
 mock_im_client.send_card.assert_called_once
 @pytest.mark.asyncio
 async def test_multi_round_history_in_new_card(self) -> None:
 """新追问卡片携带完整 history。"""
 from feishu.callbacks.chat_question_callback import _do_chat_answer_async
 mock_ne = MagicMock
 mock_ne.id = "ne-hist"
 mock_ne.workflow_execution_id = "we-hist"
 mock_ne.node_id = "node-hist"
 mock_ne.status = "waiting_event"
 mock_ne.output_data = {
 "question": "第二轮问题",
 "max_rounds": 3,
 "current_round": 2,
 "rounds": [{"question": "第一轮问题", "answer": "第一轮回答", "round": 1}],
 "chat_id": "oc_hist",
 "work_item_name": "",
 "mention_user_id": "",
 }
 mock_ne.asave = AsyncMock
 mock_im_client = AsyncMock
 mock_im_client.send_card = AsyncMock(return_value="msg_hist")
 with patch(
 "feishu.callbacks.chat_question_callback.NodeExecution"
 ) as mock_ne_cls, patch(
 "feishu.callbacks.chat_question_callback.FeishuIMClient",
 return_value=mock_im_client,
 ), patch(
 "feishu.callbacks.chat_question_callback.create_feishu_im_client_for_project",
 return_value=mock_im_client,
 ):
 mock_ne_cls.objects.filter.return_value.select_related.return_value.afirst = AsyncMock(return_value=mock_ne)
 await _do_chat_answer_async(
 execution_id="we-hist",
 node_id="node-hist",
 answer="第二轮回答",
 responder_id="ou_r",
 )
 # 新卡片应包含 history
 call_kwargs = mock_im_client.send_card.call_args[1]
 card = call_kwargs["card"]
 # history 区块存在（div 或 markdown 包含之前的 Q&A）
 all_content = " ".join(
 e.get("content", "") or e.get("text", {}).get("content", "")
 for e in card["elements"]
 if e.get("tag") in ("div", "markdown")
 )
 assert "第一轮问题" in all_content
 assert "第一轮回答" in all_content
 @pytest.mark.asyncio
 async def test_last_round_completes_node(self) -> None:
 """最后一轮：汇总回复 + approve_node 完成节点。"""
 from feishu.callbacks.chat_question_callback import _do_chat_answer_async
 mock_ne = MagicMock
 mock_ne.id = "ne-last"
 mock_ne.workflow_execution_id = "we-last"
 mock_ne.node_id = "node-last"
 mock_ne.status = "waiting_event"
 mock_ne.output_data = {
 "question": "最后一轮",
 "max_rounds": 2,
 "current_round": 2,
 "rounds": [{"question": "第一轮", "answer": "A1", "round": 1}],
 "chat_id": "oc_last",
 "work_item_name": "",
 "mention_user_id": "",
 }
 mock_ne.approval_data = {}
 mock_ne.asave = AsyncMock
 mock_we = MagicMock
 mock_we.status = "suspended"
 mock_we.asave = AsyncMock
 mock_ne.workflow_execution = mock_we
 mock_engine = AsyncMock
 with patch(
 "feishu.callbacks.chat_question_callback.NodeExecution"
 ) as mock_ne_cls, patch(
 "feishu.callbacks.chat_question_callback.WorkflowEngine",
 return_value=mock_engine,
 ):
 mock_ne_cls.objects.filter.return_value.select_related.return_value.afirst = AsyncMock(return_value=mock_ne)
 await _do_chat_answer_async(
 execution_id="we-last",
 node_id="node-last",
 answer="最后回答",
 responder_id="ou_final",
 )
 # 验证 approval_data 包含所有轮次
 assert mock_ne.approval_data["total_rounds"] == 2
 assert len(mock_ne.approval_data["rounds"]) == 2
 # 验证 approve_node 被调用
 mock_engine.approve_node.assert_called_once
 @pytest.mark.asyncio
 async def test_single_round_completes_immediately(self) -> None:
 """max_rounds=1 时行为等同于单轮。"""
 from feishu.callbacks.chat_question_callback import _do_chat_answer_async
 mock_ne = MagicMock
 mock_ne.id = "ne-single"
 mock_ne.workflow_execution_id = "we-single"
 mock_ne.node_id = "node-single"
 mock_ne.status = "waiting_event"
 mock_ne.output_data = {
 "question": "单轮问题",
 "max_rounds": 1,
 "current_round": 1,
 "rounds":,
 "chat_id": "oc_single",
 "work_item_name": "",
 "mention_user_id": "",
 }
 mock_ne.approval_data = {}
 mock_ne.asave = AsyncMock
 mock_we = MagicMock
 mock_we.status = "suspended"
 mock_we.asave = AsyncMock
 mock_ne.workflow_execution = mock_we
 mock_engine = AsyncMock
 with patch(
 "feishu.callbacks.chat_question_callback.NodeExecution"
 ) as mock_ne_cls, patch(
 "feishu.callbacks.chat_question_callback.WorkflowEngine",
 return_value=mock_engine,
 ):
 mock_ne_cls.objects.filter.return_value.select_related.return_value.afirst = AsyncMock(return_value=mock_ne)
 await _do_chat_answer_async(
 execution_id="we-single",
 node_id="node-single",
 answer="唯一回答",
 responder_id="ou_s",
 )
 # 单轮应直接完成
 mock_engine.approve_node.assert_called_once
 assert mock_ne.approval_data["total_rounds"] == 1
