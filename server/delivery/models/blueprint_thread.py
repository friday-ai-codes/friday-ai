"""蓝图划线澄清/评论线程模型（Phase 111，DESIGN §6.1）。

飞书文档式的划线线程与多轮消息：

- **``BlueprintThread``**：挂在蓝图 Artifact 上的一条线程。``anchor`` JSON 可空
  （null = 全局/段级线程，如仓库确认门、整段评审意见）；版本变更后重锚定失败
  置 ``anchor_status=orphaned``（失锚不删线程，DESIGN §6.2）。``blocking=True``
  的 open 线程阻塞 ``pending_review → confirmed``（LIFE-02 守卫）。
- **``BlueprintThreadMessage``**：线程内多轮消息（ai/human 双方）。

设计要点（守 INV-6 精神）：状态与业务流转唯一 writer = ``BlueprintLifecycleService``
（111 只建模型与守卫查询，线程业务流转归 Phase 114）；本模型层**零业务方法**，
旁路写表由 ``test_blueprint_inv6_guard`` 源码扫描锁死。
"""

import uuid

from django.conf import settings
from django.db import models


class ThreadAnchorStatus(models.TextChoices):
    """线程锚定状态（重锚定失败 → orphaned，不删线程）。"""

    ANCHORED = "anchored", "已锚定"
    ORPHANED = "orphaned", "已失锚"


class ThreadKind(models.TextChoices):
    """线程种类（DESIGN §6.1）。"""

    AI_CLARIFICATION = "ai_clarification", "AI 澄清提问"
    AI_REVIEW_FINDING = "ai_review_finding", "AI 审查发现"
    HUMAN_COMMENT = "human_comment", "人工评论"
    REPO_CONFIRMATION = "repo_confirmation", "仓库确认门"


class ThreadSeverity(models.TextChoices):
    """审查发现严重级（review_finding 用）。"""

    BLOCKER = "blocker", "阻塞"
    WARNING = "warning", "警告"
    INFO = "info", "提示"


class ThreadStatus(models.TextChoices):
    """线程状态机 open → answered → resolved | dismissed。"""

    OPEN = "open", "待处理"
    ANSWERED = "answered", "已回答"
    RESOLVED = "resolved", "已解决"
    DISMISSED = "dismissed", "已忽略"


class ThreadAuthorType(models.TextChoices):
    """消息作者类型。"""

    AI = "ai", "AI"
    HUMAN = "human", "人类"


class BlueprintThread(models.Model):
    """蓝图划线澄清/评论线程（DESIGN §6.1）。"""

    objects: "models.Manager[BlueprintThread]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    artifact = models.ForeignKey(
        "delivery.Artifact",
        on_delete=models.CASCADE,
        related_name="blueprint_threads",
    )
    # 创建线程时所在的蓝图版本；删版本不删线程
    created_on_version = models.ForeignKey(
        "delivery.ArtifactVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # 锚点 JSON（null = 全局/段级线程）；形状
    # {section_path, block_id, start_offset, end_offset, quoted_text}
    anchor = models.JSONField(null=True, blank=True)
    anchor_status = models.CharField(
        max_length=16,
        choices=ThreadAnchorStatus.choices,
        default=ThreadAnchorStatus.ANCHORED,
    )
    # max_length=24：ai_review_finding / repo_confirmation 长 17 字符（P5）
    kind = models.CharField(max_length=24, choices=ThreadKind.choices)
    severity = models.CharField(
        max_length=16,
        choices=ThreadSeverity.choices,
        blank=True,
        default="",
    )
    # 是否阻塞 confirmed（repo_confirmation 恒为 True）
    blocking = models.BooleanField(default=False)
    # 澄清候选选项 [{label, value, note}]；确认门为结构化仓库清单操作
    options = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=16,
        choices=ThreadStatus.choices,
        default=ThreadStatus.OPEN,
    )
    # needs_clarification 恢复目标（取值 researching/drafting/ai_reviewing，DESIGN §6.1）
    return_stage = models.CharField(max_length=16, blank=True, default="")
    # 观测规范：绑定触发用户；AI 侧标 system
    initiated_by_user_id = models.CharField(max_length=64, default="system")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # 114-05（B4）：澄清超时提醒的**周期锚点**。null = 从未提醒过（到期判据回落
    # `created_at`）。有它才能做到「按周期提醒」而不是每次 job tick 都重复轰炸同一
    # 条线程。⚠️ 提醒路径用 `bulk_update` 写回本字段，`bulk_update` **绕过 auto_now**
    # ⇒ 必须同时显式带 `updated_at=timezone.now()`（同 `_apply_transition_sync`）。
    last_reminded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "delivery_blueprint_thread"
        verbose_name = "蓝图澄清线程"
        verbose_name_plural = "蓝图澄清线程"
        indexes = [
            # confirm 守卫查询驱动：filter(artifact, status=open, blocking=True)
            models.Index(fields=["artifact", "status", "blocking"]),
        ]

    def __str__(self) -> str:
        return f"BlueprintThread({self.id}, {self.kind}/{self.status})"


class BlueprintThreadMessage(models.Model):
    """线程内多轮消息（DESIGN §6.1）。"""

    objects: "models.Manager[BlueprintThreadMessage]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    thread = models.ForeignKey(
        BlueprintThread,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    author_type = models.CharField(max_length=8, choices=ThreadAuthorType.choices)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    body = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_blueprint_thread_message"
        verbose_name = "蓝图线程消息"
        verbose_name_plural = "蓝图线程消息"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"BlueprintThreadMessage({self.id}, {self.author_type})"
