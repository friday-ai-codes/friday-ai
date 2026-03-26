"""Built-in lifecycle hooks."""
from typing import Any
import structlog
from workflows.hooks.base import BaseHook
from workflows.models.execution import NodeExecution, WorkflowExecution
logger = structlog.get_logger
class LoggingHook(BaseHook):
 """日志钩子"""
 priority = 1 # 最先执行
 async def execute(self, event: str, **kwargs) -> None:
 execution = kwargs.get("execution")
 node_execution = kwargs.get("node_execution")
 log_data = {"workflow_event_type": event}
 if execution:
 log_data["execution_id"] = str(execution.id)
 exe = await WorkflowExecution.objects.select_related("workflow").aget(id=execution.id)
 log_data["workflow"] = exe.workflow.name
 if node_execution:
 ne = await NodeExecution.objects.select_related("node").aget(id=node_execution.id)
 log_data["node_id"] = str(ne.node.id)
 log_data["node_name"] = ne.node.name
 logger.info("工作流事件", **log_data)
class WebSocketBroadcastHook(BaseHook):
 """WebSocket 广播钩子"""
 priority = 10
 async def execute(self, event: str, **kwargs) -> None:
 execution = kwargs.get("execution")
 if not execution:
 return
 try:
 from channels.layers import get_channel_layer
 channel_layer = get_channel_layer
 if not channel_layer:
 return
 message = {
 "type": "workflow.event",
 "event": event,
 "execution_id": str(execution.id),
 "status": execution.status,
 }
 node_execution = kwargs.get("node_execution")
 if node_execution:
 message["node_id"] = str(node_execution.node_id)
 message["node_status"] = node_execution.status
 # 调试暂停事件：附带节点输入输出数据供前端展示
 if event == "node_debug_paused":
 message["node_input"] = node_execution.input_data or {}
 message["node_output"] = node_execution.output_data or {}
 await channel_layer.group_send(
 f"execution_{execution.id}",
 message,
 )
 except ImportError:
 # channels not installed
 pass
class NotificationHook(BaseHook):
 """通知钩子"""
 priority = 50
 NOTIFY_EVENTS = [
 "execution_completed",
 "execution_failed",
 "node_waiting_approval",
 ]
 async def execute(self, event: str, **kwargs) -> None:
 if event not in self.NOTIFY_EVENTS:
 return
 execution = kwargs.get("execution")
 if not execution:
 logger.info("notification_skipped", workflow_event=event, reason="missing_execution")
 return
 execution_id = str(getattr(execution, "id", "unknown"))
 if getattr(execution, "is_debug", False):
 logger.info(
 "notification_skipped",
 workflow_event=event,
 execution_id=execution_id,
 reason="debug_execution",
 )
 return
 chat_id = self._get_chat_id(execution)
 if not chat_id:
 logger.info(
 "notification_skipped",
 workflow_event=event,
 execution_id=execution_id,
 reason="missing_chat_id",
 )
 return
 try:
 from services.feishu_im import FeishuIMService
 project = self._get_project(execution)
 im_service = await FeishuIMService.create(project)
 card = self._build_card(event, execution=execution, node_execution=kwargs.get("node_execution"))
 message_id = await im_service.send_card(
 receive_id=chat_id,
 receive_id_type="chat_id",
 card=card,
 )
 if message_id:
 execution.feishu_message_id = message_id
 await execution.asave(update_fields=["feishu_message_id"])
 logger.info(
 "notification_sent",
 workflow_event=event,
 execution_id=execution_id,
 message_id=message_id,
 )
 except Exception:
 logger.warning(
 "notification_failed",
 workflow_event=event,
 execution_id=execution_id,
 exc_info=True,
 )
 def _get_chat_id(self, execution: WorkflowExecution | Any) -> str | None:
 context = getattr(execution, "context", None) or {}
 chat_id = context.get("chat_id") if isinstance(context, dict) else None
 if chat_id:
 return chat_id
 input_data = getattr(execution, "input_data", None) or {}
 return input_data.get("chat_id") if isinstance(input_data, dict) else None
 def _get_project(self, execution: WorkflowExecution | Any) -> Any:
 workflow = getattr(execution, "workflow", None)
 workflow_project = getattr(workflow, "project", None)
 if workflow_project is not None:
 return workflow_project
 return getattr(execution, "project", None)
 def _build_card(
 self,
 event: str,
 *,
 execution: WorkflowExecution | Any,
 node_execution: NodeExecution | Any | None = None,
 ) -> dict[str, Any]:
 if event == "execution_completed":
 color = "green"
 content = "工作流执行完成"
 elif event == "execution_failed":
 color = "red"
 error_message = getattr(execution, "error_message", "") or "未知错误"
 content = f"工作流执行失败\n错误: {str(error_message)[:500]}"
 else:
 color = "orange"
 node_name = "审批节点"
 description = "请审批"
 if node_execution is not None:
 node = getattr(node_execution, "node", None)
 node_name = getattr(node, "name", node_name) or node_name
 node_config = getattr(node, "config", None) or {}
 if isinstance(node_config, dict):
 description = node_config.get("description_template") or description
 content = (
 f"等待审批: {node_name}\n\n"
 f"{description}\n\n"
 "回复「通过」或「驳回」进行审批"
 )
 return {
 "config": {"wide_screen_mode": True},
 "header": {
 "title": {"tag": "plain_text", "content": "工作流通知"},
 "template": color,
 },
 "elements": [{"tag": "markdown", "content": content}],
 }
