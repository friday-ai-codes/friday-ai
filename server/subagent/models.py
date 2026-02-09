"""Django models for SubAgent session management.
SubAgentSession: Tracks SubAgent session state for session reuse
SubAgentOutput: Stores long results that exceed inline threshold
"""
import hashlib
from django.db import models
from agents.models import AgentSession
def generate_subagent_session_id(
 main_session_id: str,
 repo_url: str,
 task_type: str,
) -> str:
 """Generate SubAgent session unique identifier.
 Same main session + same repo + same task type = same ID (session reuse)
 Args:
 main_session_id: Main Agent session ID
 repo_url: Git repository URL
 task_type: Task type (explore, ask, plan, coding)
 Returns:
 SubAgent session ID (format: sub-{hash12})
 """
 content = f"{main_session_id}:{repo_url}:{task_type}"
 hash_value = hashlib.sha256(content.encode).hexdigest[:12]
 return f"sub-{hash_value}"
class SubAgentSession(models.Model):
 """SubAgent session model.
 Tracks SubAgent session state, supports session reuse.
 """
 class Status(models.TextChoices):
 IDLE = "idle", "Idle"
 RUNNING = "running", "Running"
 COMPLETED = "completed", "Completed"
 ERROR = "error", "Error"
 class TaskType(models.TextChoices):
 EXPLORE = "explore", "Explore Repository"
 ASK = "ask", "Ask Question"
 PLAN = "plan", "Generate Plan"
 CODING = "coding", "Coding Task"
 # Unique identifier (sub-{hash})
 session_id = models.CharField(max_length=64, unique=True, db_index=True)
 # Relationship to main Agent session
 main_session = models.ForeignKey(
 AgentSession,
 on_delete=models.CASCADE,
 related_name="subagent_sessions",
 )
 # Repository info
 repo_url = models.URLField
 # Task type (explore, ask, plan, coding)
 task_type = models.CharField(
 max_length=20,
 choices=TaskType.choices,
 )
 # Status tracking
 status = models.CharField(
 max_length=20,
 choices=Status.choices,
 default=Status.IDLE,
 )
 # Current task tracking
 current_task_id = models.CharField(max_length=64, blank=True, default="")
 last_output = models.JSONField(null=True, blank=True)
 last_error = models.TextField(blank=True, default="")
 # Timestamps
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 indexes = [
 models.Index(fields=["main_session", "task_type"]),
 ]
 def __str__(self) -> str:
 return f"SubAgentSession({self.session_id}, {self.task_type}, {self.status})"
class SubAgentOutput(models.Model):
 """Stores long SubAgent results.
 When output exceeds MAX_INLINE_OUTPUT_LENGTH (50KB),
 store full result here and return summary + reference.
 """
 # Task identifier
 task_id = models.CharField(max_length=64, db_index=True)
 # Related main session
 session = models.ForeignKey(
 AgentSession,
 on_delete=models.CASCADE,
 related_name="subagent_outputs",
 )
 # Full output content
 full_output = models.JSONField
 # Timestamp
 created_at = models.DateTimeField(auto_now_add=True)
 class Meta:
 ordering = ["-created_at"]
 def __str__(self) -> str:
 return f"SubAgentOutput({self.task_id})"
