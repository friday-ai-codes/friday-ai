"""Django models for SubAgent session management.
SubAgentSession: Tracks SubAgent session state for session reuse
SubAgentOutput: Stores long results that exceed inline threshold
"""
import hashlib
import uuid
import warnings
from django.db import models
from django.utils import timezone
from agents.models import AgentSession
def generate_subagent_session_id(
 main_session_id: str,
 repo_url: str,
 task_type: str,
) -> str:
 """Generate SubAgent session unique identifier.
 Same main session + same repo + same task type = same ID (session reuse)
 .. deprecated:
 使用确定性哈希，重试场景会碰撞。请使用 generate_execution_id 替代。
 Args:
 main_session_id: Main Agent session ID
 repo_url: Git repository URL
 task_type: Task type (explore, ask, plan, coding)
 Returns:
 SubAgent session ID (format: sub-{hash12})
 """
 warnings.warn(
 "generate_subagent_session_id 使用确定性哈希，重试场景会碰撞。"
 "请使用 generate_execution_id 替代。",
 DeprecationWarning,
 stacklevel=2,
 )
 content = f"{main_session_id}:{repo_url}:{task_type}"
 hash_value = hashlib.sha256(content.encode).hexdigest[:12]
 return f"sub-{hash_value}"
def generate_execution_id -> str:
 """生成唯一执行 ID。
 使用 UUID4 替代确定性哈希，彻底解决 Session ID 碰撞问题。
 Returns:
 执行 ID (格式: exec-{uuid_hex[:16]})
 """
 return f"exec-{uuid.uuid4.hex[:16]}"
class SubAgentSession(models.Model):
 """SubAgent session model.
 Tracks SubAgent session state, supports session reuse.
 """
 class Status(models.TextChoices):
 IDLE = "idle", "Idle"
 PENDING = "pending", "Pending"
 RUNNING = "running", "Running"
 COMPLETED = "completed", "Completed"
 ERROR = "error", "Error"
 TIMEOUT = "timeout", "Timeout"
 CANCELLED = "cancelled", "Cancelled"
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
 # 容器追踪（Phase 新增）
 container_id = models.CharField(
 max_length=128,
 blank=True,
 default="",
 verbose_name="Docker 容器 ID",
 help_text="Docker 容器完整 ID，持久化以防服务重启后丢失映射",
 )
 container_name = models.CharField(
 max_length=255,
 blank=True,
 default="",
 verbose_name="Docker 容器名",
 help_text="格式: friday-exec-{uuid}",
 )
 node_execution = models.ForeignKey(
 "workflows.NodeExecution",
 on_delete=models.SET_NULL,
 null=True,
 blank=True,
 related_name="subagent_sessions",
 verbose_name="关联节点执行",
 )
 # 重复提交检测（Phase 新增）
 work_item_id = models.CharField(
 max_length=100,
 blank=True,
 default="",
 db_index=True,
 verbose_name="工作项 ID",
 )
 target_branch = models.CharField(
 max_length=255,
 blank=True,
 default="",
 verbose_name="目标分支",
 )
 last_output = models.JSONField(null=True, blank=True)
 last_error = models.TextField(blank=True, default="")
 # Timestamps
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 # 执行时间追踪（Phase 新增）
 started_at = models.DateTimeField(null=True, blank=True, verbose_name="开始时间")
 completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")
 # 心跳追踪（Phase 新增）
 last_heartbeat_at = models.DateTimeField(null=True, blank=True, verbose_name="最后心跳时间")
 class Meta:
 indexes = [
 models.Index(fields=["main_session", "task_type"]),
 models.Index(fields=["work_item_id", "task_type", "target_branch", "status"]),
 ]
 def __str__(self) -> str:
 return f"SubAgentSession({self.session_id}, {self.task_type}, {self.status})"
 # 状态转换辅助方法（Phase 新增）
 def mark_pending(self) -> None:
 """标记为等待容器启动。"""
 self.status = self.Status.PENDING
 self.save(update_fields=["status", "updated_at"])
 def mark_running(self, container_id: str, container_name: str) -> None:
 """标记为运行中，记录容器信息。"""
 self.status = self.Status.RUNNING
 self.container_id = container_id
 self.container_name = container_name
 self.started_at = timezone.now
 self.save(update_fields=["status", "container_id", "container_name", "started_at", "updated_at"])
 def mark_completed(self) -> None:
 """标记为已完成。"""
 self.status = self.Status.COMPLETED
 self.completed_at = timezone.now
 self.save(update_fields=["status", "completed_at", "updated_at"])
 def mark_failed(self, error: str = "") -> None:
 """标记为失败。"""
 self.status = self.Status.ERROR
 self.last_error = error
 self.completed_at = timezone.now
 self.save(update_fields=["status", "last_error", "completed_at", "updated_at"])
 def mark_timeout(self) -> None:
 """标记为超时。"""
 self.status = self.Status.TIMEOUT
 self.completed_at = timezone.now
 self.save(update_fields=["status", "completed_at", "updated_at"])
 def mark_cancelled(self) -> None:
 """标记为已取消。"""
 self.status = self.Status.CANCELLED
 self.completed_at = timezone.now
 self.save(update_fields=["status", "completed_at", "updated_at"])
 @property
 def duration_ms(self) -> int | None:
 """执行时长（毫秒）。"""
 if self.started_at and self.completed_at:
 return int((self.completed_at - self.started_at).total_seconds * 1000)
 return None
class TaskResult(models.Model):
 """统一任务结果模型（Phase）。
 替代 SubAgentSession.last_output 和 AgentSession.temp_data 中的结果存储。
 文本产物和 Git 产物通过 result_type 区分，各有独立字段。
 """
 class ResultType(models.TextChoices):
 TEXT = "text", "Text Output"
 GIT = "git", "Git Artifacts"
 # 关联 SubAgentSession
 session = models.OneToOneField(
 SubAgentSession,
 on_delete=models.CASCADE,
 related_name="task_result",
 )
 result_type = models.CharField(
 max_length=10,
 choices=ResultType.choices,
 verbose_name="结果类型",
 )
 # 文本产物（explore/ask/plan）
 text_output = models.TextField(blank=True, default="", verbose_name="文本输出")
 # Git 产物（coding）
 branch_name = models.CharField(max_length=255, blank=True, default="")
 commit_sha = models.CharField(max_length=64, blank=True, default="")
 pr_url = models.URLField(blank=True, default="")
 modified_files = models.JSONField(default=list, blank=True, verbose_name="修改文件列表")
 # 原始输出（完整 result.json 内容）
 raw_output = models.JSONField(default=dict, blank=True, verbose_name="原始输出")
 # 元数据
 duration_ms = models.IntegerField(null=True, blank=True, verbose_name="执行时长(ms)")
 created_at = models.DateTimeField(auto_now_add=True)
 class Meta:
 indexes = [
 models.Index(fields=["result_type"]),
 ]
 def __str__(self) -> str:
 return f"TaskResult({self.session.session_id}, {self.result_type})"
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
