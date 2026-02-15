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
from datetime import timedelta
import structlog
from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from services.protocols import CallbackType
from subagent.models import ActionLog, ExecutionContext, SubAgentSession, TaskResult, TokenUsage
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
# === 重试配置（Phase）===
# 可重试的任务类型（用户决策：explore/ask/plan 可重试，coding 不重试）
RETRYABLE_TASK_TYPES = {"explore", "ask", "plan"}
MAX_RETRIES = 2
RETRY_DELAYS = [30, 60] # 指数退避：30s -> 60s
# === 并行调度通知（Phase）===
def _notify_scheduler_completion(session_id: str) -> None:
 """通知调度器容器已完成，尝试启动队列中下一个任务。"""
 async def _notify:
 try:
 from services.parallel_scheduler import get_scheduler
 scheduler = get_scheduler
 await scheduler.on_container_completed(session_id)
 except Exception as e:
 logger.warning("scheduler_notification_failed", session_id=session_id, error=str(e))
 try:
 loop = asyncio.get_running_loop
 loop.create_task(_notify)
 except RuntimeError:
 # 没有运行中的事件循环
 asyncio.run(_notify)
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
def _collect_container_stats(session: SubAgentSession, log: BoundLogger) -> None:
 """收集容器资源消耗（在清理前）。
 通过 docker stats 获取 CPU 使用率和内存使用量。
 这是同步调用但会异步执行以不阻塞回调响应。
 """
 async def _collect:
 if not session.container_id:
 return
 try:
 import asyncio
 from services.container_manager import ContainerManager
 manager = ContainerManager
 container = await asyncio.to_thread(
 manager._executor.client.containers.get, session.container_id
 )
 # 获取 docker stats（单次采样）
 stats = await asyncio.to_thread(container.stats, stream=False)
 if stats:
 # CPU 使用率计算
 cpu_stats = stats.get("cpu_stats", {})
 precpu_stats = stats.get("precpu_stats", {})
 cpu_delta = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) - precpu_stats.get(
 "cpu_usage", {}
 ).get("total_usage", 0)
 system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get(
 "system_cpu_usage", 0
 )
 if system_delta > 0 and cpu_delta > 0:
 # 考虑 CPU 核心数
 online_cpus = cpu_stats.get("online_cpus", 1)
 cpu_percent = (cpu_delta / system_delta) * online_cpus * 100
 session.cpu_usage_percent = round(cpu_percent, 2)
 # 内存使用
 mem_stats = stats.get("memory_stats", {})
 mem_usage = mem_stats.get("usage", 0)
 if mem_usage > 0:
 session.memory_usage_mb = round(mem_usage / 1024 / 1024, 2)
 session.save(update_fields=["cpu_usage_percent", "memory_usage_mb", "updated_at"])
 log.info(
 "container_stats_collected",
 cpu_percent=session.cpu_usage_percent,
 memory_mb=session.memory_usage_mb,
 )
 except Exception as e:
 log.warning("stats_collection_error", error=str(e))
 try:
 loop = asyncio.get_running_loop
 loop.create_task(_collect)
 except RuntimeError:
 # 没有运行中的事件循环
 pass
# === 失败通知（Phase）===
def _schedule_agent_loop_resume(session: SubAgentSession, log: BoundLogger) -> None:
 """触发 AgentLoop 恢复（当容器完成时）。
 仅当 session 有 main_session 但无 node_execution 时触发（纯 AgentLoop 场景）。
 如果有 node_execution，由 workflow 恢复处理。
 Args:
 session: SubAgentSession 实例
 log: Bound logger
 """
 # 如果有 node_execution，由 workflow 恢复处理
 if session.node_execution_id:
 log.debug("has_node_execution_skip_agent_resume")
 return
 # 检查是否有 main_session
 if not session.main_session_id:
 log.debug("no_main_session_skip_agent_resume")
 return
 async def _prepare_and_resume:
 """异步准备并调度 AgentLoop 恢复。"""
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
 # 调度 AgentLoop 恢复
 from tasks.agent_tasks import schedule_resume_agent_session
 # 需要刷新 main_session 关系以获取 session_id
 await session.arefresh_from_db
 if session.main_session:
 schedule_resume_agent_session(
 session_id=session.main_session.session_id,
 user_response=result_msg,
 )
 log.info(
 "agent_loop_resume_scheduled",
 main_session_id=session.main_session.session_id,
 )
 except Exception as e:
 log.exception("agent_loop_resume_error", error=str(e))
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
def _send_feishu_card(chat_id: str, card: dict[str, Any]) -> None:
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
 return handler(session, payload, log)
# === 执行上下文收集（Phase）===
# 敏感环境变量 key 关键词
_SENSITIVE_KEY_PATTERNS = {"API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"}
def _filter_sensitive_env(env: dict[str, str]) -> dict[str, str]:
 """过滤环境变量中的敏感值。"""
 filtered = {}
 for k, v in env.items:
 key_upper = k.upper
 if any(p in key_upper for p in _SENSITIVE_KEY_PATTERNS):
 filtered[k] = "***"
 else:
 filtered[k] = v
 return filtered
def _collect_execution_context(session: SubAgentSession, log: BoundLogger) -> None:
 """在容器清理前收集执行上下文写入 ExecutionContext。"""
 async def _collect:
 try:
 import json
 import os
 from services.container_manager import ContainerManager
 manager = ContainerManager
 # 容器日志
 container_logs = ""
 if session.container_id:
 container_logs = await manager.get_logs(session.session_id, tail=500)
 # Docker stats
 docker_stats: dict = {}
 if session.container_id:
 try:
 import asyncio
 container = await asyncio.to_thread(
 manager._executor.client.containers.get, session.container_id
 )
 docker_stats = await asyncio.to_thread(container.stats, stream=False)
 except Exception as e:
 log.warning("docker_stats_collection_error", error=str(e))
 # 环境变量（从 ContainerManager 构建方法获取，过滤敏感 key）
 environment_vars: dict = {}
 try:
 env = manager._build_environment(
 type("_Cfg",, {
 "session_id": session.session_id,
 "task_type": session.task_type,
 "repo_url": session.repo_url,
 "branch": session.target_branch or "main",
 "target_branch": session.target_branch,
 "timeout": 3600,
 "git_credentials": {},
 "claude_api_key": "",
 "claude_base_url": "",
 })
 )
 environment_vars = _filter_sensitive_env(env)
 except Exception as e:
 log.warning("env_collection_error", error=str(e))
 # input_prompt（从 transfer 目录的 context.json 读取）
 input_prompt = ""
 try:
 transfer_dir = os.path.join(
 manager._executor.transfers_dir, session.session_id, ".friday"
 )
 context_path = os.path.join(transfer_dir, "context.json")
 if os.path.exists(context_path):
 with open(context_path) as f:
 ctx = json.load(f)
 input_prompt = ctx.get("prompt", "")
 except Exception as e:
 log.warning("prompt_collection_error", error=str(e))
 # 创建或更新 ExecutionContext
 from asgiref.sync import sync_to_async
 await sync_to_async(ExecutionContext.objects.update_or_create)(
 session=session,
 defaults={
 "environment_vars": environment_vars,
 "input_prompt": input_prompt,
 "container_logs": container_logs,
 "docker_stats": docker_stats,
 },
 )
 log.info("execution_context_collected")
 except Exception as e:
 log.warning("execution_context_collection_error", error=str(e))
 try:
 loop = asyncio.get_running_loop
 loop.create_task(_collect)
 except RuntimeError:
 pass
# === 回调处理函数 ===
def _handle_completed(session: SubAgentSession, payload: dict[str, Any], log: BoundLogger) -> Response:
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
 # 收集执行上下文（在清理前）
 _collect_execution_context(session, log)
 # 收集容器资源消耗（在清理前）
 _collect_container_stats(session, log)
 # 调度容器清理（成功任务立即清理）
 _schedule_container_cleanup(session, immediate=True)
 # 触发 workflow 恢复（如果有 node_execution）
 _schedule_workflow_resume(session, log)
 # 触发 AgentLoop 恢复（如果有 main_session 但无 node_execution）
 _schedule_agent_loop_resume(session, log)
 # 通知调度器容器完成（Phase）
 _notify_scheduler_completion(session.session_id)
 log.info("callback_completed_ok", result_type=p["result_type"])
 return Response({"status": "ok"})
def _handle_failed(session: SubAgentSession, payload: dict[str, Any], log: BoundLogger) -> Response:
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
 session.failure_reason = error_msg
 session.save(update_fields=["failure_reason"])
 session.mark_failed(error=error_msg)
 _collect_execution_context(session, log)
 _schedule_container_cleanup(session, immediate=False)
 _send_failure_notification(session, error_msg, retry_count=0)
 # 触发 workflow 恢复（如果有 node_execution）
 _schedule_workflow_resume(session, log)
 # 触发 AgentLoop 恢复
 _schedule_agent_loop_resume(session, log)
 # 通知调度器容器完成（Phase）
 _notify_scheduler_completion(session.session_id)
 log.info("callback_failed_no_retry", task_type=task_type)
 return Response({"status": "ok", "retried": False})
 # 获取当前重试次数
 retry_count = 0
 if session.last_output and isinstance(session.last_output, dict):
 retry_count = session.last_output.get("retry_count", 0)
 if retry_count >= MAX_RETRIES:
 session.failure_reason = error_msg
 session.save(update_fields=["failure_reason"])
 session.mark_failed(error=error_msg)
 _collect_execution_context(session, log)
 _schedule_container_cleanup(session, immediate=False)
 _send_failure_notification(session, error_msg, retry_count=retry_count)
 # 触发 workflow 恢复（如果有 node_execution）
 _schedule_workflow_resume(session, log)
 # 触发 AgentLoop 恢复
 _schedule_agent_loop_resume(session, log)
 # 通知调度器容器完成（Phase）
 _notify_scheduler_completion(session.session_id)
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
def _handle_heartbeat(session: SubAgentSession, payload: dict[str, Any], log: BoundLogger) -> Response:
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
def _handle_question(session: SubAgentSession, payload: dict[str, Any], log: BoundLogger) -> Response:
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
 interaction_log = InteractionLog.objects.create(
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
 session.save(update_fields=["last_output", "updated_at"])
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
def _handle_progress(session: SubAgentSession, payload: dict[str, Any], log: BoundLogger) -> Response:
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
def _handle_action_log(session: SubAgentSession, payload: dict[str, Any], log: BoundLogger) -> Response:
 """处理 action_log 回调 — 写入 ActionLog 记录。"""
 ser = ActionLogPayloadSerializer(data=payload)
 if not ser.is_valid:
 return Response(
 {"detail": "Invalid action_log payload", "errors": ser.errors},
 status=status.HTTP_400_BAD_REQUEST,
 )
 p = ser.validated_data
 ActionLog.objects.create(
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
def _handle_token_usage(session: SubAgentSession, payload: dict[str, Any], log: BoundLogger) -> Response:
 """处理 token_usage 回调 — 写入 TokenUsage 记录。"""
 ser = TokenUsagePayloadSerializer(data=payload)
 if not ser.is_valid:
 return Response(
 {"detail": "Invalid token_usage payload", "errors": ser.errors},
 status=status.HTTP_400_BAD_REQUEST,
 )
 p = ser.validated_data
 TokenUsage.objects.create(
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
from structlog.typing import BoundLogger
