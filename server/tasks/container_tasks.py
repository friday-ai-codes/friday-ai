"""容器健康检查、僵尸检测与清理任务（Phase/49）。
定期任务：
- check_container_health: 检查 RUNNING 容器的 Docker 健康状态 (Phase)
- detect_zombie_containers: 检测心跳超时的容器，标记为 TIMEOUT
- cleanup_completed_containers: 清理已完成容器的 Docker 资源
- enforce_task_timeouts: 强制终止超时容器 (Phase)
"""
import asyncio
from datetime import timedelta
from typing import Any
import docker
import structlog
from django.conf import settings
from django.utils import timezone
from services.container_config import ZOMBIE_HEARTBEAT_SECONDS
from subagent.models import SubAgentSession
logger = structlog.get_logger(__name__)
# 容器清理阈值（小时）— 终态容器超过此时间后清理 Docker 资源
CONTAINER_CLEANUP_HOURS = getattr(settings, "CONTAINER_CLEANUP_HOURS", 24)
async def check_container_health -> dict:
 """检查 RUNNING 容器的健康状态。
 通过 docker inspect 读取容器健康状态，更新 SubAgentSession.health_status。
 检测到 unhealthy 时记录日志但不立即终止（由超时任务处理）。
 Returns:
 {"checked": int, "healthy": int, "unhealthy": int, "errors": list}
 """
 log = logger.bind(task="check_container_health")
 log.info("task_start")
 from services.container_manager import ContainerManager
 manager = ContainerManager
 stats: dict[str, Any] = {"checked": 0, "healthy": 0, "unhealthy": 0, "errors": }
 sessions = SubAgentSession.objects.filter(
 status=SubAgentSession.Status.RUNNING,
 container_id__gt="",
 )
 async for session in sessions:
 try:
 # 通过 docker inspect 获取健康状态
 container = await asyncio.to_thread(
 manager._executor.client.containers.get, session.container_id
 )
 state = container.attrs.get("State", {})
 health = state.get("Health", {})
 status_str = health.get("Status", "unknown").lower
 if status_str == "healthy":
 session.health_status = SubAgentSession.HealthStatus.HEALTHY
 stats["healthy"] += 1
 elif status_str == "unhealthy":
 session.health_status = SubAgentSession.HealthStatus.UNHEALTHY
 stats["unhealthy"] += 1
 log.warning("container_unhealthy", session_id=session.session_id)
 else:
 session.health_status = SubAgentSession.HealthStatus.UNKNOWN
 session.save(update_fields=["health_status", "updated_at"])
 stats["checked"] += 1
 except docker.errors.NotFound:
 log.warning("container_not_found", session_id=session.session_id)
 except Exception as e:
 stats["errors"].append(f"{session.session_id}: {e}")
 log.exception("health_check_error", session_id=session.session_id)
 log.info("task_complete", **stats)
 return stats
async def detect_zombie_containers -> dict:
 """检测僵尸容器 — 心跳超时的 RUNNING 容器。
 使用 ZOMBIE_HEARTBEAT_SECONDS (120s) 作为判定阈值（Phase 用户决策）。
 条件：
 - status = RUNNING
 - last_heartbeat_at 非空且超过阈值
 - 或 last_heartbeat_at 为空但 started_at 超过阈值（从未发过心跳）
 Returns:
 {"zombie_count": int, "errors": list[str]}
 """
 log = logger.bind(task="detect_zombie_containers")
 log.info("task_start", timeout_seconds=ZOMBIE_HEARTBEAT_SECONDS)
 now = timezone.now
 cutoff = now - timedelta(seconds=ZOMBIE_HEARTBEAT_SECONDS)
 zombie_count = 0
 errors: list[str] =
 # Case 1: 有心跳但超时
 sessions_with_heartbeat = SubAgentSession.objects.filter(
 status=SubAgentSession.Status.RUNNING,
 last_heartbeat_at__isnull=False,
 last_heartbeat_at__lt=cutoff,
 )
 async for session in sessions_with_heartbeat:
 try:
 session.mark_timeout
 zombie_count += 1
 log.info(
 "zombie_detected",
 session_id=session.session_id,
 last_heartbeat=session.last_heartbeat_at.isoformat if session.last_heartbeat_at else "",
 reason="heartbeat_timeout",
 )
 except Exception as e:
 errors.append(f"{session.session_id}: {e!s}")
 log.exception("zombie_mark_error", session_id=session.session_id)
 # Case 2: 从未发过心跳但启动时间超过阈值
 sessions_no_heartbeat = SubAgentSession.objects.filter(
 status=SubAgentSession.Status.RUNNING,
 last_heartbeat_at__isnull=True,
 started_at__isnull=False,
 started_at__lt=cutoff,
 )
 async for session in sessions_no_heartbeat:
 try:
 session.mark_timeout
 zombie_count += 1
 log.info(
 "zombie_detected",
 session_id=session.session_id,
 started_at=session.started_at.isoformat if session.started_at else "",
 reason="no_heartbeat",
 )
 except Exception as e:
 errors.append(f"{session.session_id}: {e!s}")
 log.exception("zombie_mark_error", session_id=session.session_id)
 log.info("task_complete", zombie_count=zombie_count, error_count=len(errors))
 return {"zombie_count": zombie_count, "errors": errors}
async def cleanup_completed_containers -> dict:
 """清理已完成容器的 Docker 资源。
 委托给 ContainerManager.cleanup，它会：
 1. 查找终态且超过阈值的 session
 2. 移除对应的 Docker 容器
 3. 清空 container_id 字段
 Returns:
 {"removed_count": int}
 """
 log = logger.bind(task="cleanup_completed_containers")
 log.info("task_start", cleanup_hours=CONTAINER_CLEANUP_HOURS)
 try:
 from services.container_manager import ContainerManager
 manager = ContainerManager
 removed = await manager.cleanup(older_than_hours=CONTAINER_CLEANUP_HOURS)
 log.info("task_complete", removed_count=removed)
 return {"removed_count": removed}
 except Exception as e:
 log.exception("cleanup_error", error=str(e))
 return {"removed_count": 0, "error": str(e)}
async def enforce_task_timeouts -> dict:
 """强制终止超时容器。
 检查每个 RUNNING 状态的 SubAgentSession，如果已超过任务类型对应的超时时间，
 调用 ContainerManager.stop 优雅终止。
 Returns:
 {"stopped": int, "errors": list}
 """
 log = logger.bind(task="enforce_task_timeouts")
 log.info("task_start")
 from services.container_config import TASK_TIMEOUTS
 from services.container_manager import ContainerManager
 manager = ContainerManager
 now = timezone.now
 stats: dict[str, Any] = {"stopped": 0, "errors": }
 sessions = SubAgentSession.objects.filter(
 status=SubAgentSession.Status.RUNNING,
 started_at__isnull=False,
 )
 async for session in sessions:
 task_type = session.task_type or "coding"
 timeout_seconds = TASK_TIMEOUTS.get(task_type, 1800)
 cutoff = now - timedelta(seconds=timeout_seconds)
 if session.started_at is not None and session.started_at < cutoff:
 log.info(
 "task_timeout_enforcing",
 session_id=session.session_id,
 task_type=task_type,
 elapsed_seconds=int((now - session.started_at).total_seconds),
 )
 try:
 # 优雅终止：先 stop(timeout=30) 再 remove
 await manager.stop(session.session_id, force=False)
 session.mark_timeout
 stats["stopped"] += 1
 except Exception as e:
 stats["errors"].append(f"{session.session_id}: {e}")
 log.exception("timeout_stop_error", session_id=session.session_id)
 log.info("task_complete", **stats)
 return stats
# === 提问超时提醒（Phase）===
# 提醒配置（用户决策：每 30 分钟低频提醒）
QUESTION_REMINDER_INTERVAL_MINUTES = 30
async def remind_pending_questions -> dict:
 """提醒用户待回复的问题。
 每 30 分钟执行一次，检查未回复且距上次提醒超过 30 分钟的问题。
 发送提醒消息并更新状态。
 用户决策：
 - 无自动决策：用户不回复不自动继续
 - 提醒频率：每 30 分钟低频提醒
 - 提醒渠道：飞书消息
 - 最大等待：永不取消，任务一直等待
 Returns:
 {"reminded": int, "errors": list[str]}
 """
 from django.db import models
 from services.feishu_im import FeishuIMClient
 from subagent.models import InteractionLog
 log = logger.bind(task="remind_pending_questions")
 log.info("task_start")
 # 从 settings 获取飞书配置
 app_id = getattr(settings, "FEISHU_APP_ID", "")
 app_secret = getattr(settings, "FEISHU_APP_SECRET", "")
 if not app_id or not app_secret:
 log.warning("feishu_config_missing_skip_reminder")
 return {"reminded": 0, "errors": ["Feishu config missing"]}
 now = timezone.now
 reminder_cutoff = now - timedelta(minutes=QUESTION_REMINDER_INTERVAL_MINUTES)
 reminded_count = 0
 errors: list[str] =
 # 查找未回复且需要提醒的问题
 # 条件：answered_at 为空 AND (last_reminder_at 为空 OR 距今超过 30 分钟)
 pending_questions = InteractionLog.objects.filter(
 answered_at__isnull=True,
 ).filter(
 models.Q(last_reminder_at__isnull=True) |
 models.Q(last_reminder_at__lt=reminder_cutoff)
 ).select_related("session", "session__main_session")
 async for interaction in pending_questions:
 try:
 # 检查 session 是否仍在运行
 if interaction.session.status != SubAgentSession.Status.RUNNING:
 continue
 # 获取 chat_id
 chat_id = ""
 if interaction.session.main_session and interaction.session.main_session.metadata:
 chat_id = interaction.session.main_session.metadata.get("chat_id", "")
 if not chat_id:
 continue
 # 计算等待时间
 wait_seconds = int((now - interaction.asked_at).total_seconds)
 wait_hours = wait_seconds // 3600
 wait_minutes = (wait_seconds % 3600) // 60
 if wait_hours > 0:
 wait_str = f"{wait_hours}小时{wait_minutes}分钟"
 else:
 wait_str = f"{wait_minutes}分钟"
 # 构建提醒消息
 question_preview = interaction.question_text[:100]
 if len(interaction.question_text) > 100:
 question_preview += "..."
 reminder_text = (
 f"⏰ **任务等待中**\n\n"
 f"容器任务需要您的输入才能继续。\n\n"
 f"• 问题：{question_preview}\n"
 f"• 已等待：{wait_str}\n\n"
 f"请回复上方卡片中的问题。"
 )
 # 发送提醒消息（使用 send_message 发送文本消息）
 try:
 im_client = FeishuIMClient(app_id=app_id, app_secret=app_secret)
 await im_client.send_message(
 receive_id=chat_id,
 receive_id_type="chat_id",
 msg_type="text",
 content={"text": reminder_text},
 )
 except Exception as e:
 log.warning("reminder_send_failed", error=str(e))
 continue
 # 更新提醒状态
 interaction.reminder_count += 1
 interaction.last_reminder_at = now
 await interaction.asave(update_fields=["reminder_count", "last_reminder_at"])
 reminded_count += 1
 log.info(
 "question_reminded",
 interaction_id=interaction.id,
 reminder_count=interaction.reminder_count,
 wait_time=wait_str,
 )
 except Exception as e:
 errors.append(f"{interaction.id}: {e}")
 log.exception("remind_error", interaction_id=interaction.id)
 log.info("task_complete", reminded=reminded_count, error_count=len(errors))
 return {"reminded": reminded_count, "errors": errors}
