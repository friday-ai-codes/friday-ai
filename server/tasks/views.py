"""Tasks app views."""
import logging
from django.shortcuts import get_object_or_404
from django.utils import timezone
from projects.models import Project
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from .models import Task, TaskStatus
from .serializers import (
 TaskCreateSerializer,
 TaskExecuteRequestSerializer,
 TaskExecuteResponseSerializer,
 TaskSerializer,
 TaskStatusUpdateSerializer,
 TaskUpdateSerializer,
)
logger = logging.getLogger(__name__)
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
 return queryset
 def create(self, request, *args, **kwargs):
 serializer = self.get_serializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 # Verify project exists - get from validated_data which handles ForeignKey
 validated_data = serializer.validated_data.copy
 project_id = validated_data.get("project_id") or request.data.get("project_id")
 if project_id and not Project.objects.filter(id=project_id).exists:
 return Response(
 {"detail": "Project not found"},
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
 {"detail": "Cannot start execution: task must be in PLAN_REVIEW status"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # Check repository
 if not task.repository_id:
 return Response(
 {"detail": "Task must have a repository assigned before execution."},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # TODO: Implement actual container execution
 # For now, just update status
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
 "container_id": "mock-container-id",
 "mode": mode,
 "message": f"Task execution started in {mode} mode",
 }
 ).data
 )
 @action(detail=True, methods=["post"])
 def stop(self, request, pk=None):
 """Stop task execution."""
 task = self.get_object
 # TODO: Implement actual container stop
 task.status = TaskStatus.FAILED
 task.error_message = "Task stopped by user"
 task.save
 return Response(
 {
 "status": "stopped",
 "message": "Task container stopped",
 }
 )
 @action(detail=True, methods=["get"])
 def logs(self, request, pk=None):
 """Get task container logs."""
 task = self.get_object
 tail = int(request.query_params.get("tail", 100))
 # TODO: Implement actual log retrieval
 return Response(
 {
 "task_id": str(task.id),
 "logs": "Container logs not available in Django migration phase",
 }
 )
 @action(detail=True, methods=["get"], url_path="container-status")
 def container_status(self, request, pk=None):
 """Get task container status."""
 task = self.get_object
 # TODO: Implement actual container status
 return Response(
 {
 "task_id": str(task.id),
 "container": None,
 }
 )
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
