"""WebSocket consumers for workflows app."""
import json
import structlog
from channels.generic.websocket import AsyncWebsocketConsumer
logger = structlog.get_logger
class WorkflowExecutionConsumer(AsyncWebsocketConsumer):
 """Consumer for workflow execution updates.
 Clients connect to: /ws/workflow-executions/{execution_id}/
 """
 async def connect(self) -> None:
 self.execution_id = self.scope["url_route"]["kwargs"]["execution_id"] # type: ignore[typeddict-item]
 self.group_name = f"execution_{self.execution_id}"
 # Join execution group
 await self.channel_layer.group_add(self.group_name, self.channel_name)
 await self.accept
 async def disconnect(self, close_code: int) -> None:
 # Leave execution group
 await self.channel_layer.group_discard(self.group_name, self.channel_name)
 # 调试会话清理：WS 断线时释放暂停并标记取消
 from workflows.engine.scheduler import _debug_sessions
 session = _debug_sessions.pop(self.execution_id, None)
 if session:
 session.debug_action = "cancel"
 session.loop.call_soon_threadsafe(session.event.set)
 logger.info("debug_session_ws_disconnect_cleanup", execution_id=self.execution_id)
 async def receive(self, text_data: str) -> None:
 """处理前端调试控制命令。"""
 data = json.loads(text_data)
 msg_type = data.get("type")
 if msg_type == "debug_action":
 action = data.get("action")
 if action not in ("release", "skip", "mock"):
 await self.send(text_data=json.dumps({
 "type": "error",
 "message": f"未知调试操作: {action}",
 }))
 return
 from workflows.engine.scheduler import WorkflowEngine
 success = WorkflowEngine.release_debug_node(
 execution_id=self.execution_id,
 action=action,
 action_data=data.get("data", {}),
 )
 if not success:
 await self.send(text_data=json.dumps({
 "type": "error",
 "message": "调试会话不存在或已结束",
 }))
 else:
 await self.send(text_data=json.dumps({
 "type": "debug_action_ack",
 "action": action,
 }))
 async def workflow_event(self, event: dict) -> None:
 """Handle workflow event message from group."""
 # Send message to WebSocket
 await self.send(text_data=json.dumps(event))
