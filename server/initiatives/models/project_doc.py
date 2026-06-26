"""项目工作区文件容器 + 飞书同步映射模型（WS/DOC-01~05）。

- ``ProjectDoc``：项目工作区 5 份文件（memory/state/milestones/research/preflight）的容器，
  持飞书文档映射（document_id/doc_token）、增量同步水位（last_synced_revision）与内联快照
  （last_synced_snapshot）、就绪状态（sync_status）。MEMORY 条目本身仍落 ``ProjectMemory``，
  ``ProjectDoc(memory)`` 只持飞书映射与渲染，**不持记忆业务数据**。
- ``ProjectDocBlockMap``：飞书 block_id ↔ 库内引用（db_ref）的同步映射骨架，区分系统区/人工区
  （section）并存内容指纹（content_hash）；同步引擎在 Phase 83 落地，本期仅建表。

模型层**不提供业务 create/save 方法**——所有写入收口于
``initiatives.services.ProjectDocService``（INV-6，由 ``test_project_doc_inv6_guard`` grep 守护，
随 82-02 落地）。
"""

from __future__ import annotations

import uuid

from django.db import models


class DocType(models.TextChoices):
    """工作区文件类型（5 份固定文件，每项目每类型至多一份）。"""

    MEMORY = "memory", "记忆"
    STATE = "state", "状态"
    MILESTONES = "milestones", "里程碑"
    RESEARCH = "research", "调研"
    PREFLIGHT = "preflight", "预检"


class DocSyncStatus(models.TextChoices):
    """文件飞书同步状态。"""

    PENDING = "pending", "待创建"
    READY = "ready", "已就绪"
    BROKEN = "broken", "失效待重建"


class DocSection(models.TextChoices):
    """文档区段：系统生成区 vs 人工编辑区。"""

    SYSTEM = "system", "系统区"
    HUMAN = "human", "人工区"


class ProjectDoc(models.Model):
    """项目工作区文件容器（每项目每 doc_type 至多一行）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "initiatives.Project",
        on_delete=models.CASCADE,
        related_name="docs",
        verbose_name="项目",
    )
    doc_type = models.CharField(
        max_length=20,
        choices=DocType.choices,
        verbose_name="文件类型",
    )
    feishu_document_id = models.CharField(
        max_length=200, blank=True, default="", verbose_name="飞书文档 ID"
    )
    feishu_doc_token = models.CharField(
        max_length=200, blank=True, default="", verbose_name="飞书文档 token"
    )
    # 增量同步水位：飞书文档 revision_id，避免全量 diff（同步引擎 Phase 83 使用）。
    last_synced_revision = models.BigIntegerField(default=0, verbose_name="最近同步 revision")
    # 内联快照：最近一次同步的内容快照（最小可用，不另起快照表，per Claude 裁量）。
    last_synced_snapshot = models.TextField(blank=True, default="", verbose_name="最近同步快照")
    sync_status = models.CharField(
        max_length=20,
        choices=DocSyncStatus.choices,
        default=DocSyncStatus.PENDING,
        verbose_name="同步状态",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_project_docs"
        verbose_name = "项目文件"
        verbose_name_plural = "项目文件"
        ordering = ["-created_at"]
        constraints = [
            # 每项目每 doc_type 至多一行。
            models.UniqueConstraint(fields=["project", "doc_type"], name="uniq_project_doc_type"),
        ]
        indexes = [
            models.Index(fields=["project", "doc_type"]),
        ]

    def __str__(self) -> str:
        return f"ProjectDoc({self.project_id}, {self.doc_type})"


class ProjectDocBlockMap(models.Model):
    """飞书 block ↔ 库内引用的同步映射（每文档每 block_id 至多一行）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    doc = models.ForeignKey(
        "initiatives.ProjectDoc",
        on_delete=models.CASCADE,
        related_name="block_maps",
        verbose_name="所属文件",
    )
    feishu_block_id = models.CharField(max_length=200, verbose_name="飞书 block id")
    db_ref = models.CharField(max_length=200, blank=True, default="", verbose_name="库内引用")
    section = models.CharField(
        max_length=20,
        choices=DocSection.choices,
        default=DocSection.SYSTEM,
        verbose_name="区段",
    )
    content_hash = models.CharField(max_length=128, blank=True, default="", verbose_name="内容指纹")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_project_doc_block_maps"
        verbose_name = "项目文件 block 映射"
        verbose_name_plural = "项目文件 block 映射"
        constraints = [
            # 每文档每 feishu_block_id 至多一行。
            models.UniqueConstraint(fields=["doc", "feishu_block_id"], name="uniq_doc_block"),
        ]
        indexes = [
            models.Index(fields=["doc", "section"]),
        ]

    def __str__(self) -> str:
        return f"ProjectDocBlockMap({self.doc_id}, {self.feishu_block_id})"
