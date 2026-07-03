"""项目上下文关联（「生成知识关联」能力的持久化地基）。

把与项目高相关的上下文对象——知识实体 / 外部工件 / MR·PR / 外部链接——统一抽象为
**候选可审阅、人工可编辑**的关联记录：

- AI 生成（``origin=ai``）落 ``status=proposed``，由项目成员接受/拒绝；
- 人工添加（``origin=manual``）直接 ``status=accepted``，**绝不**被后续 AI 生成覆盖；
- 已 rejected 的候选在重新生成时**不复活**（幂等键命中即跳过）。

仓库关联不在本模型：``RepoAssociation`` 仍是项目↔仓库关联的唯一真相源（INV-6），
「生成知识关联」编排只是委托 ``RepoAssociationService`` 产候选，本模型承载其余目标类型。

模型层**不提供业务 create/save 方法**——所有写入收口于
``initiatives.services.context_link_service.ContextLinkService``。
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class ContextLinkKind(models.TextChoices):
    """关联目标类型。"""

    KNOWLEDGE = "knowledge", "知识实体"
    ARTIFACT = "artifact", "外部工件"
    MERGE_REQUEST = "merge_request", "MR/PR"
    EXTERNAL = "external", "外部链接"


class ContextLinkStatus(models.TextChoices):
    """候选审阅状态。"""

    PROPOSED = "proposed", "待确认"
    ACCEPTED = "accepted", "已关联"
    REJECTED = "rejected", "已拒绝"


class ContextLinkOrigin(models.TextChoices):
    """记录来源（人工记录不被 AI 生成覆盖的判据）。"""

    AI = "ai", "AI 生成"
    MANUAL = "manual", "人工添加"


class ProjectContextLink(models.Model):
    """项目↔上下文对象关联记录（候选审阅 + 人工编辑）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "initiatives.Project",
        on_delete=models.CASCADE,
        related_name="context_links",
        verbose_name="项目",
    )
    target_kind = models.CharField(
        max_length=20, choices=ContextLinkKind.choices, verbose_name="目标类型"
    )
    # knowledge → KnowledgeEntity.id；artifact → Artifact.id；merge_request → MergeRequest.id；
    # external（纯链接）无目标 id。
    target_id = models.UUIDField(null=True, blank=True, verbose_name="目标 id")
    title = models.CharField(max_length=500, blank=True, default="", verbose_name="标题快照")
    url = models.CharField(max_length=1000, blank=True, default="", verbose_name="链接")
    score = models.FloatField(default=0.0, verbose_name="相关性分")
    reason = models.TextField(blank=True, default="", verbose_name="关联理由")
    origin = models.CharField(
        max_length=10,
        choices=ContextLinkOrigin.choices,
        default=ContextLinkOrigin.AI,
        verbose_name="来源",
    )
    status = models.CharField(
        max_length=10,
        choices=ContextLinkStatus.choices,
        default=ContextLinkStatus.PROPOSED,
        verbose_name="状态",
    )
    initiated_by_user_id = models.CharField(
        max_length=64, blank=True, default="system", verbose_name="触发用户"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="创建者",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_context_links"
        verbose_name = "项目上下文关联"
        verbose_name_plural = "项目上下文关联"
        ordering = ["-created_at"]
        constraints = [
            # 幂等键：同项目同类型同目标唯一（external 无 target_id 不受限）。
            models.UniqueConstraint(
                fields=["project", "target_kind", "target_id"],
                condition=models.Q(target_id__isnull=False),
                name="uniq_context_link_project_kind_target",
            ),
        ]
        indexes = [
            models.Index(fields=["project", "status"]),
            models.Index(fields=["project", "target_kind"]),
        ]

    def __str__(self) -> str:
        return f"ContextLink({self.target_kind}, {self.status}, {self.title[:30]})"
