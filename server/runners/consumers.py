"""Runner WebSocket consumer。"""
import asyncio
import uuid
import structlog
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone
logger = structlog.get_logger
# 终态集合
_TERMINAL_STATUSES = {"completed", "error", "timeout", "cancelled"}
# 断连超时（秒）：5 分钟后未重连则标记任务失败
DISCONNECT_TIMEOUT = 300
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
 "task.rejected": "_handle_task_rejected",
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
 await self.channel_layer.send(runner.channel_name, {"type": "force.disconnect"})
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
 await _alog_runner_event(self.runner.id, "disconnected")
 # 启动断连超时处理：5 分钟后检查是否重连
 _schedule_disconnect_timeout(self.runner.id)
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
 await self._update_hello(payload)
 await _broadcast_monitor_event(
 self.channel_layer,
 "runner.status_changed",
 self.runner.id,
 {"status": "online", "name": self.runner.name, "version": payload.get("version", "")},
 )
 await _alog_runner_event(
 self.runner.id, "connected", {"version": payload.get("version", "")}
 )
 # 重连时恢复未完成任务关联
 await self._recover_pending_tasks
 # 触发分发器检查待分发队列
 from runners.dispatcher import get_dispatcher
 await get_dispatcher.on_runner_online(self.runner.id)
 async def _handle_heartbeat(self, content):
 payload = content.get("payload", {})
 await self._update_heartbeat(payload)
 self._heartbeat_count += 1
 # 每次心跳记录详细指标到 RunnerEvent（支持趋势查看）
 _METRIC_KEYS = (
 "cpu_percent",
 "mem_percent",
 "mem_total_mb",
 "mem_used_mb",
 "disk_percent",
 "disk_total_gb",
 "disk_used_gb",
 "current_tasks",
 "max_concurrent",
 "accepting",
 )
 detail = {k: payload[k] for k in _METRIC_KEYS if k in payload}
 await _alog_runner_event(self.runner.id, "heartbeat", detail)
 # 每 10 次广播到前端监控（避免 WS 消息过多）
 if self._heartbeat_count % 10 == 0:
 await _broadcast_monitor_event(
 self.channel_layer,
 "runner.status_changed",
 self.runner.id,
 {"status": "online", "current_tasks": payload.get("current_tasks", 0)},
 )
 async def _handle_task_accepted(self, content):
 payload = content.get("payload", {})
 task_id = payload.get("task_id", "")
 logger.info("task_accepted", runner=str(self.runner.id), task_id=task_id)
 if answer_endpoint:= payload.get("answer_endpoint", ""):
 if task_id:
 await self._store_answer_endpoint(task_id, answer_endpoint)
 await _broadcast_monitor_event(
 self.channel_layer,
 "task.status_changed",
 self.runner.id,
 {"task_id": task_id, "status": "running"},
 )
 await self._update_assignment_status(task_id, "running")
 async def _handle_task_completed(self, content):
 payload = content.get("payload", {})
 task_id = payload.get("task_id", "")
 log = logger.bind(runner=str(self.runner.id), task_id=task_id)
 await self._handle_completed(payload, log)
 await _broadcast_monitor_event(
 self.channel_layer,
 "task.status_changed",
 self.runner.id,
 {"task_id": task_id, "status": "completed"},
 )
 await self._update_assignment_status(task_id, "completed")
 await _alog_runner_event(self.runner.id, "task_completed", {"task_id": task_id})
 async def _handle_task_failed(self, content):
 payload = content.get("payload", {})
 task_id = payload.get("task_id", "")
 log = logger.bind(runner=str(self.runner.id), task_id=task_id)
 await self._handle_failed(payload, log)
 await _broadcast_monitor_event(
 self.channel_layer,
 "task.status_changed",
 self.runner.id,
 {"task_id": task_id, "status": "failed"},
 )
 await self._update_assignment_status(task_id, "failed")
 await _alog_runner_event(
 self.runner.id, "task_failed", {"task_id": task_id, "error": payload.get("error", "")}
 )
 async def _handle_task_question(self, content):
 payload = content.get("payload", {})
 task_id = payload.get("task_id", "")
 log = logger.bind(runner=str(self.runner.id), task_id=task_id)
 result = await self._create_question(payload)
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
 await self._update_feishu_message_id(question_id, message_id)
 log.info("task_question_via_ws", question_id=question_id)
 async def _handle_task_token_usage(self, content):
 payload = content.get("payload", {})
 task_id = payload.get("task_id", "")
 log = logger.bind(runner=str(self.runner.id), task_id=task_id)
 await self._handle_token_usage(payload, log)
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
 await self._handle_progress(task_id, payload)
 async def _handle_task_rejected(self, content):
 payload = content.get("payload", {})
 task_id = payload.get("task_id", "")
 reason = payload.get("reason", "")
 logger.info("task_rejected", runner=str(self.runner.id), task_id=task_id, reason=reason)
 dispatch_task = await self._rebuild_dispatch_task(task_id)
 if dispatch_task:
 from runners.dispatcher import get_dispatcher
 await get_dispatcher.on_task_rejected(task_id, dispatch_task)
 await self._update_assignment_status(task_id, "rejected")
 async def _handle_tool_call(self, content):
 payload = content.get("payload", {})
 call_id = payload.get("call_id", "")
 tool_name = payload.get("tool_name", "")
 arguments = payload.get("arguments", {})
 from tools.executor import execute_tool
 result = await execute_tool(tool_name, arguments)
 await self.send_json(
 {
 "type": "tool.result",
 "payload": {"call_id": call_id, "result": result},
 }
 )
 # -- channel layer events --
 async def runner_message(self, event):
 """Channel layer 事件：向 Runner 发送消息。"""
 await self.send_json(event["message"])
 async def force_disconnect(self, event):
 """收到踢连接指令。"""
 await self.close(code=4002)
 # -- async ORM helpers --
 async def _update_hello(self, payload: dict) -> None:
 r = self.runner
 r.status = "online"
 r.version = payload.get("version", "")
 await r.asave(update_fields=["status", "version", "updated_at"])
 async def _update_heartbeat(self, payload: dict) -> None:
 r = self.runner
 r.status = "online"
 r.last_heartbeat = timezone.now
 r.current_tasks = payload.get("current_tasks", r.current_tasks)
 await r.asave(update_fields=["status", "last_heartbeat", "current_tasks", "updated_at"])
 async def _store_answer_endpoint(self, session_id: str, answer_endpoint: str) -> None:
 from subagent.models import SubAgentSession
 session = await SubAgentSession.objects.filter(session_id=session_id).afirst
 if session:
 output = session.last_output or {}
 output["answer_endpoint"] = answer_endpoint
 session.last_output = output
 await session.asave(update_fields=["last_output", "updated_at"])
 async def _handle_completed(self, payload: dict, log: structlog.stdlib.BoundLogger) -> None:
 from subagent.api.callbacks import _schedule_agent_session_resume, _schedule_workflow_resume
 from subagent.models import SubAgentSession, TaskResult
 task_id = payload.get("task_id", "")
 session = await SubAgentSession.objects.filter(session_id=task_id).afirst
 if not session or session.status in _TERMINAL_STATUSES:
 log.warning(
 "completed_session_not_found_or_terminal", status=getattr(session, "status", None)
 )
 return
 if not await TaskResult.objects.filter(session=session).aexists:
 await TaskResult.objects.acreate(
 session=session,
 result_type=payload.get("result_type", "text"),
 text_output=payload.get("text_output", ""),
 branch_name=payload.get("branch_name", ""),
 commit_sha=payload.get("commit_sha", ""),
 modified_files=payload.get("modified_files", ),
 raw_output=payload.get("output", {}),
 duration_ms=payload.get("duration_ms"),
 )
 await session.amark_completed
 _schedule_workflow_resume(session, log)
 _schedule_agent_session_resume(session, log)
 log.info("task_completed_via_ws")
 async def _handle_failed(self, payload: dict, log: structlog.stdlib.BoundLogger) -> None:
 from subagent.api.callbacks import (
 _schedule_agent_session_resume,
 _schedule_workflow_resume,
 _send_failure_notification,
 )
 from subagent.models import SubAgentSession
 task_id = payload.get("task_id", "")
 session = await SubAgentSession.objects.filter(session_id=task_id).afirst
 if not session or session.status in _TERMINAL_STATUSES:
 log.warning(
 "failed_session_not_found_or_terminal", status=getattr(session, "status", None)
 )
 return
 error_msg = payload.get("error", "Unknown error")
 session.failure_reason = error_msg
 await session.asave(update_fields=["failure_reason"])
 await session.amark_failed(error=error_msg)
 await _send_failure_notification(session, error_msg)
 _schedule_workflow_resume(session, log)
 _schedule_agent_session_resume(session, log)
 log.info("task_failed_via_ws")
 async def _create_question(self, payload: dict) -> tuple | None:
 from subagent.models import InteractionLog, SubAgentSession
 task_id = payload.get("task_id", "")
 session = await SubAgentSession.objects.filter(session_id=task_id).afirst
 if not session:
 logger.warning("question_session_not_found", task_id=task_id)
 return None
 question_id = f"q-{uuid.uuid4.hex[:12]}"
 await InteractionLog.objects.acreate(
 session=session,
 question_id=question_id,
 question_text=payload.get("question", ""),
 question_context=payload.get("context", ""),
 code_snippet=payload.get("code_snippet", ""),
 options=payload.get("options", ),
 )
 session.last_output = {
 **(session.last_output or {}),
 "pending_question": {
 "question_id": question_id,
 "question": payload.get("question", ""),
 "options": payload.get("options", ),
 "asked_at": timezone.now.isoformat,
 },
 }
 await session.asave(update_fields=["last_output", "updated_at"])
 return session, question_id
 async def _update_feishu_message_id(self, question_id: str, message_id: str) -> None:
 from subagent.models import InteractionLog
 await InteractionLog.objects.filter(question_id=question_id).aupdate(
 feishu_message_id=message_id
 )
 async def _handle_token_usage(self, payload: dict, log: structlog.stdlib.BoundLogger) -> None:
 from subagent.models import SubAgentSession, TokenUsage
 task_id = payload.get("task_id", "")
 session = await SubAgentSession.objects.filter(session_id=task_id).afirst
 if not session:
 log.warning("token_usage_session_not_found", task_id=task_id)
 return
 await TokenUsage.objects.acreate(
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
 async def _handle_progress(self, task_id: str, payload: dict) -> None:
 from subagent.models import SubAgentSession
 session = await SubAgentSession.objects.filter(session_id=task_id).afirst
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
 await session.asave(update_fields=["last_output", "updated_at"])
 async def _rebuild_dispatch_task(self, session_id: str):
 from runners.dispatcher import DispatchTask
 from runners.models import RunnerTaskAssignment
 assignment = (
 await RunnerTaskAssignment.objects.filter(
 runner=self.runner, session__session_id=session_id
 )
 .select_related("session")
 .afirst
 )
 if not assignment or not assignment.session:
 return None
 session = assignment.session
 return DispatchTask(
 task_id=session.session_id,
 task_type=session.last_output.get("task_type", "coding")
 if session.last_output
 else "coding",
 tags=list(self.runner.tags),
 image="",
 repo_url="",
 branch="",
 target_branch="",
 prompt="",
 timeout=600,
 node_execution_id="",
 session_id=session.session_id,
 )
 async def _update_assignment_status(self, session_id: str, status: str) -> None:
 from runners.models import RunnerTaskAssignment
 updates: dict[str, object] = {"status": status}
 if status in ("completed", "failed", "rejected"):
 updates["completed_at"] = timezone.now
 await RunnerTaskAssignment.objects.filter(
 runner=self.runner, session__session_id=session_id, status__in=["assigned", "running"]
 ).aupdate(**updates)
 async def _update_channel_name(self, channel_name: str):
 self.runner.channel_name = channel_name
 await self.runner.asave(update_fields=["channel_name", "updated_at"])
 async def _mark_offline(self):
 self.runner.status = "offline"
 self.runner.channel_name = ""
 await self.runner.asave(update_fields=["status", "channel_name", "updated_at"])
 async def _recover_pending_tasks(self) -> None:
 """重连时恢复未完成任务关联。
 查询该 Runner 所有 assigned/running 状态的任务，
 对仍有效的任务重新发送 dispatch 消息。
 """
 from runners.models import RunnerTaskAssignment
 pending_assignments = RunnerTaskAssignment.objects.filter(
 runner=self.runner,
 status__in=["assigned", "running"],
 ).select_related("session")
 recovered_count = 0
 async for assignment in pending_assignments:
 session = assignment.session
 if not session or session.status in _TERMINAL_STATUSES:
 # 任务已在终态，标记 assignment 为 failed
 assignment.status = "failed"
 assignment.completed_at = timezone.now
 await assignment.asave(update_fields=["status", "completed_at"])
 continue
 # 重新分发任务
 dispatch_task = await self._rebuild_dispatch_task(session.session_id)
 if dispatch_task:
 from runners.dispatcher import get_dispatcher
 await get_dispatcher.dispatch(dispatch_task)
 recovered_count += 1
 if recovered_count > 0:
 logger.info(
 "runner_tasks_recovered",
 runner_id=str(self.runner.id),
 recovered_count=recovered_count,
 )
def _schedule_disconnect_timeout(runner_id: uuid.UUID) -> None:
 """启动断连超时处理。
 在后台线程中等待 DISCONNECT_TIMEOUT 秒后检查 Runner 是否仍离线。
 如果仍离线，将所有 assigned/running 状态的任务标记为 failed。
 """
 import threading
 def _timeout_handler -> None:
 loop = asyncio.new_event_loop
 asyncio.set_event_loop(loop)
 try:
 loop.run_until_complete(_handle_disconnect_timeout(runner_id))
 except Exception as e:
 logger.exception("disconnect_timeout_error", runner_id=str(runner_id), error=str(e))
 finally:
 loop.close
 timer = threading.Timer(DISCONNECT_TIMEOUT, _timeout_handler)
 timer.daemon = True
 timer.start
async def _handle_disconnect_timeout(runner_id: uuid.UUID) -> None:
 """断连超时处理：检查 Runner 是否仍离线，如果是则标记任务失败。"""
 from runners.models import Runner, RunnerTaskAssignment
 try:
 runner = await Runner.objects.aget(id=runner_id)
 except Runner.DoesNotExist:
 return
 # Runner 已重连，无需处理
 if runner.status == "online":
 logger.info("disconnect_timeout_runner_reconnected", runner_id=str(runner_id))
 return
 # Runner 仍离线，标记所有未完成任务为失败
 pending = RunnerTaskAssignment.objects.filter(
 runner_id=runner_id,
 status__in=["assigned", "running"],
 ).select_related("session")
 failed_count = 0
 async for assignment in pending:
 assignment.status = "failed"
 assignment.completed_at = timezone.now
 await assignment.asave(update_fields=["status", "completed_at"])
 failed_count += 1
 # 发送失败通知
 if assignment.session:
 try:
 from subagent.api.callbacks import _send_failure_notification
 await _send_failure_notification(
 assignment.session,
 f"Runner 断连超时（{DISCONNECT_TIMEOUT}秒），任务自动标记失败",
 )
 except Exception:
 logger.warning(
 "disconnect_timeout_notification_failed",
 session_id=assignment.session.session_id,
 )
 if failed_count > 0:
 logger.warning(
 "disconnect_timeout_tasks_failed",
 runner_id=str(runner_id),
 failed_count=failed_count,
 )
# ---------------------------------------------------------------------------
# Monitor WebSocket — 前端实时监控
# ---------------------------------------------------------------------------
MONITOR_GROUP = "runner_monitor"
AUTH_TIMEOUT = 5
async def _broadcast_monitor_event(
 channel_layer: object, event_type: str, runner_id: uuid.UUID, data: dict
) -> None:
 await channel_layer.group_send(
 MONITOR_GROUP,
 {
 "type": "monitor.event",
 "data": {"event": event_type, "runner_id": str(runner_id), "data": data},
 },
 )
async def _alog_runner_event(
 runner_id: uuid.UUID, event_type: str, detail: dict | None = None
) -> None:
 from runners.models import RunnerEvent
 await RunnerEvent.objects.acreate(
 runner_id=runner_id, event_type=event_type, detail=detail or {}
 )
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
 async def receive_json(self, content: dict, **kwargs) -> None:
 if content.get("type") == "auth":
 await self._handle_auth(content)
 async def _handle_auth(self, content: dict) -> None:
 try:
 from rest_framework_simplejwt.tokens import AccessToken
 token = AccessToken(content.get("token", ""))
 user_id = token["sub"]
 from django.contrib.auth import get_user_model
 await get_user_model.objects.aget(id=user_id)
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
