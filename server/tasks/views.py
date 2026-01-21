import asyncio
import logging
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from repositories.models import GitCredential, Repository
from projects.models import Project
from common.encryption import decrypt_value
from services.claude_config import get_claude_config_for_task
from services.scheduler import get_scheduler
from .models import Task, TaskStatus
from .serializers import (
 TaskCreateSerializer,
 TaskExecuteRequestSerializer,
 TaskExecuteResponseSerializer,
 TaskSerializer,
 TaskStatusUpdateSerializer,
 TaskUpdateSerializer,
)
"""Tasks app views - 任务管理 API 视图。
包含完整的任务执行功能
"""
logger = logging.getLogger(__name__)
def run_async(coro):
 """运行异步协程的辅助函数。
 使用 asyncio.run 替代已弃用的 get_event_loop.run_until_complete。
 """
 return asyncio.run(coro)
class TaskViewSet(ModelViewSet):
 """ViewSet for Task CRUD operations."""
 queryset = Task.objects.all
 serializer_class = TaskSerializer
 def get_serializer_class(self):
 if self.action == "create":
 return TaskCreateSerializer
 if self.action in ["update", "partial_update"]:
 return TaskUpdateSerializer
 return TaskSerializer
 def get_queryset(self):
 queryset = Task.objects.all
 # Filter by project_id
 project_id = self.request.query_params.get("project_id")
 if project_id:
 queryset = queryset.filter(project_id=project_id)
 # Filter by status
 task_status = self.request.query_params.get("status")
 if task_status:
 queryset = queryset.filter(status=task_status)
 return queryset.order_by("-created_at")
 def create(self, request, *args, **kwargs):
 serializer = self.get_serializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 # Verify project exists - get from validated_data which handles ForeignKey
 validated_data = serializer.validated_data.copy
 project_id = validated_data.get("project_id") or request.data.get("project_id")
 if project_id and not Project.objects.filter(id=project_id).exists:
 return Response(
 {"detail": "项目未找到"},
 status=status.HTTP_404_NOT_FOUND,
 )
 # Use serializer.save for proper handling
 task = serializer.save
 return Response(
 TaskSerializer(task).data,
 status=status.HTTP_201_CREATED,
 )
 @action(detail=False, methods=["get"], url_path=r"work-item/(?P<work_item_id>[^/.]+)")
 def by_work_item(self, request, work_item_id=None):
 """Get task by work item ID."""
 task = get_object_or_404(Task, work_item_id=work_item_id)
 return Response(TaskSerializer(task).data)
 @action(detail=True, methods=["post"], url_path=r"transition/(?P<new_status>\w+)")
 def transition(self, request, pk=None, new_status=None):
 """Transition task to a new status."""
 task = self.get_object
 # Validate new status
 if new_status not in TaskStatus.values:
 return Response(
 {"detail": f"Invalid status: {new_status}"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # Check valid transition
 if not task.can_transition_to(new_status):
 allowed = Task.get_valid_transitions.get(task.status, )
 return Response(
 {
 "detail": f"Cannot transition from {task.status} to {new_status}. Allowed: {allowed}"
 },
 status=status.HTTP_400_BAD_REQUEST,
 )
 # Update timestamps based on transition
 now = timezone.now
 if new_status == TaskStatus.PLANNING and task.plan_started_at is None:
 task.plan_started_at = now
 elif new_status == TaskStatus.PLAN_REVIEW:
 task.plan_completed_at = now
 elif new_status == TaskStatus.EXECUTING and task.execute_started_at is None:
 task.execute_started_at = now
 elif new_status == TaskStatus.CODE_REVIEW:
 task.execute_completed_at = now
 elif new_status == TaskStatus.FAILED:
 task.retry_count += 1
 task.status = new_status
 task.save
 return Response(TaskSerializer(task).data)
 @action(detail=True, methods=["post"])
 def execute(self, request, pk=None):
 """Execute task in a container."""
 task = self.get_object
 serializer = TaskExecuteRequestSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 mode = serializer.validated_data["mode"]
 # Check if task can be executed
 if mode == "plan" and task.status != TaskStatus.PENDING:
 return Response(
 {"detail": f"Cannot start planning: task is in {task.status} status"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 elif mode == "execute" and task.status != TaskStatus.PLAN_REVIEW:
 return Response(
 {"detail": "无法开始执行：任务必须处于方案评审状态"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # Check repository
 if not task.repository_id:
 return Response(
 {"detail": "执行前必须先关联仓库"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # Get repository and credentials
 try:
 repository = Repository.objects.get(id=task.repository_id)
 except Repository.DoesNotExist:
 return Response(
 {"detail": "仓库未找到"},
 status=status.HTTP_404_NOT_FOUND,
 )
 git_credentials = {}
 try:
 credential = GitCredential.objects.get(repository=repository)
 if credential.ssh_key_encrypted:
 git_credentials["ssh_key"] = decrypt_value(credential.ssh_key_encrypted)
 elif credential.encrypted_token:
 git_credentials["access_token"] = decrypt_value(credential.encrypted_token)
 except GitCredential.DoesNotExist:
 pass
 # 获取 Claude 配置
 try:
 claude_config_obj = get_claude_config_for_task(str(task.project_id))
 claude_config = {
 "api_key": claude_config_obj.api_key or "",
 "base_url": claude_config_obj.base_url or "",
 }
 except ValueError as e:
 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
 # Start container
 scheduler = get_scheduler
 try:
 # 使用 asyncio.run 运行异步代码
 container_id = run_async(
 scheduler.start_task(
 task=task,
 repo_url=repository.git_url,
 branch=repository.default_branch or "main",
 git_credentials=git_credentials,
 mode=mode,
 claude_config=claude_config,
 )
 )
 except RuntimeError as e:
 return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
 # Update task status
 now = timezone.now
 if mode == "plan":
 task.status = TaskStatus.PLANNING
 task.plan_started_at = now
 else:
 task.status = TaskStatus.EXECUTING
 task.execute_started_at = now
 task.save
 return Response(
 TaskExecuteResponseSerializer(
 {
 "task_id": str(task.id),
 "container_id": container_id[:12],
 "mode": mode,
 "message": f"Task execution started in {mode} mode",
 }
 ).data
 )
 @action(detail=True, methods=["post"])
 def stop(self, request, pk=None):
 """Stop task execution."""
 task = self.get_object
 force = request.query_params.get("force", "false").lower == "true"
 scheduler = get_scheduler
 stopped = run_async(scheduler.stop_task(str(task.id), force=force))
 if stopped:
 task.status = TaskStatus.FAILED
 task.error_message = "Task stopped by user"
 task.save
 return Response({"status": "stopped", "message": "Task container stopped"})
 else:
 return Response(
 {"status": "not_found", "message": "No running container found for task"}
 )
 @action(detail=True, methods=["get"])
 def logs(self, request, pk=None):
 """Get task container logs."""
 task = self.get_object
 tail = int(request.query_params.get("tail", 100))
 scheduler = get_scheduler
 logs = run_async(scheduler.get_task_logs(str(task.id), tail=tail))
 if logs is None:
 return Response(
 {"detail": "未找到任务对应的容器"},
 status=status.HTTP_404_NOT_FOUND,
 )
 return Response({"task_id": str(task.id), "logs": logs})
 @action(detail=True, methods=["get"], url_path="container-status")
 def container_status(self, request, pk=None):
 """Get task container status."""
 task = self.get_object
 scheduler = get_scheduler
 container_status = run_async(scheduler.get_task_status(str(task.id)))
 if container_status is None:
 return Response({"task_id": str(task.id), "container": None})
 return Response({"task_id": str(task.id), "container": container_status})
class TaskStatusCallbackView(APIView):
 """View for task status callback from container."""
 permission_classes = [AllowAny] # Container callback doesn't use auth
 def post(self, request, task_id):
 """Receive status update from task container."""
 serializer = TaskStatusUpdateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 try:
 task = Task.objects.get(id=task_id)
 except Task.DoesNotExist:
 logger.warning(
 "Received status update for unknown task",
 extra={
 "task_id": task_id,
 "status": serializer.validated_data.get("status"),
 },
 )
 return Response(
 {
 "status": "ignored",
 "reason": "task not found",
 "task_id": task_id,
 }
 )
 update_status = serializer.validated_data.get("status")
 details = serializer.validated_data.get("details", {}) or {}
 now = timezone.now
 # Handle different status updates
 if update_status == "plan_ready":
 task.status = TaskStatus.PLAN_REVIEW
 task.plan_completed_at = now
 task.plan_output = details.get("plan", "")
 elif update_status == "execution_complete":
 task.status = TaskStatus.CODE_REVIEW
 task.execute_completed_at = now
 task.branch_name = details.get("branch_name")
 task.commit_sha = details.get("commit_sha")
 elif update_status == "error":
 task.status = TaskStatus.FAILED
 task.error_message = serializer.validated_data.get("message")
 task.retry_count += 1
 task.save
 return Response(
 {
 "status": "ok",
 "task_status": task.status,
 }
 )
