"""容器统一回调端点（Phase）。
POST /api/containers/callback/
容器 SubAgent 通过此端点上报状态变更：
- completed: 任务完成，创建 TaskResult
- failed: 任务失败，更新 session 状态
- heartbeat: 心跳，更新 last_heartbeat_at
- question: 提问，触发 Feishu 卡片
- progress: 进度更新，写入 last_output
"""
import asyncio
from datetime import timedelta
import structlog
from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from services.protocols import CallbackType
from subagent.models import SubAgentSession, TaskResult
from .serializers import (
 CallbackSerializer,
 CompletedPayloadSerializer,
 FailedPayloadSerializer,
 HeartbeatPayloadSerializer,
 ProgressPayloadSerializer,
 QuestionPayloadSerializer,
)
logger = structlog.get_logger
# 终态集合 — 处于终态的 session 不再接受回调
_TERMINAL_STATUSES = {
 SubAgentSession.Status.COMPLETED,
 SubAgentSession.Status.ERROR,
 SubAgentSession.Status.TIMEOUT,
 SubAgentSession.Status.CANCELLED,
}
# === 重试配置（Phase）===
# 可重试的任务类型（用户决策：explore/ask/plan 可重试，coding 不重试）
RETRYABLE_TASK_TYPES = {"explore", "ask", "plan"}
MAX_RETRIES = 2
RETRY_DELAYS = [30, 60] # 指数退避：30s -> 60s
# === 容器清理调度（Phase）===
def _schedule_container_cleanup(session: SubAgentSession, immediate: bool = False) -> None:
 """调度容器清理（异步，不阻塞回调响应）。
 Args:
 session: SubAgentSession 实例
 immediate: True=立即清理（成功任务），False=延迟 1 小时清理（失败任务）
 """
 log = logger.bind(session_id=session.session_id, immediate=immediate)
 if immediate:
 # 成功任务：立即清理
 asyncio.create_task(_cleanup_container_now(session))
 log.info("container_cleanup_scheduled_immediate")
 else:
 # 失败任务：标记 1 小时后清理
 cleanup_after = (timezone.now + timedelta(hours=1)).isoformat
 session.last_output = {
 **(session.last_output or {}),
 "cleanup_after": cleanup_after,
 }
 session.save(update_fields=["last_output", "updated_at"])
 log.info("container_cleanup_scheduled_delayed", cleanup_after=cleanup_after)
async def _cleanup_container_now(session: SubAgentSession) -> None:
 """立即清理容器和挂载卷。"""
 log = logger.bind(session_id=session.session_id)
 try:
 from services.container_manager import ContainerManager
 manager = ContainerManager
 if session.container_id:
 await manager.stop(session.session_id, force=False)
 log.info("container_cleaned")
 except Exception as e:
 log.warning("container_cleanup_error", error=str(e))
# === 失败通知（Phase）===
def _send_failure_notification(
 session: SubAgentSession,
 error_msg: str,
 retry_count: int = 0,
) -> None:
 """发送失败通知给任务触发者。
 通过飞书卡片通知用户任务失败。
 只通知任务触发者（用户决策）。
 """
 log = logger.bind(session_id=session.session_id)
 try:
 from feishu.cards.failure_notification_card import build_failure_notification_card
 # 获取触发者信息（从 main_session 或 node_execution）
 chat_id = _resolve_notification_chat_id(session)
 if not chat_id:
 log.warning("failure_notification_no_chat_id")
 return
 repository_name = ""
 if session.last_output and isinstance(session.last_output, dict):
 repository_name = session.last_output.get("repository_name", "")
 card = build_failure_notification_card(
 task_type=session.task_type,
 error_message=error_msg,
 retry_count=retry_count,
 repository_name=repository_name,
 session_id=session.session_id,
 )
 # 发送卡片
 _send_feishu_card(chat_id, card)
 log.info("failure_notification_sent", chat_id=chat_id)
 except Exception as e:
 log.error("failure_notification_error", error=str(e))
def _resolve_notification_chat_id(session: SubAgentSession) -> str:
 """解析通知目标的 chat_id。"""
 # 优先从 main_session 获取（metadata 中的 chat_id）
 if session.main_session and session.main_session.metadata:
 return session.main_session.metadata.get("chat_id", "")
 # 从 node_execution 获取
 if session.node_execution:
 node_exec = session.node_execution
 if node_exec.node and node_exec.node.config:
 return node_exec.node.config.get("chat_id", "")
 return ""
def _send_feishu_card(chat_id: str, card: dict) -> None:
 """发送飞书卡片（异步）。"""
 async def _send:
 try:
 from services.feishu_im import FeishuIMClient
 # 从 settings 获取飞书配置
 app_id = getattr(settings, "FEISHU_APP_ID", "")
 app_secret = getattr(settings, "FEISHU_APP_SECRET", "")
 if not app_id or not app_secret:
 logger.warning("feishu_config_missing")
 return
 client = FeishuIMClient(app_id=app_id, app_secret=app_secret)
 await client.send_card(
 receive_id=chat_id,
 receive_id_type="chat_id",
 card=card,
 )
 except Exception as e:
 logger.exception("feishu_card_send_error", error=str(e))
 try:
 loop = asyncio.get_running_loop
 loop.create_task(_send)
 except RuntimeError:
 # 没有运行中的事件循环
 pass
class ContainerCallbackView(APIView):
 """容器统一回调端点。
 所有容器 SubAgent 通过 POST 请求上报状态。
 使用 CONTAINER_CALLBACK_TOKEN 进行身份验证。
 """
 permission_classes = [AllowAny]
 def post(self, request):
 # 1. 反序列化 + 基础验证
 serializer = CallbackSerializer(data=request.data)
 if not serializer.is_valid:
 return Response(
 {"detail": "Invalid callback payload", "errors": serializer.errors},
 status=status.HTTP_400_BAD_REQUEST,
 )
 data = serializer.validated_data
 callback_type = data["type"]
 session_id = data["session_id"]
 token = data["token"]
 payload = data.get("payload", {})
 log = logger.bind(
 callback_type=callback_type,
 session_id=session_id,
 )
 # 2. Token 验证
 expected_token = getattr(settings, "CONTAINER_CALLBACK_TOKEN", "")
 if not expected_token or token != expected_token:
 log.warning("callback_token_invalid")
 return Response(
 {"detail": "Invalid token"},
 status=status.HTTP_403_FORBIDDEN,
 )
 # 3. Session 查找
 try:
 session = SubAgentSession.objects.get(session_id=session_id)
 except SubAgentSession.DoesNotExist:
 log.warning("callback_session_not_found")
 return Response(
 {"detail": f"Session not found: {session_id}"},
 status=status.HTTP_404_NOT_FOUND,
 )
 # 4. 终态检查 — 已完成的 session 拒绝重复回调
 if session.status in _TERMINAL_STATUSES:
 log.info("callback_terminal_state", current_status=session.status)
 return Response(
 {"detail": "Session already in terminal state", "status": session.status},
 status=status.HTTP_409_CONFLICT,
 )
 # 5. 分发处理
 handler = _HANDLERS.get(callback_type)
 if not handler:
 return Response(
 {"detail": f"Unknown callback type: {callback_type}"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 return handler(session, payload, log)
# === 回调处理函数 ===
def _handle_completed(session: SubAgentSession, payload: dict, log) -> Response:
 """处理 completed 回调 — 创建 TaskResult，更新 session 状态。"""
 ser = CompletedPayloadSerializer(data=payload)
 if not ser.is_valid:
 return Response(
 {"detail": "Invalid completed payload", "errors": ser.errors},
 status=status.HTTP_400_BAD_REQUEST,
 )
 p = ser.validated_data
 # 幂等：如果 TaskResult 已存在，直接返回成功
 if TaskResult.objects.filter(session=session).exists:
 log.info("callback_completed_idempotent")
 return Response({"status": "ok", "detail": "Already recorded"})
 # 创建 TaskResult
 TaskResult.objects.create(
 session=session,
 result_type=p["result_type"],
 text_output=p["output"].get("text", "") if p["result_type"] == "text" else "",
 branch_name=p.get("branch_name", ""),
 commit_sha=p.get("commit_sha", ""),
 modified_files=p.get("modified_files", ),
 raw_output=p["output"],
 duration_ms=p.get("duration_ms"),
 )
 # 更新 session 状态
 session.mark_completed
 # 调度容器清理（成功任务立即清理）
 _schedule_container_cleanup(session, immediate=True)
 log.info("callback_completed_ok", result_type=p["result_type"])
 return Response({"status": "ok"})
def _handle_failed(session: SubAgentSession, payload: dict, log) -> Response:
 """处理 failed 回调 — 更新状态，轻量任务自动重试。"""
 ser = FailedPayloadSerializer(data=payload)
 if not ser.is_valid:
 return Response(
 {"detail": "Invalid failed payload", "errors": ser.errors},
 status=status.HTTP_400_BAD_REQUEST,
 )
 p = ser.validated_data
 error_msg = p.get("error", "Unknown error")
 task_type = session.task_type
 # Coding 任务不重试（有 Git 副作用）
 if task_type not in RETRYABLE_TASK_TYPES:
 session.mark_failed(error=error_msg)
 _schedule_container_cleanup(session, immediate=False)
 _send_failure_notification(session, error_msg, retry_count=0)
 log.info("callback_failed_no_retry", task_type=task_type)
 return Response({"status": "ok", "retried": False})
 # 获取当前重试次数
 retry_count = 0
 if session.last_output and isinstance(session.last_output, dict):
 retry_count = session.last_output.get("retry_count", 0)
 if retry_count >= MAX_RETRIES:
 session.mark_failed(error=error_msg)
 _schedule_container_cleanup(session, immediate=False)
 _send_failure_notification(session, error_msg, retry_count=retry_count)
 log.info("callback_failed_max_retries", retry_count=retry_count)
 return Response({"status": "ok", "retried": False, "max_retries_exceeded": True})
 # 计划重试
 retry_delay = RETRY_DELAYS[retry_count]
 session.last_output = {
 **(session.last_output or {}),
 "retry_count": retry_count + 1,
 "last_error": error_msg,
 }
 session.save(update_fields=["last_output", "updated_at"])
 # 调度延迟重试
 _schedule_retry(session, delay_seconds=retry_delay)
 log.info(
 "callback_failed_retry_scheduled",
 retry_count=retry_count + 1,
 retry_delay=retry_delay,
 )
 return Response({"status": "ok", "retried": True, "retry_count": retry_count + 1})
def _schedule_retry(session: SubAgentSession, delay_seconds: int) -> None:
 """调度任务重试（延迟执行）。"""
 async def _retry_after_delay:
 await asyncio.sleep(delay_seconds)
 try:
 from services.container_manager import ContainerConfig, ContainerManager
 from subagent.models import generate_execution_id
 # 生成新 session_id
 old_session_id = session.session_id
 new_session_id = generate_execution_id
 # 构建 config（从 session 恢复）
 config = ContainerConfig(
 session_id=new_session_id,
 task_type=session.task_type,
 repo_url=session.repo_url,
 work_item_id=session.work_item_id,
 target_branch=session.target_branch,
 )
 manager = ContainerManager
 await manager.restart(config)
 logger.info(
 "retry_started",
 old_session_id=old_session_id,
 new_session_id=new_session_id,
 )
 except Exception as e:
 logger.exception("retry_error", session_id=session.session_id, error=str(e))
 try:
 loop = asyncio.get_running_loop
 loop.create_task(_retry_after_delay)
 except RuntimeError:
 # 没有运行中的事件循环，直接创建新的
 asyncio.create_task(_retry_after_delay)
def _handle_heartbeat(session: SubAgentSession, payload: dict, log) -> Response:
 """处理 heartbeat 回调 — 更新 last_heartbeat_at。"""
 ser = HeartbeatPayloadSerializer(data=payload)
 if not ser.is_valid:
 return Response(
 {"detail": "Invalid heartbeat payload", "errors": ser.errors},
 status=status.HTTP_400_BAD_REQUEST,
 )
 session.last_heartbeat_at = timezone.now
 session.save(update_fields=["last_heartbeat_at", "updated_at"])
 log.debug("callback_heartbeat_ok")
 return Response({"status": "ok"})
def _handle_question(session: SubAgentSession, payload: dict, log) -> Response:
 """处理 question 回调 — 更新 session 状态，触发 Feishu 提问卡片。"""
 ser = QuestionPayloadSerializer(data=payload)
 if not ser.is_valid:
 return Response(
 {"detail": "Invalid question payload", "errors": ser.errors},
 status=status.HTTP_400_BAD_REQUEST,
 )
 p = ser.validated_data
 # 存储问题到 last_output（临时状态数据）
 session.last_output = {
 "pending_question": {
 "question": p["question"],
 "options": p.get("options", ),
 "context": p.get("context", ""),
 "asked_at": timezone.now.isoformat,
 },
 }
 session.save(update_fields=["last_output", "updated_at"])
 # 触发 Feishu 提问卡片（异步，不阻塞回调响应）
 from subagent.question_handler import send_question_card
 try:
 send_question_card(
 session=session,
 question=p["question"],
 options=p.get("options", ),
 context=p.get("context", ""),
 )
 except Exception as e:
 log.error("callback_question_card_failed", error=str(e))
 # 卡片发送失败不影响回调响应
 log.info("callback_question_ok", question_preview=p["question"][:80])
 return Response({"status": "ok"})
def _handle_progress(session: SubAgentSession, payload: dict, log) -> Response:
 """处理 progress 回调 — 更新 last_output（临时进度数据）。"""
 ser = ProgressPayloadSerializer(data=payload)
 if not ser.is_valid:
 return Response(
 {"detail": "Invalid progress payload", "errors": ser.errors},
 status=status.HTTP_400_BAD_REQUEST,
 )
 p = ser.validated_data
 session.last_output = {
 "progress": {
 "phase": p.get("phase", ""),
 "progress": p.get("progress", 0.0),
 "message": p.get("message", ""),
 "updated_at": timezone.now.isoformat,
 },
 }
 session.save(update_fields=["last_output", "updated_at"])
 log.debug("callback_progress_ok", phase=p.get("phase", ""))
 return Response({"status": "ok"})
# 处理器映射
_HANDLERS = {
 CallbackType.COMPLETED: _handle_completed,
 CallbackType.FAILED: _handle_failed,
 CallbackType.HEARTBEAT: _handle_heartbeat,
 CallbackType.QUESTION: _handle_question,
 CallbackType.PROGRESS: _handle_progress,
}
