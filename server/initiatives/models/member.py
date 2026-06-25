"""ProjectMember 成员模型（MEMBER-01/02）。

项目↔用户 多对多 + 身份角色。``ProjectRole.OWNER``（主R）每项目至多一个（partial
UniqueConstraint），可经 ``ProjectService.transfer_owner`` 原子转移。模型层无业务写方法
（INV-6，收口于 ``ProjectService``）。
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class ProjectRole(models.TextChoices):
    """项目成员身份角色（可扩展闭集）。"""

    OWNER = "owner", "主R"
    PM = "pm", "产品经理"
    FRONTEND = "frontend", "前端"
    BACKEND = "backend", "后端"
    QA = "qa", "测试"


class ProjectMember(models.Model):
    """项目成员关系（一人一项目一行）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "initiatives.Project",
        on_delete=models.CASCADE,
        related_name="members",
        verbose_name="项目",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="project_memberships",
        verbose_name="用户",
    )
    role = models.CharField(
        max_length=20,
        choices=ProjectRole.choices,
        default=ProjectRole.BACKEND,
        verbose_name="身份角色",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_project_members"
        verbose_name = "项目成员"
        verbose_name_plural = "项目成员"
        constraints = [
            # 一人一项目一行
            models.UniqueConstraint(
                fields=["project", "user"], name="uniq_project_member_user"
            ),
            # 主R 唯一：每项目至多一个 owner（partial constraint）。
            models.UniqueConstraint(
                fields=["project"],
                condition=models.Q(role=ProjectRole.OWNER),
                name="uniq_project_single_owner",
            ),
        ]
        indexes = [
            models.Index(fields=["project", "role"]),
            models.Index(fields=["user"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.project} ({self.get_role_display()})"
