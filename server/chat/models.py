"""对话数据模型：Conversation 和 Message。
定义对话系统的核心数据结构。Conversation 绑定 Project，
Message 支持 user/assistant/system/tool 四种角色，
用于存储完整的对话历史（含工具调用记录）。
"""
import hashlib
import uuid
import structlog
from django.conf import settings
from django.db import models
from django.db.models import Q
from projects.models import Project
logger = structlog.get_logger(__name__)
class Conversation(models.Model):
 """对话模型 — 一次完整的用户-AI 交互会话。"""
 class Status(models.TextChoices):
 """对话状态（Phase pin 冻结判据）。
 status 为 三态判定的唯一真源：
 - draft：0 user message，Provider 可自由修改
 - running/paused/interrupted：≥1 user message 活跃态，切换 Provider 弹 pin 确认
 - completed/stopped/error：frozen 态，后端拒绝修改 provider_credential_id / model
 """
 DRAFT = "draft", "草稿"
 RUNNING = "running", "进行中"
 PAUSED = "paused", "已暂停"
 INTERRUPTED = "interrupted", "已中断"
 COMPLETED = "completed", "已完成"
 STOPPED = "stopped", "已停止"
 ERROR = "error", "异常"
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
 # Phase Plan：v8.1 Conversation.provider_type 字段硬删；
 # 替代：provider_credential_id FK（ pin 语义 ）
 # Phase /：对话级固定 Provider 凭证（pin 语义）
 provider_credential_id = models.ForeignKey(
 "system.ProviderCredential",
 null=True,
 blank=True,
 on_delete=models.SET_NULL,
 related_name="conversations",
 help_text="对话级固定 Provider 凭证（ pin 语义 ）",
 )
 # Phase：对话状态（frozen 判据真源）
 status = models.CharField(
 max_length=20,
 choices=Status.choices,
 default=Status.DRAFT,
 verbose_name="对话状态",
 help_text=" pin 冻结判据；frozen 态（completed/stopped/error）拒绝修改 provider_credential_id",
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
class CodingPlan(models.Model):
 """编码方案 — Phase 拆出的独立领域实体。
 一份 `CodingPlan` 描述一次"技术方案"语义（tech_plan + affected_files
 + 飞书文档元数据），由后续 CodingSession 实例引用执行。同一 conversation
 内 `tech_plan` 文本相同的方案通过 `aget_or_create_for_conversation` 去重，
 多 session（如 multi-confirm / 多仓 fan-out）共享同一份方案。
 """
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 conversation = models.ForeignKey(
 "chat.Conversation",
 on_delete=models.CASCADE,
 related_name="coding_plans",
 )
 title = models.CharField(
 max_length=200,
 blank=True,
 default="",
 verbose_name="方案标题",
 )
 tech_plan = models.TextField(verbose_name="技术方案 (Markdown)")
 affected_files = models.JSONField(
 default=list,
 verbose_name="影响文件列表",
 help_text='schema: [{"file_path": str, "change_type": str}]',
 )
 feishu_doc_token = models.CharField(
 max_length=64,
 blank=True,
 default="",
 verbose_name="飞书文档 token",
 )
 feishu_doc_url = models.CharField(
 max_length=500,
 blank=True,
 default="",
 verbose_name="飞书文档 URL",
 )
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "coding_plans"
 ordering = ["-created_at"]
 indexes = [
 models.Index(fields=["conversation", "-created_at"]),
 ]
 verbose_name = "编码方案"
 verbose_name_plural = "编码方案"
 def __str__(self) -> str:
 preview = self.title or self.tech_plan[:30]
 return f"CodingPlan({self.id}, {preview})"
 @classmethod
 async def aget_or_create_for_conversation(
 cls,
 conversation: "Conversation",
 tech_plan: str,
 affected_files: list[dict[str, str]],
 title: str = "",
 ) -> tuple["CodingPlan", bool]:
 """基于 `sha256(tech_plan)` 在 conversation 内去重。
 命中返回既有 plan + ``created=False``；未命中创建新 plan + ``created=True``。
 跨 conversation 不去重（同字符串两个 conversation 各产 1 条）。
 """
 content_hash = hashlib.sha256(tech_plan.encode("utf-8")).hexdigest
 async for existing in cls.objects.filter(conversation=conversation).aiterator:
 existing_hash = hashlib.sha256(existing.tech_plan.encode("utf-8")).hexdigest
 if existing_hash == content_hash:
 logger.info(
 "coding_plan_get_or_created",
 conversation_id=str(conversation.id),
 plan_id=str(existing.id),
 created=False,
 )
 return existing, False
 plan = await cls.objects.acreate(
 conversation=conversation,
 title=title,
 tech_plan=tech_plan,
 affected_files=affected_files,
 )
 logger.info(
 "coding_plan_get_or_created",
 conversation_id=str(conversation.id),
 plan_id=str(plan.id),
 created=True,
 )
 return plan, True
 async def aupdate_plan(
 self,
 tech_plan: str,
 affected_files: list[dict[str, str]],
 ) -> None:
 """原子更新 tech_plan + affected_files。"""
 self.tech_plan = tech_plan
 self.affected_files = affected_files
 await self.asave(update_fields=["tech_plan", "affected_files", "updated_at"])
 logger.info("coding_plan_updated", plan_id=str(self.id))
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
 coding_plan = models.ForeignKey(
 "chat.CodingPlan",
 on_delete=models.CASCADE,
 null=True,
 blank=True,
 related_name="coding_sessions",
 help_text=(
 "Phase：tech_plan / affected_files 拆出 CodingPlan 后的关联；"
 "过渡期为空，由 migrate_coding_sessions_to_plans 命令回填"
 ),
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
 tech_plan = models.TextField(
 verbose_name="技术方案 (Markdown)",
 help_text=(
 "Phase 起 deprecated：优先使用 coding_plan.tech_plan；"
 "本字段保留至 v26.1 清理"
 ),
 )
 affected_files = models.JSONField(
 default=list,
 verbose_name="影响文件列表",
 help_text=(
 "Phase 起 deprecated：优先使用 coding_plan.affected_files；"
 "本字段保留至 v26.1 清理"
 ),
 )
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
 conflict_check_result = models.JSONField(
 blank=True,
 default=dict,
 verbose_name="冲突预检结果",
 help_text="compare_branches 冲突检测结果，支持页面刷新恢复",
 )
 diff_summary = models.JSONField(
 blank=True,
 default=dict,
 verbose_name="Diff 摘要",
 help_text="相对 base 分支的文件变更统计，支持页面刷新恢复",
 )
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "coding_sessions"
 ordering = ["-created_at"]
 indexes = [
 models.Index(fields=["conversation", "status"]),
 # Phase：批量按 (coding_plan, status) 查询的覆盖索引；
 # 支撑 批量预检 + 状态行渲染。
 models.Index(
 fields=["coding_plan", "status"],
 name="idx_codingsession_plan_status",
 ),
 ]
 # Phase：同一 plan + 同一 repository 同一时刻仅允许 1 个活跃 session。
 # status 字面值与 CodingSession.Status 枚举对应：
 # draft / confirmed / running / awaiting_confirmation
 # completed 与 failed 不计入约束（允许多个历史 / 重试副本）。
 constraints = [
 models.UniqueConstraint(
 fields=["coding_plan", "repository"],
 condition=Q(
 status__in=[
 "draft",
 "confirmed",
 "running",
 "awaiting_confirmation",
 ]
 ),
 name="unique_active_plan_repo",
 ),
 ]
 verbose_name = "编码会话"
 verbose_name_plural = "编码会话"
 def __str__(self) -> str:
 return f"CodingSession({self.id}, {self.status})"
 @property
 def tech_plan_effective(self) -> str:
 """优先返回关联 CodingPlan 的 tech_plan，无关联则回退本字段（兼容期）。
 注意：调用方必须 `select_related('coding_plan')`，否则触发额外 DB 查询。
 """
 if self.coding_plan_id is not None and self.coding_plan is not None:
 return self.coding_plan.tech_plan
 return self.tech_plan
 @property
 def affected_files_effective(self) -> list[dict[str, str]]:
 """优先返回关联 CodingPlan 的 affected_files，回退本字段（兼容期）。"""
 if self.coding_plan_id is not None and self.coding_plan is not None:
 return list(self.coding_plan.affected_files)
 return list(self.affected_files)
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
