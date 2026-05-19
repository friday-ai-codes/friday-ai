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
from typing import Any
import structlog
from adrf.views import APIView
from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from structlog.stdlib import BoundLogger
from orchestration.progress_payload import parse_progress_payload
from services.protocols import CallbackType
from subagent.models import ActionLog, SubAgentSession, TaskResult, TokenUsage
from .serializers import (
 ActionLogPayloadSerializer,
 CallbackSerializer,
 CompletedPayloadSerializer,
 FailedPayloadSerializer,
 HeartbeatPayloadSerializer,
 ProgressPayloadSerializer,
 QuestionPayloadSerializer,
 TokenUsagePayloadSerializer,
)
logger = structlog.get_logger
# 终态集合 — 处于终态的 session 不再接受回调
_TERMINAL_STATUSES = {
 SubAgentSession.Status.COMPLETED,
 SubAgentSession.Status.ERROR,
 SubAgentSession.Status.TIMEOUT,
 SubAgentSession.Status.CANCELLED,
}
# 数据补充类回调绕过终态检查（它们不改变状态，只追加数据）
_DATA_APPEND_TYPES = {CallbackType.ACTION_LOG, CallbackType.TOKEN_USAGE}
def _notify_barrier_manager(session: SubAgentSession, log: BoundLogger) -> None:
 """通知 BarrierManager 任务完成/失败 — 由 chat_deep_analysis 回调触发。"""
 is_success = session.status == SubAgentSession.Status.COMPLETED
 async def _do_notify -> None:
 try:
 from orchestration.barrier import get_barrier_manager
 from orchestration.contracts import BlockingTaskResult
 output_text = ""
 error_text = ""
 if is_success:
 task_result = await TaskResult.objects.filter(session=session).afirst
 if task_result:
 output_text = task_result.text_output or ""
 if not output_text and task_result.raw_output:
 output_text = str(task_result.raw_output)[:3000]
 else:
 error_text = session.last_error or f"Task {session.status}"
 result: BlockingTaskResult = {
 "task_id": session.session_id,
 "task_type": session.task_type or "deep_analysis",
 "success": is_success,
 "output": output_text,
 "error": error_text,
 }
 barrier = get_barrier_manager
 satisfied = await barrier.task_completed(session.session_id, result)
 log.info(
 "barrier_task_notified",
 session_id=session.session_id,
 success=is_success,
 barrier_satisfied=satisfied,
 )
 except Exception:
 log.exception("barrier_notify_error", session_id=session.session_id)
 try:
 loop = asyncio.get_running_loop
 loop.create_task(_do_notify)
 except RuntimeError:
 asyncio.run(_do_notify)
def _schedule_agent_session_resume(session: SubAgentSession, log: BoundLogger) -> None:
 """触发 Agent 会话恢复（当容器完成时）。
 仅当 session 有 main_session 但无 node_execution 时触发（纯 Agent 场景）。
 如果有 node_execution，由 workflow 恢复处理。
 Args:
 session: SubAgentSession 实例
 log: Bound logger
 """
 # 如果有 node_execution，由 workflow 恢复处理
 if session.node_execution_id:
 log.debug("has_node_execution_skip_agent_resume")
 return
 if isinstance(session.last_output, dict) and session.last_output.get("source") == "chat_deep_analysis":
 log.info("chat_deep_analysis_notify_barrier", session_id=session.session_id)
 _notify_barrier_manager(session, log)
 return
 # 检查是否有 main_session
 if not session.main_session_id:
 log.debug("no_main_session_skip_agent_resume")
 return
 async def _prepare_and_resume:
 """异步准备并调度 Agent 会话恢复。"""
 try:
 from subagent.models import TaskResult
 # 获取 TaskResult
 task_result = await TaskResult.objects.filter(
 session=session,
 ).afirst
 # 构建结果消息
 if task_result:
 if session.status == SubAgentSession.Status.COMPLETED:
 result_msg = f"SubAgent 任务完成。\n\n结果：\n{task_result.text_output[:2000]}"
 else:
 result_msg = f"SubAgent 任务失败：{session.last_error}"
 else:
 if session.status == SubAgentSession.Status.COMPLETED:
 result_msg = "SubAgent 任务完成。"
 else:
 result_msg = f"SubAgent 任务失败：{session.last_error}"
 # 调度 Agent 会话恢复
 from agents.models import AgentSession
 from tasks.agent_tasks import schedule_resume_agent_session
 await session.arefresh_from_db
 if session.main_session_id:
 main_session = await AgentSession.objects.filter(
 id=session.main_session_id,
 ).afirst
 if main_session:
 schedule_resume_agent_session(
 session_id=main_session.session_id,
 user_response=result_msg,
 )
 log.info(
 "agent_session_resume_scheduled",
 main_session_id=main_session.session_id,
 )
 except Exception as e:
 log.exception("agent_session_resume_error", error=str(e))
 try:
 loop = asyncio.get_running_loop
 loop.create_task(_prepare_and_resume)
 except RuntimeError:
 # 没有运行中的事件循环
 asyncio.run(_prepare_and_resume)
def _schedule_workflow_resume(session: SubAgentSession, log: BoundLogger) -> None:
 """触发 workflow 恢复（异步，不阻塞回调响应）。
 当容器完成时，检查该节点的所有 SubAgentSession 是否都已终态，
 如果是则恢复 workflow 执行。
 """
 if not session.node_execution_id:
 log.debug("no_node_execution_skip_resume")
 return
 async def _resume:
 try:
 from django.db import close_old_connections
 from workflows.engine.scheduler import WorkflowEngine
 from workflows.models.execution import NodeExecution
 # 关闭旧连接（防止长时间运行后的连接问题）
 close_old_connections
 # 获取 node_execution
 node_exec = (
 await NodeExecution.objects.select_related("workflow_execution")
 .filter(id=session.node_execution_id)
 .afirst
 )
 if not node_exec:
 log.warning("node_execution_not_found_for_resume")
 return
 # 检查该节点的所有 SubAgentSession 是否都已终态
 pending_count = await SubAgentSession.objects.filter(
 node_execution=node_exec,
 status__in=[
 SubAgentSession.Status.PENDING,
 SubAgentSession.Status.RUNNING,
 ],
 ).acount
 if pending_count > 0:
 log.info(
 "pending_subagents_remain",
 pending_count=pending_count,
 node_execution_id=str(node_exec.id),
 )
 return
 # 所有任务完成，设置恢复标记并触发 workflow 恢复
 output_data = node_exec.output_data or {}
 output_data["_resume_from_callback"] = True
 output_data["_all_containers_completed"] = True
 # 保存每个 session 的结果摘要
 session_results = {}
 async for s in SubAgentSession.objects.filter(node_execution=node_exec):
 session_results[s.session_id] = {
 "status": s.status,
 "error": s.last_error,
 }
 output_data["_session_results"] = session_results
 node_exec.output_data = output_data
 await node_exec.asave(update_fields=["output_data"])
 # 恢复 workflow
 engine = WorkflowEngine
 await engine._continue_after_node(
 node_exec.workflow_execution,
 node_exec,
 )
 log.info(
 "workflow_resumed_after_container_completion",
 node_execution_id=str(node_exec.id),
 workflow_execution_id=str(node_exec.workflow_execution.id),
 )
 except Exception as e:
 log.exception("workflow_resume_error", error=str(e))
 try:
 loop = asyncio.get_running_loop
 loop.create_task(_resume)
 except RuntimeError:
 # 没有运行中的事件循环，创建新的
 asyncio.run(_resume)
async def _send_failure_notification(
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
 chat_id = await _resolve_notification_chat_id(session)
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
 await _send_feishu_card(chat_id, card)
 log.info("failure_notification_sent", chat_id=chat_id)
 except Exception as e:
 log.error("failure_notification_error", error=str(e))
async def _resolve_notification_chat_id(session: SubAgentSession) -> str:
 """解析通知目标的 chat_id。"""
 # 优先从 main_session 获取（metadata 中的 chat_id）
 if session.main_session_id:
 from agents.models import AgentSession
 main = await AgentSession.objects.filter(pk=session.main_session_id).afirst
 if main and main.metadata:
 chat_id: str = main.metadata.get("chat_id", "")
 if chat_id:
 return chat_id
 # 从 node_execution 获取
 if session.node_execution_id:
 from workflows.models.execution import NodeExecution
 ne = (
 await NodeExecution.objects.select_related("node")
 .filter(pk=session.node_execution_id)
 .afirst
 )
 if ne and ne.node and ne.node.config:
 return ne.node.config.get("chat_id", "")
 return ""
async def _send_feishu_card(chat_id: str, card: dict[str, Any]) -> None:
 """发送飞书卡片。"""
 try:
 from services.feishu_im import FeishuIMClient
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
class ContainerCallbackView(APIView):
 """容器统一回调端点。
 所有容器 SubAgent 通过 POST 请求上报状态。
 使用 CONTAINER_CALLBACK_TOKEN 进行身份验证。
 """
 permission_classes = [AllowAny]
 async def post(self, request):
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
 session = await SubAgentSession.objects.aget(session_id=session_id)
 except SubAgentSession.DoesNotExist:
 log.warning("callback_session_not_found")
 return Response(
 {"detail": f"Session not found: {session_id}"},
 status=status.HTTP_404_NOT_FOUND,
 )
 # 4. 终态检查 — 已完成的 session 拒绝重复回调（数据补充类回调除外）
 if session.status in _TERMINAL_STATUSES and callback_type not in _DATA_APPEND_TYPES:
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
 return await handler(session, payload, log)
# === CodingSession 回调扩展 (Phase) ===
async def _update_coding_session_on_complete(session: SubAgentSession) -> None:
 """容器完成回调 -- 根据 task_type 区分 Phase/2，resume CodingSession graph。
 Phase (coding): 提取 suggested_commit_message，resume graph 进入 awaiting_confirmation。
 Phase (coding_commit): resume graph 标记 completed。
 兼容旧流程: 非 graph 管理的 session 直接 amark_completed。
 """
 from chat.coding_events import store_coding_complete_to_message
 from chat.models import CodingSession
 coding_session = await CodingSession.objects.filter(
 subagent_session=session,
 ).afirst
 if coding_session is None:
 return
 if session.task_type == "coding":
 # Phase 完成: 提取 suggested_commit_message，resume graph
 suggested_msg = ""
 if isinstance(session.last_output, dict):
 suggested_msg = session.last_output.get("suggested_commit_message", "")
 from langgraph.types import Command
 from orchestration.checkpointer import get_checkpointer
 from orchestration.coding_graph import build_coding_graph
 checkpointer = await get_checkpointer
 graph = build_coding_graph.compile(checkpointer=checkpointer)
 config = {"configurable": {"thread_id": f"coding-{coding_session.id}"}}
 # 与 _update_coding_session_on_fail 对称的防御：graph 不存在（v18.1
 # Phase 实施缺口期间 view 未启动 graph）或 ainvoke 异常时降级为
 # 直接 amark_completed + 错误日志，避免 WS / HTTP completed callback
 # 父流程被吞掉无关异常。
 try:
 await graph.ainvoke(
 Command(resume={"success": True, "suggested_commit_message": suggested_msg}),
 config=config,
 )
 logger.info(
 "coding_session_phase1_complete",
 coding_session_id=str(coding_session.id),
 )
 except Exception:
 logger.exception(
 "coding_graph_resume_complete_fail",
 coding_session_id=str(coding_session.id),
 phase="phase1",
 )
 await coding_session.amark_completed
 await store_coding_complete_to_message(coding_session)
 elif session.task_type == "coding_commit":
 # Phase 完成: resume graph，三阶段流程中 graph 继续执行到 PR 创建/跳过，
 # store_coding_complete_to_message 已在 create_pr_or_skip_node 中调用
 from langgraph.types import Command
 from orchestration.checkpointer import get_checkpointer
 from orchestration.coding_graph import build_coding_graph
 checkpointer = await get_checkpointer
 graph = build_coding_graph.compile(checkpointer=checkpointer)
 config = {"configurable": {"thread_id": f"coding-{coding_session.id}"}}
 try:
 await graph.ainvoke(
 Command(resume={"success": True}),
 config=config,
 )
 logger.info(
 "coding_session_phase2_complete",
 coding_session_id=str(coding_session.id),
 )
 except Exception:
 logger.exception(
 "coding_graph_resume_complete_fail",
 coding_session_id=str(coding_session.id),
 phase="phase2",
 )
 task_result_fallback = await TaskResult.objects.filter(session=session).afirst
 pr_url_fallback = task_result_fallback.pr_url if task_result_fallback else ""
 await coding_session.amark_completed(pr_url=pr_url_fallback)
 await store_coding_complete_to_message(coding_session)
 else:
 # 兼容旧流程（非 graph 管理的 session）
 task_result = await TaskResult.objects.filter(session=session).afirst
 pr_url = task_result.pr_url if task_result else ""
 await coding_session.amark_completed(pr_url=pr_url)
 await store_coding_complete_to_message(coding_session)
 logger.info("coding_session_completed", coding_session_id=str(coding_session.id), pr_url=pr_url)
async def _update_coding_session_on_fail(session: SubAgentSession, error: str) -> None:
 """容器失败回调 -- resume graph 标记 CodingSession failed。
 graph 管理的 session (coding/coding_commit): 通过 Command(resume=) 恢复 graph 处理失败。
 graph resume 本身失败时降级为直接更新 DB。
 兼容旧流程: 非 graph 管理的 session 直接 amark_failed。
 """
 from chat.coding_events import store_coding_failed_to_message
 from chat.models import CodingSession
 coding_session = await CodingSession.objects.filter(
 subagent_session=session,
 ).afirst
 if coding_session is None:
 return
 if session.task_type in ("coding", "coding_commit"):
 # graph 管理的 session: resume graph 处理失败
 from langgraph.types import Command
 from orchestration.checkpointer import get_checkpointer
 from orchestration.coding_graph import build_coding_graph
 checkpointer = await get_checkpointer
 graph = build_coding_graph.compile(checkpointer=checkpointer)
 config = {"configurable": {"thread_id": f"coding-{coding_session.id}"}}
 try:
 await graph.ainvoke(
 Command(resume={"success": False, "error": error}),
 config=config,
 )
 except Exception:
 # graph resume 失败时直接更新 DB
 logger.exception("coding_graph_resume_fail", coding_session_id=str(coding_session.id))
 await coding_session.amark_failed(error=error)
 else:
 await coding_session.amark_failed(error=error)
 await store_coding_failed_to_message(coding_session)
 logger.info(
 "coding_session_failed",
 coding_session_id=str(coding_session.id),
 error=error,
 )
# === 回调处理函数 ===
async def _handle_completed(
 session: SubAgentSession, payload: dict[str, Any], log: BoundLogger
) -> Response:
 """处理 completed 回调 — 创建 TaskResult，更新 session 状态。"""
 ser = CompletedPayloadSerializer(data=payload)
 if not ser.is_valid:
 return Response(
 {"detail": "Invalid completed payload", "errors": ser.errors},
 status=status.HTTP_400_BAD_REQUEST,
 )
 p = ser.validated_data
 # 幂等：如果 TaskResult 已存在，直接返回成功
 if await TaskResult.objects.filter(session=session).aexists:
 log.info("callback_completed_idempotent")
 return Response({"status": "ok", "detail": "Already recorded"})
 # 创建 TaskResult
 await TaskResult.objects.acreate(
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
 await session.amark_completed
 # 更新关联的 CodingSession（如果有）
 await _update_coding_session_on_complete(session)
 # 触发 workflow 恢复（如果有 node_execution）
 _schedule_workflow_resume(session, log)
 # 触发 Agent 会话恢复（如果有 main_session 但无 node_execution）
 _schedule_agent_session_resume(session, log)
 # repo_summary 完成写回 Repository
 if session.task_type == SubAgentSession.TaskType.REPO_SUMMARY:
 await _update_repository_on_summary_complete(session, p)
 log.info("callback_completed_ok", result_type=p["result_type"])
 return Response({"status": "ok"})
async def _handle_failed(
 session: SubAgentSession, payload: dict[str, Any], log: BoundLogger
) -> Response:
 """处理 failed 回调 — 标记失败，通知，恢复 workflow/agent。
 Phase: Runner 端独立处理重试，Server 端不再重试。
 """
 ser = FailedPayloadSerializer(data=payload)
 if not ser.is_valid:
 return Response(
 {"detail": "Invalid failed payload", "errors": ser.errors},
 status=status.HTTP_400_BAD_REQUEST,
 )
 p = ser.validated_data
 error_msg = p.get("error", "Unknown error")
 # 直接标记失败（Runner 端独立处理重试）
 session.failure_reason = error_msg
 await session.asave(update_fields=["failure_reason"])
 await session.amark_failed(error=error_msg)
 # 更新关联的 CodingSession（如果有）
 await _update_coding_session_on_fail(session, error_msg)
 await _send_failure_notification(session, error_msg)
 # 触发 workflow 恢复（如果有 node_execution）
 _schedule_workflow_resume(session, log)
 # 触发 Agent 会话恢复
 _schedule_agent_session_resume(session, log)
 # repo_summary 失败写回 Repository
 if session.task_type == SubAgentSession.TaskType.REPO_SUMMARY:
 await _update_repository_on_summary_fail(session, error_msg)
 log.info("callback_failed_ok", error=error_msg)
 return Response({"status": "ok"})
async def _handle_heartbeat(
 session: SubAgentSession, payload: dict[str, Any], log: BoundLogger
) -> Response:
 """处理 heartbeat 回调 — 更新 last_heartbeat_at。"""
 ser = HeartbeatPayloadSerializer(data=payload)
 if not ser.is_valid:
 return Response(
 {"detail": "Invalid heartbeat payload", "errors": ser.errors},
 status=status.HTTP_400_BAD_REQUEST,
 )
 session.last_heartbeat_at = timezone.now
 await session.asave(update_fields=["last_heartbeat_at", "updated_at"])
 log.debug("callback_heartbeat_ok")
 return Response({"status": "ok"})
async def _handle_question(
 session: SubAgentSession, payload: dict[str, Any], log: BoundLogger
) -> Response:
 """处理 question 回调 — 创建 InteractionLog 并触发 Feishu 提问卡片。"""
 import uuid
 from subagent.models import InteractionLog
 from subagent.question_handler import send_question_card_enhanced
 ser = QuestionPayloadSerializer(data=payload)
 if not ser.is_valid:
 return Response(
 {"detail": "Invalid question payload", "errors": ser.errors},
 status=status.HTTP_400_BAD_REQUEST,
 )
 p = ser.validated_data
 # 生成问题 ID
 question_id = f"q-{uuid.uuid4.hex[:12]}"
 # 创建 InteractionLog 记录
 interaction_log = await InteractionLog.objects.acreate(
 session=session,
 question_id=question_id,
 question_text=p["question"],
 question_context=p.get("context", ""),
 code_snippet=p.get("code_snippet", ""),
 options=p.get("options", ),
 )
 # 存储问题到 last_output（保持兼容）
 session.last_output = {
 **(session.last_output or {}),
 "pending_question": {
 "question_id": question_id,
 "question": p["question"],
 "options": p.get("options", ),
 "asked_at": timezone.now.isoformat,
 },
 }
 await session.asave(update_fields=["last_output", "updated_at"])
 # 触发增强版 Feishu 提问卡片（异步）
 async def _send_card:
 message_id = await send_question_card_enhanced(
 session=session,
 question=p["question"],
 options=p.get("options", ),
 context=p.get("context", ""),
 code_snippet=p.get("code_snippet", ""),
 question_id=question_id,
 )
 # 更新 message_id 到 InteractionLog
 if message_id:
 interaction_log.feishu_message_id = message_id
 await interaction_log.asave(update_fields=["feishu_message_id"])
 try:
 loop = asyncio.get_running_loop
 loop.create_task(_send_card)
 except RuntimeError:
 # 没有运行中的事件循环
 asyncio.run(_send_card)
 log.info(
 "callback_question_ok",
 question_id=question_id,
 interaction_log_id=interaction_log.id,
 question_preview=p["question"][:80],
 )
 return Response({"status": "ok", "question_id": question_id})
async def _handle_progress(
 session: SubAgentSession, payload: dict[str, Any], log: BoundLogger
) -> Response:
 """处理 progress 回调 — 更新 last_output（临时进度数据）。
 Phase + G4 + G5 修复（v18.1 audit gap closure）:
 - G4: 调用公共 ``parse_progress_payload`` 与 WebSocket 路径
 (runners/consumers.py:RunnerConsumer._handle_progress) 共享同一解析逻辑，
 避免两条路径分叉。
 - G1 (BLOCKER): ``details.suggested_commit_message`` scalar 透传到 output 顶层，
 使下游 ``GET /api/chat/coding-sessions/{id}/commit-confirm/`` 返回真实 AI 建议。
 - G5: 使用 dict spread merge 语义写入 ``session.last_output``，保留既有
 task_type/source/conversation_id/logs 等 meta 而非整体覆盖。
 """
 ser = ProgressPayloadSerializer(data=payload)
 if not ser.is_valid:
 return Response(
 {"detail": "Invalid progress payload", "errors": ser.errors},
 status=status.HTTP_400_BAD_REQUEST,
 )
 p = ser.validated_data
 output = parse_progress_payload(p)
 # G5 merge 语义：严格使用 (session.last_output or {}) fallback 防御 None
 session.last_output = {**(session.last_output or {}), **output}
 await session.asave(update_fields=["last_output", "updated_at"])
 log.debug("callback_progress_ok", phase=p.get("phase", ""))
 return Response({"status": "ok"})
async def _handle_action_log(
 session: SubAgentSession, payload: dict[str, Any], log: BoundLogger
) -> Response:
 """处理 action_log 回调 — 写入 ActionLog 记录。"""
 ser = ActionLogPayloadSerializer(data=payload)
 if not ser.is_valid:
 return Response(
 {"detail": "Invalid action_log payload", "errors": ser.errors},
 status=status.HTTP_400_BAD_REQUEST,
 )
 p = ser.validated_data
 await ActionLog.objects.acreate(
 session=session,
 action_type=p["action_type"],
 timestamp=p["timestamp"],
 sequence=p["sequence"],
 payload={
 "tool_name": p["tool_name"],
 "input": p["input"],
 "output": p["output"],
 "thinking": p["thinking"],
 "model": p["model"],
 },
 duration_ms=p["duration_ms"],
 )
 log.debug("callback_action_log_ok", action_type=p["action_type"], sequence=p["sequence"])
 return Response({"status": "ok"})
async def _handle_token_usage(
 session: SubAgentSession, payload: dict[str, Any], log: BoundLogger
) -> Response:
 """处理 token_usage 回调 — 写入 TokenUsage 记录。"""
 ser = TokenUsagePayloadSerializer(data=payload)
 if not ser.is_valid:
 return Response(
 {"detail": "Invalid token_usage payload", "errors": ser.errors},
 status=status.HTTP_400_BAD_REQUEST,
 )
 p = ser.validated_data
 await TokenUsage.objects.acreate(
 session=session,
 input_tokens=p["input_tokens"],
 output_tokens=p["output_tokens"],
 cache_read_tokens=p["cache_read_tokens"],
 cache_write_tokens=p["cache_write_tokens"],
 model=p["model"],
 total_cost_usd=p["total_cost_usd"],
 source=TokenUsage.Source.SUBAGENT,
 )
 log.debug("callback_token_usage_ok", model=p["model"])
 return Response({"status": "ok"})
# === repo_summary 回调辅助函数 (Phase) ===
def _parse_summary_json(raw_text: str) -> str:
 """尝试从 Claude 输出中提取 JSON summary；失败返回原始文本。"""
 import json as json_mod
 import re as re_mod
 if not raw_text:
 return raw_text
 # 1. 先尝试 ```json ... ``` 代码块提取
 m = re_mod.search(r"```json\s*(\{.*?\})\s*```", raw_text, re_mod.DOTALL)
 if m:
 try:
 obj = json_mod.loads(m.group(1))
 return json_mod.dumps(obj, ensure_ascii=False, indent=2)
 except json_mod.JSONDecodeError:
 pass
 # 2. 直接尝试 json.loads
 try:
 obj = json_mod.loads(raw_text.strip)
 return json_mod.dumps(obj, ensure_ascii=False, indent=2)
 except json_mod.JSONDecodeError:
 pass
 # 3. 降级：返回原始文本（markdown 存储）
 return raw_text
async def _update_repository_on_summary_complete(
 session: SubAgentSession, p: dict[str, Any]
) -> None:
 """repo_summary 完成 -- 解析结果写回 Repository。"""
 from repositories.models import Repository
 repo_id = (session.last_output or {}).get("repository_id")
 if not repo_id:
 logger.warning("repo_summary_complete_no_repo_id", session_id=session.session_id)
 return
 repo = await Repository.objects.filter(id=repo_id).afirst
 if not repo:
 logger.warning("repo_summary_complete_repo_not_found", repo_id=repo_id)
 return
 raw_text = p["output"].get("text", "") if p["result_type"] == "text" else ""
 parsed_summary = _parse_summary_json(raw_text)
 repo.ai_summary = parsed_summary[:8192]
 repo.ai_summary_status = "completed"
 repo.ai_summary_generated_at = timezone.now
 repo.ai_summary_error = ""
 await repo.asave(
 update_fields=[
 "ai_summary",
 "ai_summary_status",
 "ai_summary_generated_at",
 "ai_summary_error",
 "updated_at",
 ]
 )
 logger.info(
 "repo_summary_written",
 repository_id=repo_id,
 summary_length=len(parsed_summary),
 )
async def _update_repository_on_summary_fail(
 session: SubAgentSession, error_msg: str
) -> None:
 """repo_summary 失败 -- 写回错误状态。"""
 from repositories.models import Repository
 repo_id = (session.last_output or {}).get("repository_id")
 if not repo_id:
 return
 repo = await Repository.objects.filter(id=repo_id).afirst
 if not repo:
 return
 repo.ai_summary_status = "failed"
 repo.ai_summary_error = error_msg[:2000]
 await repo.asave(
 update_fields=["ai_summary_status", "ai_summary_error", "updated_at"]
 )
 logger.info("repo_summary_fail_written", repository_id=repo_id, error=error_msg[:100])
# 处理器映射
_HANDLERS = {
 CallbackType.COMPLETED: _handle_completed,
 CallbackType.FAILED: _handle_failed,
 CallbackType.HEARTBEAT: _handle_heartbeat,
 CallbackType.QUESTION: _handle_question,
 CallbackType.PROGRESS: _handle_progress,
 CallbackType.ACTION_LOG: _handle_action_log,
 CallbackType.TOKEN_USAGE: _handle_token_usage,
}
