"""项目记忆模型（MEM-01~04）。

项目记忆是可变、对全部成员共享的自由文本沉淀：

- ``ProjectMemory``：当前态记忆条目（``status`` active/superseded + 贡献者 + 时间戳）。
- ``ProjectMemoryRevision``：**append-only** 编辑历史快照（编辑保留可追溯，不就地丢历史，MEM-03）。
- ``ProjectMemoryDraft``：LLM 从成员会话提炼的**草稿**（pending/confirmed/rejected），人工确认才入库
  （MEM-04，绝不自动写 active）。

模型层**不提供业务 create/save 方法**——所有写入收口于 ``initiatives.services.MemoryService``
（INV-6，由 ``test_memory_inv6_guard`` grep 守护）。
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class ProjectMemoryStatus(models.TextChoices):
    """记忆条目状态。"""

    ACTIVE = "active", "生效"
    SUPERSEDED = "superseded", "已废弃"


class ProjectMemory(models.Model):
    """项目记忆条目（自由文本，成员共享，可编辑且可追溯）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "initiatives.Project",
        on_delete=models.CASCADE,
        related_name="memories",
        verbose_name="项目",
    )
    content = models.TextField(verbose_name="记忆内容")
    contributor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contributed_memories",
        verbose_name="贡献者",
    )
    status = models.CharField(
        max_length=20,
        choices=ProjectMemoryStatus.choices,
        default=ProjectMemoryStatus.ACTIVE,
        verbose_name="状态",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_project_memories"
        verbose_name = "项目记忆"
        verbose_name_plural = "项目记忆"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project", "status"]),
        ]

    def __str__(self) -> str:
        return f"Memory({self.id}, {self.status})"


class ProjectMemoryRevision(models.Model):
    """记忆编辑历史（append-only 快照，MEM-03 可追溯）。

    每次 ``MemoryService.append/edit`` 落一条快照（记录当时内容），当前态读
    ``ProjectMemory.content``；本表只增不改，绝不就地覆盖丢历史。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    memory = models.ForeignKey(
        "initiatives.ProjectMemory",
        on_delete=models.CASCADE,
        related_name="revisions",
        verbose_name="记忆条目",
    )
    content = models.TextField(verbose_name="内容快照")
    editor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="edited_memory_revisions",
        verbose_name="编辑者",
    )
    edited_at = models.DateTimeField(auto_now_add=True, verbose_name="编辑时间")

    class Meta:
        db_table = "initiative_project_memory_revisions"
        verbose_name = "项目记忆修订"
        verbose_name_plural = "项目记忆修订"
        ordering = ["memory", "edited_at"]
        indexes = [
            models.Index(fields=["memory", "edited_at"]),
        ]

    def __str__(self) -> str:
        return f"MemoryRevision({self.memory_id}, {self.edited_at})"


class DraftStatus(models.TextChoices):
    """记忆草稿状态。"""

    PENDING = "pending", "待确认"
    CONFIRMED = "confirmed", "已确认入库"
    REJECTED = "rejected", "已拒绝"


class ProjectMemoryDraft(models.Model):
    """LLM 从成员会话提炼的记忆草稿（MEM-04，人工确认才入库）。

    LLM 仅产 ``pending`` 草稿，**绝不自动写 active 记忆**；人工确认经
    ``MemoryService.confirm_draft`` → ``ProjectMemory``。``source_conversation_id`` 为软引用
    （UUID，不与 ``chat.Conversation`` 建跨 app 硬 FK，避免循环依赖）。入库前内容已脱敏。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "initiatives.Project",
        on_delete=models.CASCADE,
        related_name="memory_drafts",
        verbose_name="项目",
    )
    content = models.TextField(verbose_name="草稿内容（已脱敏）")
    status = models.CharField(
        max_length=20,
        choices=DraftStatus.choices,
        default=DraftStatus.PENDING,
        verbose_name="状态",
    )
    source_conversation_id = models.UUIDField(
        null=True, blank=True, verbose_name="来源会话（软引用）"
    )
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposed_memory_drafts",
        verbose_name="发起人",
    )
    confirmed_memory = models.ForeignKey(
        "initiatives.ProjectMemory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_drafts",
        verbose_name="确认入库后的记忆",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_project_memory_drafts"
        verbose_name = "项目记忆草稿"
        verbose_name_plural = "项目记忆草稿"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project", "status"]),
        ]

    def __str__(self) -> str:
        return f"MemoryDraft({self.id}, {self.status})"
