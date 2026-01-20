"""Webhooks app views - 飞书和 GitHub Webhook 事件处理。
包含完整的事件处理逻辑，迁移自 FastAPI 版本。
"""
import asyncio
import json
import logging
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from projects.models import Project
from services.feishu import create_feishu_client_for_project, verify_webhook_token
from tasks.models import Task, TaskStatus
from .models import WebhookLog, WebhookLogStatus, WorkItemLog
logger = logging.getLogger(__name__)
def run_async(coro):
 """运行异步协程的辅助函数。
 使用 asyncio.run 替代已弃用的 get_event_loop.run_until_complete。
 """
 return asyncio.run(coro)
# 幂等处理：存储已处理的事件 UUID
# 注意：生产环境应使用 Redis 或数据库存储
_processed_events = set
_MAX_PROCESSED_EVENTS = 10000
def is_event_processed(event_uuid: str) -> bool:
 """检查事件是否已处理（幂等性检查）。"""
 return event_uuid in _processed_events
def mark_event_processed(event_uuid: str) -> None:
 """标记事件已处理。"""
 if len(_processed_events) >= _MAX_PROCESSED_EVENTS:
 # 简单策略：清除一半旧记录
 to_remove = list(_processed_events)[: _MAX_PROCESSED_EVENTS // 2]
 for uuid in to_remove:
 _processed_events.discard(uuid)
 _processed_events.add(event_uuid)
class FeishuWebhookView(APIView):
 """Handle Feishu webhook events.
 支持的事件类型：
 - URL 验证挑战
 - WorkitemCreateEvent: 创建工作项
 - WorkitemStatusEvent: 工作项状态变更
 - WorkFlowNodeStatusEvent: 工作项节点流转
 - WorkitemCommentEvent: 工作项评论
 - WorkitemUpdateEvent: 工作项字段修改
 """
 permission_classes = [AllowAny]
 def post(self, request):
 raw_body = request.body.decode("utf-8")
 try:
 data = json.loads(raw_body)
 except json.JSONDecodeError:
 return Response(
 {"detail": "无效的 JSON 格式"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # Handle URL verification challenge
 if data.get("type") == "url_verification":
 return Response({"challenge": data.get("challenge", "")})
 # Parse webhook request
 header = data.get("header", {})
 payload = data.get("payload", {})
 if not header or not payload:
 WebhookLog.objects.create(
 raw_request=raw_body,
 event_type="",
 status=WebhookLogStatus.IGNORED,
 error_message="缺少 header 或 payload",
 )
 return Response({"status": "ignored", "reason": "缺少 header 或 payload"})
 event_uuid = header.get("uuid")
 event_type = header.get("event_type", "")
 # Idempotency check
 if event_uuid and is_event_processed(event_uuid):
 WebhookLog.objects.create(
 raw_request=raw_body,
 event_uuid=event_uuid,
 event_type=event_type,
 status=WebhookLogStatus.DUPLICATE,
 )
 return Response({"status": "duplicate", "uuid": event_uuid})
 # Get project
 project_key = payload.get("project_key") or payload.get("project_simple_name")
 if not project_key:
 WebhookLog.objects.create(
 raw_request=raw_body,
 event_uuid=event_uuid,
 event_type=event_type,
 status=WebhookLogStatus.IGNORED,
 error_message="缺少 project_key",
 )
 return Response({"status": "ignored", "reason": "缺少 project_key"})
 try:
 project = Project.objects.prefetch_related("repositories").get(
 feishu_project_key=project_key
 )
 except Project.DoesNotExist:
 WebhookLog.objects.create(
 raw_request=raw_body,
 event_uuid=event_uuid,
 event_type=event_type,
 project_key=project_key,
 status=WebhookLogStatus.IGNORED,
 error_message=f"项目未配置: {project_key}",
 )
 return Response({"status": "ignored", "reason": f"项目未配置: {project_key}"})
 # Verify webhook token
 token = header.get("token", "")
 if project.feishu_webhook_token and not verify_webhook_token(
 token, project.feishu_webhook_token
 ):
 WebhookLog.objects.create(
 raw_request=raw_body,
 event_uuid=event_uuid,
 event_type=event_type,
 project_key=project_key,
 project=project,
 status=WebhookLogStatus.ERROR,
 error_message="Token 验证失败",
 )
 return Response(
 {"detail": "Token 验证失败"},
 status=status.HTTP_401_UNAUTHORIZED,
 )
 # Mark as processed
 if event_uuid:
 mark_event_processed(event_uuid)
 # Log successful receipt
 WebhookLog.objects.create(
 raw_request=raw_body,
 event_uuid=event_uuid,
 event_type=event_type,
 project_key=project_key,
 project=project,
 status=WebhookLogStatus.ACCEPTED,
 )
 logger.info(f"处理事件: {event_type}, 项目: {project_key}, UUID: {event_uuid}")
 # 根据事件类型处理
 if event_type == "WorkitemCreateEvent":
 self._handle_workitem_create(project, payload)
 elif event_type == "WorkitemStatusEvent":
 self._handle_workitem_status(project, payload)
 elif event_type == "WorkFlowNodeStatusEvent":
 self._handle_workflow_node_status(project, payload)
 elif event_type == "WorkitemCommentEvent":
 self._handle_workitem_comment(project, payload)
 elif event_type == "WorkitemUpdateEvent":
 self._handle_workitem_update(project, payload)
 else:
 logger.info(f"未处理的事件类型: {event_type}")
 return Response({"status": "ignored", "event_type": event_type})
 return Response(
 {
 "status": "accepted",
 "event_type": event_type,
 "uuid": event_uuid,
 }
 )
 def _handle_workitem_create(self, project: Project, payload: dict):
 """处理工作项创建事件。"""
 work_item_id = payload.get("id")
 work_item_name = payload.get("name", "")
 work_item_type = payload.get("work_item_type_key", "story")
 if not work_item_id:
 logger.warning("工作项创建事件缺少 id")
 return
 # 检查任务是否已存在
 if Task.objects.filter(work_item_id=str(work_item_id)).exists:
 logger.info(f"任务已存在: {work_item_id}")
 return
 # 获取工作项详情
 description = ""
 try:
 feishu_client = create_feishu_client_for_project(project)
 work_item_info = run_async(
 feishu_client.get_work_item(
 project_key=project.feishu_project_key or "",
 work_item_id=work_item_id,
 work_item_type=work_item_type,
 )
 )
 description = work_item_info.description
 work_item_name = work_item_info.name or work_item_name
 # 保存工作项日志
 if work_item_info.raw_response:
 WorkItemLog.objects.create(
 raw_response=work_item_info.raw_response,
 work_item_id=str(work_item_id),
 work_item_type=work_item_type,
 project_key=project.feishu_project_key,
 project=project,
 )
 except Exception as e:
 logger.error(f"获取工作项详情失败: {e}")
 # 尝试自动关联仓库
 repository_id = None
 repositories = list(project.repositories.all)
 if len(repositories) == 1:
 repository_id = repositories[0].id
 logger.info(f"自动关联唯一仓库: {repositories[0].name}")
 elif len(repositories) > 1:
 logger.info("项目关联多个仓库，需手动指定任务仓库")
 else:
 logger.warning("项目未关联任何仓库，无法自动关联")
 # 创建新任务
 with transaction.atomic:
 Task.objects.create(
 project=project,
 repository_id=repository_id,
 work_item_id=str(work_item_id),
 feature_id=str(work_item_id),
 title=work_item_name,
 description=description,
 status=TaskStatus.PENDING,
 )
 logger.info(f"已创建任务: {work_item_id}")
 def _handle_workitem_status(self, project: Project, payload: dict):
 """处理工作项状态变更事件。"""
 work_item_id = payload.get("id")
 work_item_name = payload.get("name", "")
 work_item_type = payload.get("work_item_type_key", "story")
 cur_status = payload.get("cur_work_item_status", {})
 pre_status = payload.get("pre_work_item_status", {})
 if not work_item_id:
 logger.warning("工作项状态变更事件缺少 id")
 return
 cur_state_key = cur_status.get("state_key", "")
 pre_state_key = pre_status.get("state_key", "")
 logger.info(f"状态变更: {work_item_id} {pre_state_key} -> {cur_state_key}")
 # 查找任务
 try:
 task = Task.objects.get(work_item_id=str(work_item_id))
 except Task.DoesNotExist:
 # 如果任务不存在，自动创建
 logger.info(f"任务不存在，自动创建: {work_item_id}")
 self._handle_workitem_create(project, payload)
 try:
 task = Task.objects.get(work_item_id=str(work_item_id))
 except Task.DoesNotExist:
 return
 # 根据飞书状态更新任务状态
 if "planning" in cur_state_key.lower or "规划" in cur_state_key.lower:
 if task.status == TaskStatus.PENDING:
 task.status = TaskStatus.PLANNING
 task.save
 logger.info(f"任务状态更新为 PLANNING: {task.id}")
 elif "doing" in cur_state_key.lower or "进行中" in cur_state_key.lower:
 if task.status == TaskStatus.PLAN_REVIEW:
 task.status = TaskStatus.EXECUTING
 task.save
 logger.info(f"任务状态更新为 EXECUTING: {task.id}")
 elif "review" in cur_state_key.lower or "评审" in cur_state_key.lower:
 if task.status == TaskStatus.EXECUTING:
 task.status = TaskStatus.CODE_REVIEW
 task.save
 logger.info(f"任务状态更新为 CODE_REVIEW: {task.id}")
 def _handle_workflow_node_status(self, project: Project, payload: dict):
 """处理工作项节点流转事件。"""
 work_item_id = payload.get("id")
 nodes = payload.get("nodes", )
 status_change_type = payload.get("status_change_type", "")
 if not work_item_id:
 return
 logger.info(f"节点流转: {work_item_id}, 类型: {status_change_type}")
 # 节点流转事件的处理逻辑可以根据具体业务需求实现
 def _handle_workitem_comment(self, project: Project, payload: dict):
 """处理工作项评论事件。"""
 work_item_id = payload.get("id")
 comment = payload.get("comment", "")
 if not work_item_id or not comment:
 return
 # 解析评论内容，检查审批/驳回关键词
 comment_lower = comment.lower
 approval_keywords = ["通过", "批准", "approved", "lgtm", "ok", "👍"]
 rejection_keywords = ["驳回", "拒绝", "rejected", "需要修改", "不通过", "👎"]
 is_approved = any(kw in comment_lower for kw in approval_keywords)
 is_rejected = any(kw in comment_lower for kw in rejection_keywords)
 if not is_approved and not is_rejected:
 return
 logger.info(f"评论审批: {work_item_id}, 通过={is_approved}, 驳回={is_rejected}")
 try:
 task = Task.objects.get(work_item_id=str(work_item_id))
 except Task.DoesNotExist:
 return
 # 根据当前状态和评论内容更新任务
 if task.status == TaskStatus.PLAN_REVIEW:
 if is_approved:
 task.status = TaskStatus.EXECUTING
 task.human_feedback = None
 task.save
 logger.info(f"方案审批通过，开始执行: {task.id}")
 elif is_rejected:
 task.human_feedback = comment
 task.status = TaskStatus.PLANNING
 task.save
 logger.info(f"方案审批驳回，重新规划: {task.id}")
 elif task.status == TaskStatus.CODE_REVIEW:
 if is_approved:
 logger.info(f"代码审批通过: {task.id}")
 elif is_rejected:
 task.human_feedback = comment
 task.status = TaskStatus.EXECUTING
 task.save
 logger.info(f"代码审批驳回，继续开发: {task.id}")
 def _handle_workitem_update(self, project: Project, payload: dict):
 """处理工作项字段修改事件。"""
 work_item_id = payload.get("id")
 changed_fields = payload.get("changed_fields", ) or
 if not work_item_id:
 return
 logger.info(f"字段变更: {work_item_id}, 字段数: {len(changed_fields)}")
 # 可以根据需要同步字段变更到任务
class GitHubWebhookView(APIView):
 """Handle GitHub webhook events（PR 合并）。"""
 permission_classes = [AllowAny]
 def post(self, request):
 raw_body = request.body.decode("utf-8")
 try:
 data = json.loads(raw_body)
 except json.JSONDecodeError:
 return Response(
 {"detail": "无效的 JSON 格式"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 action = data.get("action", "")
 pull_request = data.get("pull_request", {})
 # Handle PR merge
 if action == "closed" and pull_request.get("merged"):
 branch = pull_request.get("head", {}).get("ref", "")
 pr_url = pull_request.get("html_url", "")
 self._handle_pr_merged(branch, pr_url)
 return Response({"status": "accepted"})
 def _handle_pr_merged(self, branch: str, pr_url: str):
 """处理 PR 合并事件 - 更新任务为 MERGED 状态。"""
 try:
 task = Task.objects.select_related("project").get(branch_name=branch)
 except Task.DoesNotExist:
 logger.info(f"未找到对应分支的任务: {branch}")
 return
 if task.status == TaskStatus.CODE_REVIEW:
 task.status = TaskStatus.MERGED
 task.pr_url = pr_url
 task.save
 logger.info(f"任务已合并: {task.id}, PR: {pr_url}")
 # 更新飞书状态
 project = task.project
 if project.has_feishu_config:
 try:
 feishu_client = create_feishu_client_for_project(project)
 run_async(
 feishu_client.transition_status(
 project_key=project.feishu_project_key or "",
 work_item_id=int(task.work_item_id),
 work_item_type="story",
 target_status_name="已完成",
 )
 )
 logger.info(f"已更新飞书状态为已完成: {task.work_item_id}")
 except Exception as e:
 logger.error(f"更新飞书状态失败: {e}")
