"""Project 聚合根模型（PROJ-01/02/04/05）。

``Project`` 是 v0.15.0 的领域聚合根：隶属一个组织单元 ``Space``、关联一个飞书"项目跟踪"
看板、含可扩展状态机。模型层**不提供业务 create/save 方法**——所有写入收口于
``initiatives.services.ProjectService``（INV-6，由 ``test_project_inv6_guard`` grep 守护）。

幂等键：``(space, feishu_project_key)`` —— ``feishu_project_key`` 非空时唯一（partial
UniqueConstraint）；无飞书 key 的手动项目允许并存（靠 id 区分）。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from initiatives.models.member import ProjectMember


class ProjectStatus(models.TextChoices):
    """项目状态（可扩展闭集）。"""

    DEVELOPING = "developing", "开发中"
    ARCHIVED = "archived", "归档"
    TERMINATED = "terminated", "终止"


class Project(models.Model):
    """项目聚合根：隶属 Space + 关联飞书看板 + 状态机。"""

    # 反向关系类型声明
    members: "QuerySet[ProjectMember]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    space = models.ForeignKey(
        "projects.Space",
        on_delete=models.CASCADE,
        related_name="projects",
        verbose_name="所属空间",
    )
    name = models.CharField(max_length=200, verbose_name="项目名称")
    description = models.TextField(blank=True, default="", verbose_name="项目描述")
    status = models.CharField(
        max_length=20,
        choices=ProjectStatus.choices,
        default=ProjectStatus.DEVELOPING,
        verbose_name="状态",
    )

    # 飞书"项目跟踪"看板引用（语义对齐既有 feishu_project_key 命名）
    feishu_project_key = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="飞书项目 Key",
        help_text="飞书'项目跟踪'看板的 project_key；非空时与 space 构成幂等键",
    )
    feishu_board_url = models.URLField(
        max_length=1000, blank=True, default="", verbose_name="飞书看板链接"
    )
    feishu_board_id = models.CharField(
        max_length=100, blank=True, default="", verbose_name="飞书看板 ID"
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_projects",
        verbose_name="创建者",
    )

    # 项目↔项目轻量关联（through ProjectRelation，symmetrical=False）。
    # KnowledgeEdge 富建模留 Phase 79（KLINK-02）——本期最小可用关联表。
    related_projects = models.ManyToManyField(
        "self",
        through="initiatives.ProjectRelation",
        symmetrical=False,
        related_name="related_to",
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_projects"
        verbose_name = "项目"
        verbose_name_plural = "项目"
        ordering = ["-created_at"]
        constraints = [
            # 幂等键：feishu_project_key 非空时 (space, feishu_project_key) 唯一。
            # 空 key 的手动项目可并存（condition 排除空串）。
            models.UniqueConstraint(
                fields=["space", "feishu_project_key"],
                condition=~models.Q(feishu_project_key=""),
                name="uniq_project_space_feishu_key",
            ),
        ]
        indexes = [
            models.Index(fields=["space", "status"]),
            models.Index(fields=["feishu_project_key"]),
        ]

    def __str__(self) -> str:
        return self.name
