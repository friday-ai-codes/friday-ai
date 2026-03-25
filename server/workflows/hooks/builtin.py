"""Built-in lifecycle hooks."""
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
 return
 raise NotImplementedError("通知发送逻辑未实现")
