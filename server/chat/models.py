"""对话数据模型：Conversation 和 Message。
定义对话系统的核心数据结构。Conversation 绑定 Project，
Message 支持 user/assistant/system/tool 四种角色，
用于存储完整的对话历史（含工具调用记录）。
"""
import uuid
from django.conf import settings
from django.db import models
from projects.models import Project
class Conversation(models.Model):
 """对话模型 — 一次完整的用户-AI 交互会话。"""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 project = models.ForeignKey(
 Project,
 on_delete=models.CASCADE,
 related_name="conversations",
 )
 title = models.CharField(max_length=200, default="新对话")
 model = models.CharField(
 max_length=100,
 blank=True,
 default="",
 help_text="LLM 模型 ID，为空时使用系统默认模型",
 )
 provider_type = models.CharField(
 max_length=50,
 null=True,
 blank=True,
 verbose_name="Provider 类型",
 help_text="LLM Provider 类型，为空时继承上层配置",
 )
 is_deleted = models.BooleanField(default=False, db_index=True)
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "conversations"
 ordering = ["-updated_at"]
 verbose_name = "对话"
 verbose_name_plural = "对话"
 def __str__(self) -> str:
 return f"{self.title} ({self.id})"
class Message(models.Model):
 """消息模型 — 对话中的单条消息。"""
 class Role(models.TextChoices):
 USER = "user", "用户"
 ASSISTANT = "assistant", "助手"
 SYSTEM = "system", "系统"
 TOOL = "tool", "工具"
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 conversation = models.ForeignKey(
 Conversation,
 on_delete=models.CASCADE,
 related_name="messages",
 )
 role = models.CharField(max_length=20, choices=Role.choices)
 content = models.TextField(blank=True, default="")
 tool_calls = models.JSONField(null=True, blank=True)
 tool_call_id = models.CharField(max_length=64, blank=True, default="")
 metadata = models.JSONField(default=dict, blank=True)
 created_at = models.DateTimeField(auto_now_add=True)
 class Meta:
 db_table = "messages"
 ordering = ["created_at"]
 indexes = [
 models.Index(fields=["conversation", "created_at"]),
 ]
 verbose_name = "消息"
 verbose_name_plural = "消息"
 def __str__(self) -> str:
 preview = self.content[:50] if self.content else ""
 return f"{self.role}: {preview}..."
class ChatPushSubscription(models.Model):
 """浏览器 Web Push 订阅。"""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 user = models.ForeignKey(
 settings.AUTH_USER_MODEL,
 on_delete=models.CASCADE,
 related_name="chat_push_subscriptions",
 )
 endpoint = models.TextField(unique=True)
 p256dh = models.CharField(max_length=255)
 auth = models.CharField(max_length=255)
 user_agent = models.TextField(blank=True, default="")
 is_active = models.BooleanField(default=True, db_index=True)
 last_used_at = models.DateTimeField(auto_now=True)
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "chat_push_subscriptions"
 verbose_name = "聊天 Push 订阅"
 verbose_name_plural = "聊天 Push 订阅"
 indexes = [
 models.Index(fields=["user", "is_active"]),
 ]
 def __str__(self) -> str:
 return f"ChatPushSubscription({self.user_id}, active={self.is_active})"
class CodingSession(models.Model):
 """编码会话 -- 追踪从技术方案到 PR 的全流程。
 状态机: draft -> confirmed -> running -> awaiting_confirmation -> running -> completed/failed
 """
 class Status(models.TextChoices):
 DRAFT = "draft", "方案草稿"
 CONFIRMED = "confirmed", "已确认"
 RUNNING = "running", "执行中"
 AWAITING_CONFIRMATION = "awaiting_confirmation", "等待确认"
 COMPLETED = "completed", "已完成"
 FAILED = "failed", "已失败"
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 conversation = models.ForeignKey(
 "chat.Conversation",
 on_delete=models.CASCADE,
 related_name="coding_sessions",
 )
 message = models.ForeignKey(
 "chat.Message",
 on_delete=models.SET_NULL,
 null=True,
 blank=True,
 related_name="coding_sessions",
 help_text="创建该方案的 AI 消息",
 )
 status = models.CharField(
 max_length=30,
 choices=Status.choices,
 default=Status.DRAFT,
 )
 tech_plan = models.TextField(verbose_name="技术方案 (Markdown)")
 affected_files = models.JSONField(default=list, verbose_name="影响文件列表")
 revision_count = models.IntegerField(default=0, verbose_name="修订次数")
 repository = models.ForeignKey(
 "repositories.Repository",
 on_delete=models.CASCADE,
 related_name="coding_sessions",
 )
 branch_name = models.CharField(max_length=255, blank=True, default="")
 subagent_session = models.OneToOneField(
 "subagent.SubAgentSession",
 on_delete=models.SET_NULL,
 null=True,
 blank=True,
 related_name="coding_session",
 )
 pr_url = models.URLField(blank=True, default="")
 error_message = models.TextField(blank=True, default="")
 confirmation_step = models.CharField(
 max_length=50,
 blank=True,
 default="",
 verbose_name="当前确认步骤",
 help_text="awaiting_confirmation 状态下标识具体确认类型: commit_message, pr_review",
 )
 suggested_commit_message = models.TextField(
 blank=True,
 default="",
 verbose_name="AI 建议的 commit message",
 help_text="Phase 容器回传，支持页面刷新后恢复",
 )
 suggested_pr_title = models.CharField(
 max_length=200,
 blank=True,
 default="",
 verbose_name="AI 建议的 PR 标题",
 help_text="generate_pr_draft 节点生成，支持页面刷新后恢复",
 )
 suggested_pr_description = models.TextField(
 blank=True,
 default="",
 verbose_name="AI 建议的 PR 描述",
 help_text="generate_pr_draft 节点生成，支持页面刷新后恢复",
 )
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "coding_sessions"
 ordering = ["-created_at"]
 indexes = [
 models.Index(fields=["conversation", "status"]),
 ]
 verbose_name = "编码会话"
 verbose_name_plural = "编码会话"
 def __str__(self) -> str:
 return f"CodingSession({self.id}, {self.status})"
 async def aconfirm(self) -> None:
 """draft -> confirmed 状态转换。"""
 if self.status != self.Status.DRAFT:
 raise ValueError("只有 draft 状态可确认")
 self.status = self.Status.CONFIRMED
 await self.asave(update_fields=["status", "updated_at"])
 async def amark_running(self, subagent_session_id: int | None = None) -> None:
 """confirmed -> running 状态转换，关联 SubAgentSession。"""
 self.status = self.Status.RUNNING
 if subagent_session_id is not None:
 self.subagent_session_id = subagent_session_id # type: ignore[assignment]
 await self.asave(update_fields=["status", "subagent_session", "updated_at"])
 async def amark_completed(self, pr_url: str = "") -> None:
 """running -> completed 状态转换，设置 PR URL。"""
 self.status = self.Status.COMPLETED
 self.pr_url = pr_url
 await self.asave(update_fields=["status", "pr_url", "updated_at"])
 async def amark_failed(self, error: str = "") -> None:
 """running -> failed 状态转换，设置错误信息。"""
 self.status = self.Status.FAILED
 self.error_message = error
 await self.asave(update_fields=["status", "error_message", "updated_at"])
 async def amark_awaiting_confirmation(self, step: str, suggested_commit_message: str = "") -> None:
 """running -> awaiting_confirmation 状态转换。"""
 if self.status != self.Status.RUNNING:
 raise ValueError("只有 running 状态可进入等待确认")
 self.status = self.Status.AWAITING_CONFIRMATION
 self.confirmation_step = step
 if suggested_commit_message:
 self.suggested_commit_message = suggested_commit_message
 await self.asave(update_fields=[
 "status", "confirmation_step", "suggested_commit_message", "updated_at",
 ])
 async def aresume_running(self) -> None:
 """awaiting_confirmation -> running 状态转换（用户确认后）。"""
 if self.status != self.Status.AWAITING_CONFIRMATION:
 raise ValueError("只有 awaiting_confirmation 状态可恢复运行")
 self.status = self.Status.RUNNING
 self.confirmation_step = ""
 await self.asave(update_fields=["status", "confirmation_step", "updated_at"])
 async def aupdate_plan(
 self,
 tech_plan: str,
 affected_files: list[dict[str, str]],
 ) -> None:
 """更新技术方案并递增修订计数。"""
 self.tech_plan = tech_plan
 self.affected_files = affected_files
 self.revision_count += 1
 await self.asave(
 update_fields=["tech_plan", "affected_files", "revision_count", "updated_at"]
 )
