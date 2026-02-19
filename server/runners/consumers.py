"""Runner WebSocket consumer。"""
import asyncio
import uuid
import structlog
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import close_old_connections
from django.utils import timezone
logger = structlog.get_logger
_close_old_connections = database_sync_to_async(close_old_connections)
# 终态集合
_TERMINAL_STATUSES = {"completed", "error", "timeout", "cancelled"}
class RunnerConsumer(AsyncJsonWebsocketConsumer):
 """处理 Runner WS 连接，按 type 分发消息到 handler。"""
 _handlers: dict[str, str] = {
 "runner.hello": "_handle_hello",
 "runner.heartbeat": "_handle_heartbeat",
 "task.accepted": "_handle_task_accepted",
 "task.completed": "_handle_task_completed",
 "task.failed": "_handle_task_failed",
 "task.question": "_handle_task_question",
 "task.token_usage": "_handle_task_token_usage",
 "task.log": "_handle_task_log",
 "task.progress": "_handle_task_progress",
 "tool.call": "_handle_tool_call",
 }
 async def connect(self):
 runner = self.scope.get("runner")
 if not runner:
 await self.close(code=4001)
 return
 self.runner = runner
 self.group_name = f"runner_{runner.id}"
 self._heartbeat_count = 0
 # 踢旧连接
 if runner.channel_name:
 await self.channel_layer.send(
 runner.channel_name, {"type": "force.disconnect"}
 )
 await self.channel_layer.group_add(self.group_name, self.channel_name)
 await self.accept
 await self._update_channel_name(self.channel_name)
 async def disconnect(self, close_code):
 if hasattr(self, "group_name"):
 await self.channel_layer.group_discard(self.group_name, self.channel_name)
 if hasattr(self, "runner") and close_code != 4002:
 await self._mark_offline
 await _broadcast_monitor_event(
 self.channel_layer, "runner.status_changed", self.runner.id, {"status": "offline"}
 )
 await database_sync_to_async(_log_runner_event)(self.runner.id, "disconnected")
 async def receive_json(self, content, **kwargs):
 msg_type = content.get("type")
 handler_name = self._handlers.get(msg_type) if msg_type else None
 if handler_name:
 await getattr(self, handler_name)(content)
 else:
 logger.warning("unknown_message_type", type=msg_type)
 # -- message handlers --
 async def _handle_hello(self, content):
 payload = content.get("payload", {})
 await _close_old_connections
 await database_sync_to_async(self._sync_update_hello)(payload)
 await _broadcast_monitor_event(
 self.channel_layer, "runner.status_changed", self.runner.id,
 {"status": "online", "name": self.runner.name, "version": payload.get("version", "")},
 )
 await database_sync_to_async(_log_runner_event)(
 self.runner.id, "connected", {"version": payload.get("version", "")}
 )
 # 触发分发器检查待分发队列
 from runners.dispatcher import get_dispatcher
 await get_dispatcher.on_runner_online(self.runner.id)
 async def _handle_heartbeat(self, content):
 payload = content.get("payload", {})
 await _close_old_connections
 await database_sync_to_async(self._sync_update_heartbeat)(payload)
 self._heartbeat_count += 1
 if self._heartbeat_count % 10 == 0:
 await _broadcast_monitor_event(
 self.channel_layer, "runner.status_changed", self.runner.id,
 {"status": "online", "current_tasks": payload.get("current_tasks", 0)},
 )
 await database_sync_to_async(_log_runner_event)(
 self.runner.id, "heartbeat", {"current_tasks": payload.get("current_tasks", 0)}
 )
 async def _handle_task_accepted(self, content):
 payload = content.get("payload", {})
 task_id = payload.get("task_id", "")
 answer_endpoint = payload.get("answer_endpoint", "")
 logger.info("task_accepted", runner=str(self.runner.id), task_id=task_id)
 if answer_endpoint and task_id:
 await _close_old_connections
 await database_sync_to_async(self._sync_store_answer_endpoint)(
 task_id, answer_endpoint
 )
 await _broadcast_monitor_event(
 self.channel_layer, "task.status_changed", self.runner.id,
 {"task_id": task_id, "status": "running"},
 )
 await database_sync_to_async(self._sync_update_assignment_status)(task_id, "running")
 async def _handle_task_completed(self, content):
 payload = content.get("payload", {})
 task_id = payload.get("task_id", "")
 log = logger.bind(runner=str(self.runner.id), task_id=task_id)
 await _close_old_connections
 await database_sync_to_async(self._sync_handle_completed)(payload, log)
 await _broadcast_monitor_event(
 self.channel_layer, "task.status_changed", self.runner.id,
 {"task_id": task_id, "status": "completed"},
 )
 await database_sync_to_async(self._sync_update_assignment_status)(task_id, "completed")
 await database_sync_to_async(_log_runner_event)(
 self.runner.id, "task_completed", {"task_id": task_id}
 )
 async def _handle_task_failed(self, content):
 payload = content.get("payload", {})
 task_id = payload.get("task_id", "")
 log = logger.bind(runner=str(self.runner.id), task_id=task_id)
 await _close_old_connections
 await database_sync_to_async(self._sync_handle_failed)(payload, log)
 await _broadcast_monitor_event(
 self.channel_layer, "task.status_changed", self.runner.id,
 {"task_id": task_id, "status": "failed"},
 )
 await database_sync_to_async(self._sync_update_assignment_status)(task_id, "failed")
 await database_sync_to_async(_log_runner_event)(
 self.runner.id, "task_failed", {"task_id": task_id, "error": payload.get("error", "")}
 )
 async def _handle_task_question(self, content):
 payload = content.get("payload", {})
 task_id = payload.get("task_id", "")
 log = logger.bind(runner=str(self.runner.id), task_id=task_id)
 await _close_old_connections
 result = await database_sync_to_async(self._sync_create_question)(payload)
 if result:
 session, question_id = result
 from subagent.question_handler import send_question_card_enhanced
 message_id = await send_question_card_enhanced(
 session=session,
 question=payload.get("question", ""),
 options=payload.get("options", ),
 context=payload.get("context", ""),
 code_snippet=payload.get("code_snippet", ""),
 question_id=question_id,
 )
 if message_id:
 await database_sync_to_async(self._sync_update_feishu_message_id)(
 question_id, message_id
 )
 log.info("task_question_via_ws", question_id=question_id)
 async def _handle_task_token_usage(self, content):
 payload = content.get("payload", {})
 task_id = payload.get("task_id", "")
 log = logger.bind(runner=str(self.runner.id), task_id=task_id)
 await _close_old_connections
 await database_sync_to_async(self._sync_handle_token_usage)(payload, log)
 async def _handle_task_log(self, content):
 payload = content.get("payload", {})
 logger.debug(
 "task_log",
 runner=str(self.runner.id),
 task_id=payload.get("task_id", ""),
 message=payload.get("message", ""),
 )
 async def _handle_task_progress(self, content):
 payload = content.get("payload", {})
 task_id = payload.get("task_id", "")
 await _close_old_connections
 await database_sync_to_async(self._sync_handle_progress)(task_id, payload)
 async def _handle_tool_call(self, content):
 payload = content.get("payload", {})
 call_id = payload.get("call_id", "")
 tool_name = payload.get("tool_name", "")
 arguments = payload.get("arguments", {})
 from tools.executor import execute_tool
 result = await execute_tool(tool_name, arguments)
 await self.send_json({
 "type": "tool.result",
 "payload": {"call_id": call_id, "result": result},
 })
 # -- channel layer events --
 async def runner_message(self, event):
 """Channel layer 事件：向 Runner 发送消息。"""
 await self.send_json(event["message"])
 async def force_disconnect(self, event):
 """收到踢连接指令。"""
 await self.close(code=4002)
 # -- sync ORM helpers (called via database_sync_to_async) --
 def _sync_update_hello(self, payload: dict) -> None:
 r = self.runner
 r.status = "online"
 r.version = payload.get("version", "")
 r.save(update_fields=["status", "version", "updated_at"])
 def _sync_update_heartbeat(self, payload: dict) -> None:
 r = self.runner
 r.status = "online"
 r.last_heartbeat = timezone.now
 r.current_tasks = payload.get("current_tasks", r.current_tasks)
 r.save(update_fields=["status", "last_heartbeat", "current_tasks", "updated_at"])
 def _sync_store_answer_endpoint(self, session_id: str, answer_endpoint: str) -> None:
 from subagent.models import SubAgentSession
 session = SubAgentSession.objects.filter(session_id=session_id).first
 if session:
 output = session.last_output or {}
 output["answer_endpoint"] = answer_endpoint
 session.last_output = output
 session.save(update_fields=["last_output", "updated_at"])
 def _sync_handle_completed(self, payload: dict, log: structlog.stdlib.BoundLogger) -> None:
 from subagent.api.callbacks import _schedule_agent_loop_resume, _schedule_workflow_resume
 from subagent.models import SubAgentSession, TaskResult
 task_id = payload.get("task_id", "")
 session = SubAgentSession.objects.filter(session_id=task_id).first
 if not session or session.status in _TERMINAL_STATUSES:
 log.warning("completed_session_not_found_or_terminal", status=getattr(session, "status", None))
 return
 if not TaskResult.objects.filter(session=session).exists:
 TaskResult.objects.create(
 session=session,
 result_type=payload.get("result_type", "text"),
 text_output=payload.get("text_output", ""),
 branch_name=payload.get("branch_name", ""),
 commit_sha=payload.get("commit_sha", ""),
 modified_files=payload.get("modified_files", ),
 raw_output=payload.get("output", {}),
 duration_ms=payload.get("duration_ms"),
 )
 session.mark_completed
 _schedule_workflow_resume(session, log)
 _schedule_agent_loop_resume(session, log)
 log.info("task_completed_via_ws")
 def _sync_handle_failed(self, payload: dict, log: structlog.stdlib.BoundLogger) -> None:
 from subagent.api.callbacks import (
 _schedule_agent_loop_resume,
 _schedule_workflow_resume,
 _send_failure_notification,
 )
 from subagent.models import SubAgentSession
 task_id = payload.get("task_id", "")
 session = SubAgentSession.objects.filter(session_id=task_id).first
 if not session or session.status in _TERMINAL_STATUSES:
 log.warning("failed_session_not_found_or_terminal", status=getattr(session, "status", None))
 return
 error_msg = payload.get("error", "Unknown error")
 session.failure_reason = error_msg
 session.save(update_fields=["failure_reason"])
 session.mark_failed(error=error_msg)
 _send_failure_notification(session, error_msg)
 _schedule_workflow_resume(session, log)
 _schedule_agent_loop_resume(session, log)
 log.info("task_failed_via_ws")
 def _sync_create_question(self, payload: dict) -> tuple | None:
 from subagent.models import InteractionLog, SubAgentSession
 task_id = payload.get("task_id", "")
 session = SubAgentSession.objects.filter(session_id=task_id).first
 if not session:
 logger.warning("question_session_not_found", task_id=task_id)
 return None
 question_id = f"q-{uuid.uuid4.hex[:12]}"
 InteractionLog.objects.create(
 session=session,
 question_id=question_id,
 question_text=payload.get("question", ""),
 question_context=payload.get("context", ""),
 code_snippet=payload.get("code_snippet", ""),
 options=payload.get("options", ),
 )
 # 存储 pending_question 到 last_output
 session.last_output = {
 **(session.last_output or {}),
 "pending_question": {
 "question_id": question_id,
 "question": payload.get("question", ""),
 "options": payload.get("options", ),
 "asked_at": timezone.now.isoformat,
 },
 }
 session.save(update_fields=["last_output", "updated_at"])
 return session, question_id
 def _sync_update_feishu_message_id(self, question_id: str, message_id: str) -> None:
 from subagent.models import InteractionLog
 InteractionLog.objects.filter(question_id=question_id).update(
 feishu_message_id=message_id
 )
 def _sync_handle_token_usage(self, payload: dict, log: structlog.stdlib.BoundLogger) -> None:
 from subagent.models import SubAgentSession, TokenUsage
 task_id = payload.get("task_id", "")
 session = SubAgentSession.objects.filter(session_id=task_id).first
 if not session:
 log.warning("token_usage_session_not_found", task_id=task_id)
 return
 TokenUsage.objects.create(
 session=session,
 input_tokens=payload.get("input_tokens", 0),
 output_tokens=payload.get("output_tokens", 0),
 cache_read_tokens=payload.get("cache_read_tokens", 0),
 cache_write_tokens=payload.get("cache_write_tokens", 0),
 model=payload.get("model", ""),
 total_cost_usd=payload.get("total_cost_usd", 0),
 source=TokenUsage.Source.SUBAGENT,
 )
 log.debug("token_usage_recorded_via_ws")
 def _sync_handle_progress(self, task_id: str, payload: dict) -> None:
 from subagent.models import SubAgentSession
 session = SubAgentSession.objects.filter(session_id=task_id).first
 if not session:
 return
 session.last_output = {
 **(session.last_output or {}),
 "progress": {
 "phase": payload.get("phase", ""),
 "progress": payload.get("progress", 0.0),
 "message": payload.get("message", ""),
 "updated_at": timezone.now.isoformat,
 },
 }
 session.save(update_fields=["last_output", "updated_at"])
 def _sync_update_assignment_status(self, session_id: str, status: str) -> None:
 from runners.models import RunnerTaskAssignment
 updates: dict[str, object] = {"status": status}
 if status in ("completed", "failed"):
 updates["completed_at"] = timezone.now
 RunnerTaskAssignment.objects.filter(
 runner=self.runner, session__session_id=session_id, status__in=["assigned", "running"]
 ).update(**updates)
 async def _update_channel_name(self, channel_name: str):
 await _close_old_connections
 @database_sync_to_async
 def _save:
 self.runner.channel_name = channel_name
 self.runner.save(update_fields=["channel_name", "updated_at"])
 await _save
 async def _mark_offline(self):
 await _close_old_connections
 @database_sync_to_async
 def _save:
 self.runner.status = "offline"
 self.runner.channel_name = ""
 self.runner.save(update_fields=["status", "channel_name", "updated_at"])
 await _save
# ---------------------------------------------------------------------------
# Monitor WebSocket — 前端实时监控
# ---------------------------------------------------------------------------
MONITOR_GROUP = "runner_monitor"
AUTH_TIMEOUT = 5
async def _broadcast_monitor_event(
 channel_layer: object, event_type: str, runner_id: uuid.UUID, data: dict
) -> None:
 await channel_layer.group_send(MONITOR_GROUP, { # type: ignore[attr-defined]
 "type": "monitor.event",
 "data": {"event": event_type, "runner_id": str(runner_id), "data": data},
 })
def _log_runner_event(runner_id: uuid.UUID, event_type: str, detail: dict | None = None) -> None:
 from runners.models import RunnerEvent
 RunnerEvent.objects.create(runner_id=runner_id, event_type=event_type, detail=detail or {})
class MonitorConsumer(AsyncJsonWebsocketConsumer):
 """前端监控 WebSocket，首条消息 JWT 认证，接收 runner/task 事件。"""
 async def connect(self) -> None:
 self.authenticated = False
 await self.accept
 self._auth_timeout = asyncio.ensure_future(self._auth_timeout_handler)
 async def _auth_timeout_handler(self) -> None:
 await asyncio.sleep(AUTH_TIMEOUT)
 if not self.authenticated:
 await self.close(code=4001)
 async def disconnect(self, close_code: int) -> None:
 if hasattr(self, "_auth_timeout"):
 self._auth_timeout.cancel
 if self.authenticated:
 await self.channel_layer.group_discard(MONITOR_GROUP, self.channel_name)
 async def receive_json(self, content: dict, **kwargs) -> None: # type: ignore[override]
 if content.get("type") == "auth":
 await self._handle_auth(content)
 async def _handle_auth(self, content: dict) -> None:
 try:
 from rest_framework_simplejwt.tokens import AccessToken
 token = AccessToken(content.get("token", ""))
 user_id = token["sub"]
 from django.contrib.auth import get_user_model
 await database_sync_to_async(get_user_model.objects.get)(id=user_id)
 except Exception:
 await self.send_json({"type": "auth", "status": "error", "detail": "Invalid token"})
 await self.close(code=4003)
 return
 if not self.authenticated:
 self.authenticated = True
 self._auth_timeout.cancel
 await self.channel_layer.group_add(MONITOR_GROUP, self.channel_name)
 await self.send_json({"type": "auth", "status": "ok"})
 async def monitor_event(self, event: dict) -> None:
 """Channel layer handler — 转发事件到前端。"""
 await self.send_json(event["data"])
