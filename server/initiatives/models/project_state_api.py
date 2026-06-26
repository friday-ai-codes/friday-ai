"""项目 STATE 结构化「已完成 API 清单」模型（DOC-02）。

``ProjectStateApi`` 以 (method, path) 为业务幂等键记录项目对外/内部 API 的结构化清单
（method/path/params/status/贡献来源），供 STATE 文件「已完成 API 清单」段派生渲染。
Cursor/hook 回写（HOOK-03）留 Phase 86；本期仅建模型 + 唯一约束以支撑后续 upsert 幂等。

模型层**不提供业务 create/save 方法**——所有写入收口于
``initiatives.services.ProjectDocService``（INV-6，由 ``test_project_doc_inv6_guard`` grep 守护，
随 82-02 落地）。
"""

from __future__ import annotations

import uuid

from django.db import models


class ApiStatus(models.TextChoices):
    """API 开发状态。"""

    PLANNED = "planned", "待开发"
    IMPLEMENTED = "implemented", "已完成"
    DEPRECATED = "deprecated", "已废弃"


class ApiSource(models.TextChoices):
    """API 清单条目贡献来源。"""

    MANUAL = "manual", "手动"
    AGENT = "agent", "Agent"
    HOOK = "hook", "IDE 回写"


class ProjectStateApi(models.Model):
    """项目结构化 API 清单条目（每项目每 (method, path) 至多一行）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "initiatives.Project",
        on_delete=models.CASCADE,
        related_name="state_apis",
        verbose_name="项目",
    )
    method = models.CharField(max_length=10, verbose_name="HTTP 方法")
    path = models.CharField(max_length=500, verbose_name="路径")
    params = models.JSONField(default=dict, blank=True, verbose_name="参数")
    status = models.CharField(
        max_length=20,
        choices=ApiStatus.choices,
        default=ApiStatus.PLANNED,
        verbose_name="状态",
    )
    source = models.CharField(
        max_length=20,
        choices=ApiSource.choices,
        default=ApiSource.MANUAL,
        verbose_name="贡献来源",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_project_state_apis"
        verbose_name = "项目 API 清单"
        verbose_name_plural = "项目 API 清单"
        ordering = ["-created_at"]
        constraints = [
            # 每项目每 (method, path) 至多一行（支持后续 upsert 幂等）。
            models.UniqueConstraint(
                fields=["project", "method", "path"], name="uniq_project_state_api"
            ),
        ]
        indexes = [
            models.Index(fields=["project", "status"]),
        ]

    def __str__(self) -> str:
        return f"ProjectStateApi({self.method} {self.path})"
