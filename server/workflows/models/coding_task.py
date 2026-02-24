"""CodingTask model - the canonical location for AI coding tasks.
Architecture Note:
This is the ONLY CodingTask model in the codebase. The legacy server/tasks/
app has been removed as of 2026-02-01. All AI coding task functionality
is now managed through the Workflow system.
Historical context:
- Originally, there were two systems: Task (standalone) and Workflow (DAG-based)
- The Task system was deprecated and removed to simplify architecture
- CodingTask is created by AI coding dispatcher nodes within Workflows
"""
import uuid
from django.db import models
class CodingTaskStatus(models.TextChoices):
 """编码任务状态"""
 PENDING = "pending", "待执行"
 PLANNING = "planning", "规划中"
 PLAN_REVIEW = "plan_review", "方案评审"
 EXECUTING = "executing", "执行中"
 CODE_REVIEW = "code_review", "代码评审"
 PARTIAL_SUCCESS = "partial_success", "部分成功"
 MERGED = "merged", "已合并"
 FAILED = "failed", "失败"
 CANCELLED = "cancelled", "已取消"
class CodingTask(models.Model):
 """AI 编码任务 (Canonical Location)
 由 AI 编码指派器节点创建，存储编码任务的 Prompt、状态和 Git 产物。
 Usage:
 - 此模型由 Workflow 系统中的 AI 编码指派器节点创建
 - 每个 CodingTask 关联到一个 WorkflowExecution
 - 状态流转: PENDING → PLANNING → PLAN_REVIEW → EXECUTING → CODE_REVIEW → MERGED
 """
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 # 关联
 workflow_execution = models.ForeignKey(
 "workflows.WorkflowExecution",
 on_delete=models.CASCADE,
 related_name="coding_tasks",
 verbose_name="工作流执行",
 )
 repository = models.ForeignKey(
 "repositories.Repository",
 on_delete=models.CASCADE,
 related_name="coding_tasks",
 verbose_name="代码仓库",
 )
 # 任务信息
 name = models.CharField(
 max_length=200,
 verbose_name="任务名称",
 )
 prompt = models.TextField(
 verbose_name="AI 编码 Prompt",
 help_text="发送给 AI 的编码指令",
 )
 description = models.TextField(
 blank=True,
 default="",
 verbose_name="任务描述",
 )
 # 状态
 status = models.CharField(
 max_length=20,
 choices=CodingTaskStatus.choices,
 default=CodingTaskStatus.PENDING,
 verbose_name="状态",
 )
 # AI 执行信息
 session_id = models.CharField(
 max_length=100,
 blank=True,
 default="",
 verbose_name="Claude Code 会话 ID",
 )
 plan_output = models.TextField(
 blank=True,
 default="",
 verbose_name="规划输出",
 help_text="AI 规划阶段的输出内容",
 )
 human_feedback = models.TextField(
 blank=True,
 default="",
 verbose_name="人工反馈",
 help_text="人工评审时的反馈意见",
 )
 # Git 产物
 branch_name = models.CharField(
 max_length=200,
 blank=True,
 default="",
 verbose_name="Git 分支名",
 )
 commit_sha = models.CharField(
 max_length=40,
 blank=True,
 default="",
 verbose_name="提交哈希",
 )
 pr_url = models.URLField(
 blank=True,
 default="",
 verbose_name="PR 链接",
 )
 # 错误处理
 error_message = models.TextField(
 blank=True,
 default="",
 verbose_name="错误信息",
 )
 retry_count = models.PositiveIntegerField(
 default=0,
 verbose_name="重试次数",
 )
 # 元数据
 metadata = models.JSONField(
 default=dict,
 blank=True,
 verbose_name="元数据",
 help_text="存储额外信息，如分析结果、关联的需求字段等",
 )
 # 执行计划追踪字段
 execution_plan_ids = models.JSONField(
 default=list,
 blank=True,
 verbose_name="关联的执行计划项 ID",
 help_text="从技术方案 execution_plan 合并的任务 ID 列表",
 )
 global_context_snapshot = models.TextField(
 blank=True,
 default="",
 verbose_name="全局上下文快照",
 help_text="任务创建时的 global_context，用于重试",
 )
 execution_log = models.TextField(
 blank=True,
 default="",
 verbose_name="执行日志",
 help_text="完整的 AI 编码执行日志",
 )
 # 时间戳
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 started_at = models.DateTimeField(null=True, blank=True, verbose_name="开始时间")
 completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")
 class Meta:
 db_table = "coding_tasks"
 verbose_name = "编码任务"
 verbose_name_plural = "编码任务"
 ordering = ["-created_at"]
 indexes = [
 models.Index(fields=["workflow_execution", "status"]),
 models.Index(fields=["repository", "status"]),
 models.Index(fields=["status", "created_at"]),
 ]
 def __str__(self) -> str:
 return f"{self.name} ({self.repository.name})"
 @property
 def duration(self) -> float | None:
 """执行时长（秒）"""
 if self.started_at and self.completed_at:
 return (self.completed_at - self.started_at).total_seconds
 return None
 def mark_planning(self) -> None:
 """标记开始规划"""
 from django.utils import timezone
 self.status = CodingTaskStatus.PLANNING
 self.started_at = timezone.now
 self.save(update_fields=["status", "started_at"])
 async def amark_planning(self) -> None:
 """标记开始规划（async 版本）"""
 from django.utils import timezone
 self.status = CodingTaskStatus.PLANNING
 self.started_at = timezone.now
 await self.asave(update_fields=["status", "started_at"])
 def mark_plan_review(self, plan_output: str) -> None:
 """标记等待方案评审"""
 self.status = CodingTaskStatus.PLAN_REVIEW
 self.plan_output = plan_output
 self.save(update_fields=["status", "plan_output"])
 async def amark_plan_review(self, plan_output: str) -> None:
 """标记等待方案评审（async 版本）"""
 self.status = CodingTaskStatus.PLAN_REVIEW
 self.plan_output = plan_output
 await self.asave(update_fields=["status", "plan_output"])
 def mark_executing(self) -> None:
 """标记开始执行"""
 self.status = CodingTaskStatus.EXECUTING
 self.save(update_fields=["status"])
 async def amark_executing(self) -> None:
 """标记开始执行（async 版本）"""
 self.status = CodingTaskStatus.EXECUTING
 await self.asave(update_fields=["status"])
 def mark_code_review(self, branch_name: str, commit_sha: str, pr_url: str = "") -> None:
 """标记等待代码评审"""
 self.status = CodingTaskStatus.CODE_REVIEW
 self.branch_name = branch_name
 self.commit_sha = commit_sha
 self.pr_url = pr_url
 self.save(update_fields=["status", "branch_name", "commit_sha", "pr_url"])
 async def amark_code_review(self, branch_name: str, commit_sha: str, pr_url: str = "") -> None:
 """标记等待代码评审（async 版本）"""
 self.status = CodingTaskStatus.CODE_REVIEW
 self.branch_name = branch_name
 self.commit_sha = commit_sha
 self.pr_url = pr_url
 await self.asave(update_fields=["status", "branch_name", "commit_sha", "pr_url"])
 def mark_merged(self) -> None:
 """标记已合并"""
 from django.utils import timezone
 self.status = CodingTaskStatus.MERGED
 self.completed_at = timezone.now
 self.save(update_fields=["status", "completed_at"])
 async def amark_merged(self) -> None:
 """标记已合并（async 版本）"""
 from django.utils import timezone
 self.status = CodingTaskStatus.MERGED
 self.completed_at = timezone.now
 await self.asave(update_fields=["status", "completed_at"])
 def mark_failed(self, error: str) -> None:
 """标记失败"""
 from django.utils import timezone
 self.status = CodingTaskStatus.FAILED
 self.error_message = error
 self.completed_at = timezone.now
 self.retry_count += 1
 self.save(update_fields=["status", "error_message", "completed_at", "retry_count"])
 async def amark_failed(self, error: str) -> None:
 """标记失败（async 版本）"""
 from django.utils import timezone
 self.status = CodingTaskStatus.FAILED
 self.error_message = error
 self.completed_at = timezone.now
 self.retry_count += 1
 await self.asave(update_fields=["status", "error_message", "completed_at", "retry_count"])
 def add_feedback(self, feedback: str) -> None:
 """添加人工反馈"""
 if self.human_feedback:
 self.human_feedback += f"\n---\n{feedback}"
 else:
 self.human_feedback = feedback
 self.save(update_fields=["human_feedback"])
 async def aadd_feedback(self, feedback: str) -> None:
 """添加人工反馈（async 版本）"""
 if self.human_feedback:
 self.human_feedback += f"\n---\n{feedback}"
 else:
 self.human_feedback = feedback
 await self.asave(update_fields=["human_feedback"])
 def append_log(self, message: str) -> None:
 """追加带时间戳的日志条目到执行日志"""
 from django.utils import timezone
 timestamp = timezone.now.strftime("%Y-%m-%d %H:%M:%S")
 log_entry = f"[{timestamp}] {message}"
 if self.execution_log:
 self.execution_log += f"\n{log_entry}"
 else:
 self.execution_log = log_entry
 self.save(update_fields=["execution_log", "updated_at"])
 def mark_partial_success(self, branch_name: str, commit_sha: str, error: str) -> None:
 """标记部分成功（推送成功但 MR 创建失败）"""
 from django.utils import timezone
 self.status = CodingTaskStatus.PARTIAL_SUCCESS
 self.branch_name = branch_name
 self.commit_sha = commit_sha
 self.error_message = error
 self.completed_at = timezone.now
 self.save(
 update_fields=["status", "branch_name", "commit_sha", "error_message", "completed_at"]
 )
 async def amark_partial_success(self, branch_name: str, commit_sha: str, error: str) -> None:
 """标记部分成功（async 版本）"""
 from django.utils import timezone
 self.status = CodingTaskStatus.PARTIAL_SUCCESS
 self.branch_name = branch_name
 self.commit_sha = commit_sha
 self.error_message = error
 self.completed_at = timezone.now
 await self.asave(
 update_fields=["status", "branch_name", "commit_sha", "error_message", "completed_at"]
 )
 def set_pr_url(self, pr_url: str) -> None:
 """设置 MR/PR URL"""
 self.pr_url = pr_url
 self.save(update_fields=["pr_url", "updated_at"])
