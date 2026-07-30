"""对话数据模型：Conversation 和 Message。

定义对话系统的核心数据结构。Conversation 绑定 Space，
Message 支持 user/assistant/system/tool 四种角色，
用于存储完整的对话历史（含工具调用记录）。
"""

import hashlib
import uuid

import structlog
from django.conf import settings
from django.db import models
from django.db.models import Q

from projects.models import Space

logger = structlog.get_logger(__name__)


class Conversation(models.Model):
    """对话模型 — 一次完整的用户-AI 交互会话。"""

    class Status(models.TextChoices):
        """对话状态（implementation contract contract pin 冻结判据）。

        status 为 contract 三态判定的唯一真源：
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

    class Visibility(models.TextChoices):
        """会话可见性（项目作战室 P2）。

        - ``personal``：仅创建者可见可用（默认，沿用 ISO owner 隔离语义）。
        - ``shared``：项目共享会话——绑定项目的成员**只读可见**；他人要发言需
          clone 成自己的「项目个人会话」（fork）。仅当 ``bound_project`` 非空时可设。
        """

        PERSONAL = "personal", "个人"
        SHARED = "shared", "项目共享"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # 可空：允许不绑定空间的「通用对话」。无空间时检索/编码工具不可用，
    # system prompt 会引导用户在需要空间知识时先选择空间。
    space = models.ForeignKey(
        Space,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    # ISO-01：会话创建者；owner-scoped 隔离的真源。可空——历史会话、匿名/开放
    # 模式（未认证）创建的会话 created_by 为 null。删除 owner 用户走 SET_NULL，
    # 会话保留、created_by 置 null（不级联删会话）。
    created_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="conversations",
        help_text="会话创建者；历史/匿名/开放模式可为 null（ISO-01）",
    )
    title = models.CharField(max_length=200, default="新对话")
    model = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="LLM 模型 ID，为空时使用系统默认模型",
    )
    # implementation（contract/contract）：v8.1 Conversation.provider_type 字段硬删；
    # 替代：provider_credential_id FK（contract pin 语义 contract）
    # implementation contract contract/contract：对话级固定 Provider 凭证（pin 语义）
    provider_credential_id = models.ForeignKey(
        "system.ProviderCredential",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="conversations",
        help_text="对话级固定 Provider 凭证（contract pin 语义 contract）",
    )
    # RECALL-02（v0.15.0 Phase 80）：会话绑定的「项目聚合根」（initiatives.Project），
    # **区别于 ``space``**（组织单元）。绑定后 chat 自动经 context packer 加载项目完整上下文
    # （需求/工件/记忆/关联知识），按成员权限 fail-closed。软删项目用 SET_NULL，会话保留。
    bound_project = models.ForeignKey(
        "initiatives.Project",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bound_conversations",
        help_text="绑定的项目聚合根（RECALL-02，区别于 space 组织单元）",
    )
    # implementation contract contract：对话状态（frozen 判据真源）
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="对话状态",
        help_text="contract pin 冻结判据；frozen 态（completed/stopped/error）拒绝修改 provider_credential_id",
    )
    is_deleted = models.BooleanField(default=False, db_index=True)
    # 归档：与软删（is_deleted）正交 —— 归档的会话从默认列表隐藏，但不删除，
    # 可由用户取消归档恢复。默认列表 filter(is_archived=False)。
    is_archived = models.BooleanField(default=False, db_index=True)
    # 项目作战室 P2：会话可见性（personal=仅创建者 / shared=项目成员只读可见）。
    # 存量数据默认 personal（行为不回退）；shared 仅在 bound_project 非空时有意义。
    visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.PERSONAL,
        db_index=True,
        help_text="会话可见性（personal=仅创建者 / shared=项目共享只读）",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "conversations"
        ordering = ["-updated_at"]
        verbose_name = "对话"
        verbose_name_plural = "对话"
        indexes = [
            models.Index(fields=["bound_project", "visibility", "is_deleted", "is_archived"]),
            models.Index(fields=["bound_project", "created_by"]),
        ]

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
    # parts contract：Anthropic content blocks 风格的有序 parts 数组
    # （TextPart / ToolUsePart / ThinkingPart 联合）。default=[]、零 data migration；
    # legacy 历史消息读出 [] 后由前端 hydrate adapter 合成（legacy hydration contract）。content /
    # tool_calls 字段由 PartsCollector.to_message_payload() 强同源派生，不允许
    # 散落规则。schema 演化走 metadata.parts_schema_version。
    parts = models.JSONField(default=list, blank=True)
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
    """编码方案 — implementation 拆出的独立领域实体。

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
    # AI 在 chat 流中通过 analyze_repository_relevance /
    # deep_analysis cross_repo_relevance 识别出的相关仓库 UUID 列表，自动
    # 预填到 create_coding_plan 工具的 recommended_repository_ids 入参。
    # 由 fan-out 流程（implementation）按本字段批量创建 CodingSession。
    recommended_repository_ids = models.JSONField(
        default=list,
        blank=True,
        verbose_name="推荐仓库 ID 列表",
        help_text=(
            "[str(UUID), ...] —— AI 识别的相关仓库 UUID 列表；不传则 Server "
            "自动从 conversation 最近一条 RepositoryRoutingTrace 取 "
            "selected_by_user_final=True 的仓库（implementation）。"
        ),
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
        content_hash = hashlib.sha256(tech_plan.encode("utf-8")).hexdigest()
        async for existing in cls.objects.filter(conversation=conversation).aiterator():
            existing_hash = hashlib.sha256(existing.tech_plan.encode("utf-8")).hexdigest()
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
        from knowledge import ingestion  # lazy import 防循环

        await ingestion.aschedule_ingestion(
            ingestion.IngestionRequest("coding_plan", str(plan.id), "chat_plan_created")
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
        from knowledge import ingestion  # lazy import 防循环

        await ingestion.aschedule_ingestion(
            ingestion.IngestionRequest("coding_plan", str(self.id), "chat_plan_updated")
        )


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
        # 容器 5min 无回复挂起态（PLAN-03）：单仓编码容器遇阻等待用户，到点无回复
        # → finish turn 停容器（dispatcher.cancel）+ 标此态；用户卡片回复后经
        # SessionStore resume 续跑回 RUNNING。写入收口 ContainerSuspendService（INV-6）。
        SUSPENDED = "suspended", "已挂起"

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
            "implementation：tech_plan / affected_files 拆出 CodingPlan 后的关联；"
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
            "implementation 起 deprecated：优先使用 coding_plan.tech_plan；"
            "本字段保留至 v26.1 清理"
        ),
    )
    affected_files = models.JSONField(
        default=list,
        verbose_name="影响文件列表",
        help_text=(
            "implementation 起 deprecated：优先使用 coding_plan.affected_files；"
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
    target_branch = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="PR 目标分支",
        help_text="用户在启动编码时选定的合并目标分支，PR 创建时使用；为空时回退到仓库默认分支",
    )
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
    # Claude Code SDK 会话恢复（resume 支撑）：容器编码结束经 callback 回传。
    # sdk_session_id 单独存字符串供 re-dispatch 注入 FRIDAY_TASK_RESUME_SESSION_ID；
    # sdk_transcript 存 SDK 对话 transcript（jsonl 文本），resume 时容器从 server 拉回还原。
    # 二者按 sdk_session_saved_at + 7 天定时清理（cleanup_coding_sessions）。
    sdk_session_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        verbose_name="Claude Code SDK 会话 ID",
        help_text="容器 ResultMessage.session_id，用于 re-dispatch 时 resume 续跑",
    )
    sdk_transcript = models.TextField(
        blank=True,
        default="",
        verbose_name="SDK 会话 transcript",
        help_text=(
            "Claude Code SDK 对话 transcript（jsonl 文本）。resume 时容器拉回还原到"
            " ~/.claude 后 ClaudeAgentOptions(resume=...) 续跑；超大小上限则置空走语义重建回退。"
        ),
    )
    sdk_session_saved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="SDK 会话保存时间",
        help_text="transcript 落库时间；7 天定时清理以此为准",
    )
    # 容器 5min 无回复挂起时间戳（PLAN-03）：便于审计 / 恢复诊断。写入收口经
    # ContainerSuspendService（INV-6），与 status=SUSPENDED 同步落。
    parked_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="容器挂起时间",
        help_text="5min 无回复挂起停容器的时间戳（PLAN-03，审计/恢复诊断用）",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "coding_sessions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["conversation", "status"]),
            # 批量按 (coding_plan, status) 查询的覆盖索引；
            # 支撑 work item 批量预检 + work item 状态行渲染。
            models.Index(
                fields=["coding_plan", "status"],
                name="idx_codingsession_plan_status",
            ),
        ]
        # 同一 plan + 同一 repository 同一时刻仅允许 1 个活跃 session。
        # status 字面值与 CodingSession.Status 枚举对应：
        #   draft / confirmed / running / awaiting_confirmation
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
            self.subagent_session_id = subagent_session_id  # type: ignore[assignment]
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


class RepositoryRoutingTrace(models.Model):
    """跨仓相关性路由决策的可审计落地表（implementation）。

    三个写入来源（triggered_by 枚举）：

    - ``chat_tool``：work item 工具 ``analyze_repository_relevance`` 调用即时写入。
    - ``deep_analysis_completion``：work item deep_analysis 容器完成回报时写入。
    - ``manual_override``：work item 用户在 RoutingDecisionPanel 改勾选时写**新行**
      —— 不修改原 trace，保留 AI 决策 vs 用户最终决策的对照样本。

    ``candidates`` JSON 元素 schema：

        {
            "repository_id": str,
            "repository_name": str,
            "score": float,
            "level": "high" | "medium" | "low",
            "evidence": str,
            "selected_by_ai": bool,
            "selected_by_user_final": bool,
        }

    其中 ``selected_by_ai`` 在 trace 创建时按阈值固定，``selected_by_user_final``
    初次写入与 ``selected_by_ai`` 同值；被 manual_override trace 覆盖时单独写
    一行新 trace 而非改原行。
    """

    class TriggeredBy(models.TextChoices):
        CHAT_TOOL = "chat_tool", "Chat 工具调用"
        DEEP_ANALYSIS_COMPLETION = "deep_analysis_completion", "深度分析完成"
        MANUAL_OVERRIDE = "manual_override", "用户手动微调"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent_session = models.ForeignKey(
        "agents.AgentSession",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="routing_traces",
        help_text=(
            "关联 deep_analysis AgentSession；chat_tool / manual_override "
            "路径为 None"
        ),
    )
    conversation = models.ForeignKey(
        "chat.Conversation",
        on_delete=models.CASCADE,
        related_name="routing_traces",
    )
    query = models.TextField(help_text="触发本次路由的用户 query")
    candidates = models.JSONField(
        default=list,
        help_text=(
            "[{repository_id, repository_name, score, level, evidence, "
            "selected_by_ai, selected_by_user_final}]"
        ),
    )
    threshold = models.FloatField(
        default=0.5,
        help_text="本次决策用的截断阈值（≥ 阈值自动 selected_by_ai=True）",
    )
    triggered_by = models.CharField(
        max_length=32,
        choices=TriggeredBy.choices,
    )
    # PageIndex 化路由版本对照（观测指标用）：
    # legacy_hybrid（旧聚合）/ v2（树推理）/ v2_stage0_only（节点检索无 LLM）
    router_version = models.CharField(
        max_length=20,
        default="legacy_hybrid",
        help_text="路由实现版本，供 v1/v2 相关度对照分析",
    )
    # RELY-03 用户可见降级原因（107-08）：6 值受控闭集（timeout / upstream_error /
    # provider_missing / unparsable / no_node_index / unknown）∪ ""（无可见原因）。
    # 单列而非塞进 candidates JSON —— 迁移开销小，且「降级原因分布」可直接 SQL 聚合
    # （candidates 是 list，外层塞不进这个结果级事实）。
    # 列长 32 本身即形状约束：结构上装不下上游异常原文（T-107-02 的第二道防线，
    # 第一道是写入侧 classify_degrade_reason 的枚举归一）。
    degrade_reason = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="用户可见降级原因（6 值闭集 ∪ 空串），供降级原因分布聚合",
    )
    # ROUTE-01/02 呈现层区顺序（107-08）：长度 2 = 有项目上下文（即使某组为空），
    # ["global"] 或空 = 无上下文。消费方（前端 RoutingDecisionPanel）据长度判定是否
    # 启用分组呈现，这是唯一依据（UI-SPEC covered 11）。该值不进任何排序或打分逻辑。
    block_order = models.JSONField(
        default=list,
        blank=True,
        help_text='呈现层区顺序，如 ["in_project", "global"]；长度 2 表示有项目上下文',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "repository_routing_traces"
        verbose_name = "跨仓路由决策 trace"
        verbose_name_plural = "跨仓路由决策 traces"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["conversation", "-created_at"],
                name="routing_trace_conv_idx",
            ),
            models.Index(
                fields=["agent_session"],
                name="routing_trace_session_idx",
            ),
            models.Index(
                fields=["triggered_by", "created_at"],
                name="routing_trace_trigger_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"RoutingTrace({self.id}, triggered_by={self.triggered_by}, "
            f"candidates={len(self.candidates) if isinstance(self.candidates, list) else 0})"
        )


def derive_routing_degraded(router_version: str) -> bool:
    """降级事实的**唯一派生点**（会话 detail / manual override / 工具实时输出三处共用）。

    CONTEXT 要求「前端不自行推断降级」——把推断放到后端即满足该契约，且无需与
    ``router_version`` 冗余地再加一列（加列还要回填历史行）。

    ``legacy_hybrid`` 刻意排除：它是 ``router_version`` 的列默认值，代表 v2 完全不可用
    时的历史聚合路径；把它算作降级会让全部历史 trace 突然出现降级横幅
    （UI-SPEC backstop 1 的历史兼容要求）。

    新增判定分支时改这一处即可 —— 任何 payload 都不得再写等价的版本字面判定。
    放在 models 模块（而非某个 view）是为了让 ``agents.tools`` 这类非 HTTP 消费方也能
    复用同一个派生点而不反向依赖 view 层。
    """
    return router_version in {"v2_stage0_only", "v1_fallback"}


class ConversationIntentTrace(models.Model):
    """意图协商时间线（implementation）。

    记录每次 ``ask_clarification`` 触发的协商：问题、选项、用户答复、
    inferred 状态、是否最终落到 CodingPlan。这是 coding-plan workflow「准确性优先于速度」
    哲学的可观测底座 —— 没有 trace，evaluation 阶段无法回答「澄清是否真的
    提升了准确率」。

    字段语义：
        - ``triggering_message_id``：触发本次协商的 user message id 字符串。
          故意不做 FK 是为了避免删除消息时级联删 trace（trace 是审计记录，
          应当独立存在）。
        - ``clarification_id``：``ask_clarification`` 工具调用产生的 uuid hex；
          唯一索引保证「同一 conversation 同时只允许 1 个 pending」（plan 03
          硬约束）。
        - ``options``：完整 ClarificationOption 列表（schema 见
          ``work-item.md``）。用户改选后，原 options 不变，仅
          ``selected_option_id`` / ``inferred_state`` 更新。
        - ``inferred_state``：用户选项的 ``implies`` merge 后最终注入对话
          上下文的状态字典（如 ``selected_repository_ids`` /
          ``task_category``）。
        - ``resolved_to_plan``：是否最终产出 CodingPlan，用于 evaluation
          路径（澄清 → 方案 → 转化率）。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        "chat.Conversation",
        on_delete=models.CASCADE,
        related_name="intent_traces",
    )
    triggering_message_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="触发本次协商的 user message id（字符串化的 UUID）",
    )
    clarification_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="ask_clarification 工具调用产生的 uuid hex",
    )
    question = models.TextField(help_text="协商问题原文")
    options = models.JSONField(
        default=list,
        help_text="ClarificationOption 列表（id/label/hint/implies）",
    )
    selected_option_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="用户选中的 option.id；若仅自由输入则为空",
    )
    freeform_answer = models.TextField(
        blank=True,
        default="",
        help_text="用户自由输入的答复（与 selected_option_id 至少一个非空）",
    )
    inferred_state = models.JSONField(
        default=dict,
        help_text="implies merge 后注入对话上下文的状态字典",
    )
    resolved_to_plan = models.ForeignKey(
        "chat.CodingPlan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="intent_traces",
        help_text="本次协商是否最终落到 CodingPlan（evaluation 用）",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    answered_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="用户提交答复的时间；None 表示尚未回复",
    )

    class Meta:
        db_table = "conversation_intent_traces"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["conversation", "-created_at"],
                name="intent_trace_conv_idx",
            ),
            models.Index(
                fields=["clarification_id"],
                name="intent_trace_clar_id_idx",
            ),
        ]
        verbose_name = "意图协商 trace"
        verbose_name_plural = "意图协商 traces"

    def __str__(self) -> str:
        short = self.clarification_id[:8] if self.clarification_id else "?"
        return f"IntentTrace<{short}>"
