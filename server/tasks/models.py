"""Tasks app models."""
import uuid
from django.db import models
from projects.models import Project, Repository
class TaskStatus(models.TextChoices):
 """Task status choices."""
 PENDING = "pending", "待处理"
 PLANNING = "planning", "规划中"
 PLAN_REVIEW = "plan_review", "方案评审"
 EXECUTING = "executing", "执行中"
 CODE_REVIEW = "code_review", "代码评审"
 MERGED = "merged", "已合并"
 FAILED = "failed", "失败"
class Task(models.Model):
 """Task model for AI development tasks."""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 project = models.ForeignKey(
 Project,
 on_delete=models.CASCADE,
 related_name="tasks",
 )
 repository = models.ForeignKey(
 Repository,
 on_delete=models.SET_NULL,
 null=True,
 blank=True,
 related_name="tasks",
 )
 # Feishu integration
 work_item_id = models.CharField(max_length=100, unique=True)
 feature_id = models.CharField(max_length=100, blank=True, null=True)
 # Task info
 title = models.CharField(max_length=500)
 description = models.TextField(blank=True, null=True)
 # Git info
 branch_name = models.CharField(max_length=200, blank=True, null=True)
 commit_sha = models.CharField(max_length=40, blank=True, null=True)
 pr_url = models.CharField(max_length=500, blank=True, null=True)
 # Claude Code session
 session_id = models.CharField(max_length=100, blank=True, null=True)
 plan_output = models.TextField(blank=True, null=True)
 # Status
 status = models.CharField(
 max_length=20,
 choices=TaskStatus.choices,
 default=TaskStatus.PENDING,
 )
 human_feedback = models.TextField(blank=True, null=True)
 error_message = models.TextField(blank=True, null=True)
 retry_count = models.IntegerField(default=0)
 # Timestamps
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 plan_started_at = models.DateTimeField(null=True, blank=True)
 plan_completed_at = models.DateTimeField(null=True, blank=True)
 execute_started_at = models.DateTimeField(null=True, blank=True)
 execute_completed_at = models.DateTimeField(null=True, blank=True)
 class Meta:
 db_table = "tasks"
 verbose_name = "任务"
 verbose_name_plural = "任务"
 ordering = ["-created_at"]
 def __str__(self):
 return f"{self.title} ({self.status})"
 @classmethod
 def get_valid_transitions(cls):
 """Get valid status transitions."""
 return {
 TaskStatus.PENDING: [TaskStatus.PLANNING, TaskStatus.FAILED],
 TaskStatus.PLANNING: [TaskStatus.PLAN_REVIEW, TaskStatus.FAILED],
 TaskStatus.PLAN_REVIEW: [TaskStatus.PLANNING, TaskStatus.EXECUTING],
 TaskStatus.EXECUTING: [TaskStatus.CODE_REVIEW, TaskStatus.FAILED],
 TaskStatus.CODE_REVIEW: [TaskStatus.EXECUTING, TaskStatus.MERGED],
 TaskStatus.FAILED: [TaskStatus.PENDING],
 TaskStatus.MERGED:, # Terminal state
 }
 def can_transition_to(self, new_status: str) -> bool:
 """Check if transition to new status is valid."""
 valid_transitions = self.get_valid_transitions
 allowed = valid_transitions.get(self.status, )
 return new_status in allowed
