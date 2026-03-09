"""群聊提问卡片回调处理器。
处理群聊提问卡片的按钮点击和表单提交回调。
严格参考 approval_callback.py 的模式：
- 同步处理器（飞书回调需 3 秒内响应）
- _schedule_chat_answer_completion 在后台线程异步恢复工作流
"""
import json
from typing import Any
import structlog
from feishu.cards.chat_question_card import build_chat_answered_card
from feishu.views import CardCallback, register_card_callback
from workflows.engine.scheduler import WorkflowEngine, _run_in_thread
from workflows.models.execution import NodeExecution, NodeExecutionStatus
logger = structlog.get_logger(__name__)
@register_card_callback("chat_question_answer")
def handle_chat_question_answer(callback: CardCallback) -> dict[str, Any] | None:
 """处理群聊提问卡片的回答回调。
 支持两种回答方式：
 1. 按钮点击：answer 在 action_value.answer
 2. 表单提交：answer 在 action_value.custom_answer（CardCallbackView 已合并 form_value）
 Args:
 callback: 卡片回调数据
 Returns:
 已回复状态卡片 JSON，或 None（参数缺失时）
 """
 data = _extract_callback_data(callback)
 if not data:
 return None
 execution_id = data.get("execution_id", "")
 node_id = data.get("node_id", "")
 # 按钮点击：answer 字段；表单提交：custom_answer 字段
 answer = data.get("answer", "") or data.get("custom_answer", "")
 if not execution_id or not node_id:
 logger.warning("chat_question_callback_missing_ids", data=data)
 return None
 if not answer:
 logger.warning("chat_question_callback_missing_answer", data=data)
 return None
 logger.info(
 "chat_question_answered",
 execution_id=execution_id,
 node_id=node_id,
 answer_preview=answer[:50],
 )
 _schedule_chat_answer_completion(
 execution_id=execution_id,
 node_id=node_id,
 answer=answer,
 responder_id=callback.user_open_id,
 )
 # 获取问题信息用于更新卡片
 question = _get_question_from_node(execution_id, node_id)
 return build_chat_answered_card(
 question=question,
 answer=answer,
 responder_name="群成员",
 )
def _extract_callback_data(callback: CardCallback) -> dict[str, Any]:
 """从 callback 的 action_value 提取数据字典。
 action_value 可能是 dict（CardCallbackView 已解析）或 JSON 字符串。
 Args:
 callback: 卡片回调数据
 Returns:
 解析后的数据字典，或空字典
 """
 action_value = callback.action_value
 if isinstance(action_value, dict):
 return action_value
 elif isinstance(action_value, str):
 try:
 data = json.loads(action_value)
 return data if isinstance(data, dict) else {}
 except json.JSONDecodeError:
 return {}
 return {}
def _get_question_from_node(execution_id: str, node_id: str) -> str:
 """从 NodeExecution 的 output_data 获取当前问题文本。
 Args:
 execution_id: 工作流执行 ID
 node_id: 节点 ID
 Returns:
 问题文本，获取失败时返回默认值
 """
 try:
 node_execution = NodeExecution.objects.filter(
 workflow_execution_id=execution_id,
 node_id=node_id,
 ).first
 if not node_execution:
 return "提问"
 output_data = node_execution.output_data or {}
 question: str = output_data.get("question", "提问")
 return question
 except Exception as e:
 logger.warning("get_question_from_node_failed", error=str(e))
 return "提问"
def _schedule_chat_answer_completion(
 execution_id: str,
 node_id: str,
 answer: str,
 responder_id: str,
) -> None:
 """在后台线程异步完成群聊回答处理。
 复用 approval_callback 的 _run_in_thread 模式，
 避免阻塞飞书回调（必须 3 秒内响应）。
 首次回复即恢复工作流，后续回复被忽略（通过检查 node_execution 状态）。
 Args:
 execution_id: 工作流执行 ID
 node_id: 节点 ID
 answer: 用户回答内容
 responder_id: 回复者的飞书 open_id
 """
 async def _do_answer -> None:
 from workflows.models.execution import ExecutionStatus
 try:
 # 查找处于等待状态的 NodeExecution
 node_execution = await NodeExecution.objects.filter(
 workflow_execution_id=execution_id,
 node_id=node_id,
 status=NodeExecutionStatus.WAITING_EVENT,
 ).select_related("workflow_execution").afirst
 if not node_execution:
 # 已被其他回复处理或状态不符，忽略
 logger.info(
 "chat_answer_ignored_not_waiting",
 execution_id=execution_id,
 node_id=node_id,
 )
 return
 # 恢复 workflow_execution 为 RUNNING
 workflow_execution = node_execution.workflow_execution
 if workflow_execution.status == ExecutionStatus.SUSPENDED:
 workflow_execution.status = ExecutionStatus.RUNNING
 await workflow_execution.asave(update_fields=["status"])
 engine = WorkflowEngine
 # 构造简单的回复者对象
 class _FeishuResponder:
 def __init__(self, open_id: str) -> None:
 self.id = open_id
 self.username = f"feishu:{open_id}"
 def __str__(self) -> str:
 return self.username
 responder = _FeishuResponder(responder_id)
 await engine.approve_node(node_execution, responder, answer)
 logger.info(
 "chat_answer_completion_done",
 execution_id=execution_id,
 node_id=node_id,
 )
 except Exception as e:
 logger.exception(
 "chat_answer_completion_error",
 execution_id=execution_id,
 node_id=node_id,
 error=str(e),
 )
 _run_in_thread(_do_answer)
