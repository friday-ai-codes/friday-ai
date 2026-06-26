"""ProjectBranch 分支↔项目多绑定模型（BIND-01）。

一个项目可绑定多个 ``(repository, branch_name)``；同一 ``(project, repository,
branch_name)`` 唯一。``source`` 标记绑定来源（manual 手动 / plan 方案流水线 /
coding 编码自动），``feishu_board_id`` 冗余项目看板 id 便于 branch↔board 反查。

模型层**不提供业务 create/save 方法**——所有写入收口于
``initiatives.services.ProjectBranchService``（INV-6，由 ``test_project_branch_inv6_guard``
grep 守护）。镜像 ``Project`` / ``ProjectWorkItemLink`` 范式。
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class BranchSource(models.TextChoices):
    """分支绑定来源（闭集）。

    - ``manual``：前端手动绑定（本期 REST 唯一来源）；
    - ``plan``：方案流水线写入（Phase 89）；
    - ``coding``：编码节点 git push 自动绑定（Phase 89）。
    """

    MANUAL = "manual", "手动绑定"
    PLAN = "plan", "方案流水线"
    CODING = "coding", "编码自动"


class ProjectBranch(models.Model):
    """项目↔分支多绑定（一项目多分支，唯一 (project, repository, branch_name)）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "initiatives.Project",
        on_delete=models.CASCADE,
        related_name="branch_bindings",
        verbose_name="项目",
    )
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="project_branch_bindings",
        verbose_name="仓库",
    )
    branch_name = models.CharField(max_length=255, verbose_name="分支名")
    source = models.CharField(
        max_length=20,
        choices=BranchSource.choices,
        default=BranchSource.MANUAL,
        verbose_name="绑定来源",
    )
    # branch↔board 结合：绑定时可携项目飞书看板 id 冗余，便于按分支反查所属看板。
    feishu_board_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="飞书看板 ID",
        help_text="冗余项目看板 id，便于 branch↔board 反查（绑定时按需携带）",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_project_branches",
        verbose_name="绑定者",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_project_branches"
        verbose_name = "项目分支绑定"
        verbose_name_plural = "项目分支绑定"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "repository", "branch_name"],
                name="uniq_project_repo_branch",
            ),
        ]
        indexes = [
            # 分支名反查（BIND-02 lookup_project_by_branch）走索引。
            models.Index(fields=["branch_name"]),
            models.Index(fields=["repository", "branch_name"]),
        ]

    def __str__(self) -> str:
        return f"{self.project_id} ↔ {self.repository_id}:{self.branch_name} ({self.source})"
