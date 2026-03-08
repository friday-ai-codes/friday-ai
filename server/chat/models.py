"""对话数据模型：Conversation 和 Message。
定义对话系统的核心数据结构。Conversation 绑定 Project，
Message 支持 user/assistant/system/tool 四种角色，
用于存储完整的对话历史（含工具调用记录）。
"""
import uuid
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
