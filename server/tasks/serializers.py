"""Tasks app serializers."""
from rest_framework import serializers
from .models import Task, TaskStatus
class TaskSerializer(serializers.ModelSerializer):
 """Serializer for Task model."""
 class Meta:
 model = Task
 fields = [
 "id", "project_id", "repository_id", "work_item_id", "feature_id",
 "title", "description", "branch_name", "commit_sha", "pr_url",
 "session_id", "plan_output", "status", "human_feedback",
 "error_message", "retry_count", "created_at", "updated_at",
 "plan_started_at", "plan_completed_at", "execute_started_at",
 "execute_completed_at",
 ]
 read_only_fields = ["id", "created_at", "updated_at"]
class TaskCreateSerializer(serializers.ModelSerializer):
 """Serializer for creating Task."""
 project_id = serializers.UUIDField
 repository_id = serializers.UUIDField(required=False, allow_null=True)
 class Meta:
 model = Task
 fields = ["project_id", "repository_id", "work_item_id", "feature_id", "title", "description"]
 def validate_work_item_id(self, value):
 if Task.objects.filter(work_item_id=value).exists:
 raise serializers.ValidationError(f"Task with work_item_id {value} already exists")
 return value
 def create(self, validated_data):
 from projects.models import Project, Repository
 project_id = validated_data.pop("project_id")
 repository_id = validated_data.pop("repository_id", None)
 project = Project.objects.get(id=project_id)
 repository = Repository.objects.get(id=repository_id) if repository_id else None
 return Task.objects.create(
 project=project,
 repository=repository,
 **validated_data
 )
class TaskUpdateSerializer(serializers.ModelSerializer):
 """Serializer for updating Task."""
 class Meta:
 model = Task
 fields = ["repository_id", "title", "description", "human_feedback"]
 extra_kwargs = {field: {"required": False} for field in fields}
class TaskExecuteRequestSerializer(serializers.Serializer):
 """Serializer for task execution request."""
 mode = serializers.ChoiceField(choices=["plan", "execute"], default="plan")
class TaskExecuteResponseSerializer(serializers.Serializer):
 """Serializer for task execution response."""
 task_id = serializers.CharField
 container_id = serializers.CharField
 mode = serializers.CharField
 message = serializers.CharField
class TaskStatusUpdateSerializer(serializers.Serializer):
 """Serializer for task status update from container."""
 task_id = serializers.CharField
 status = serializers.CharField
 message = serializers.CharField(required=False, allow_null=True)
 details = serializers.DictField(required=False, allow_null=True)
 timestamp = serializers.CharField(required=False, allow_null=True)
