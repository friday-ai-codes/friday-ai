"""编排运行模型 — graph state 的 DB 投影。"""
import uuid
from django.db import models
class OrchestrationRun(models.Model):
 """编排运行实例 — graph state 的 DB 投影。
 每次用户发消息创建一个。状态始终从 graph checkpoint 派生，
 不独立维护状态机。
 """
 class Status(models.TextChoices):
 PENDING = "pending", "待处理"
 RUNNING = "running", "运行中"
 WAITING = "waiting", "等待中"
 INTERRUPTED = "interrupted", "已中断"
 COMPLETED = "completed", "已完成"
 ERROR = "error", "错误"
 class Phase(models.TextChoices):
 PLANNING = "planning", "规划"
 EXECUTING = "executing", "执行"
 WAITING = "waiting", "等待"
 FINALIZING = "finalizing", "收尾"
 COMPLETED = "completed", "完成"
 ERROR = "error", "错误"
 run_id = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
 conversation = models.ForeignKey(
 "chat.Conversation",
 on_delete=models.CASCADE,
 related_name="orchestration_runs",
 )
 thread_id = models.CharField(
 max_length=255,
 db_index=True,
 help_text="LangGraph thread_id，等于 str(conversation.id)",
 )
 status = models.CharField(
 max_length=20,
 choices=Status.choices,
 default=Status.PENDING,
 db_index=True,
 )
 phase = models.CharField(
 max_length=20,
 choices=Phase.choices,
 default=Phase.PLANNING,
 )
 checkpoint_id = models.CharField(
 max_length=255,
 blank=True,
 default="",
 help_text="最新 LangGraph checkpoint ID",
 )
 metadata = models.JSONField(default=dict, blank=True)
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 ordering = ["-created_at"]
 indexes = [
 models.Index(fields=["conversation", "-created_at"]),
 models.Index(fields=["thread_id", "status"]),
 ]
 verbose_name = "编排运行"
 verbose_name_plural = "编排运行"
 def __str__(self) -> str:
 return f"OrchestrationRun({self.run_id}, {self.status})"
