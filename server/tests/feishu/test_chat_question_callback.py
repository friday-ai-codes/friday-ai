"""群聊提问回调处理器测试。"""
from typing import Any
from unittest.mock import MagicMock, patch
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
