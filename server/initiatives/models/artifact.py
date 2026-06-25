"""工件类型注册表 + 工件实例模型（ARTIFACT-01/02/05）。

把"需求文档/feature list/研发 Spec/UI 稿/UI 评审/埋点文档/埋点评审/复盘"等外部依赖统一抽象为
**可配置类型的工件**，挂到项目：

- ``ArtifactType``：可配置类型注册表（内置 8 类经 data migration seed，``builtin=True`` 禁删只可禁用）。
- ``Artifact``：工件实例（多载体），挂项目、记类型/载体/链接/标题/版本/贡献者。

模型层**不提供业务 create/save 方法**——所有写入收口于 ``initiatives.services.ArtifactService``
（INV-6，由 ``test_artifact_inv6_guard`` grep 守护）。类型删除受既有实例约束保护：``Artifact.type``
FK ``on_delete=PROTECT``（DB 兜底）+ ``ArtifactService`` 预检（有实例则拒删；builtin 禁删）。
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class ArtifactCarrier(models.TextChoices):
    """工件载体语义（载体决定在线查看与是否可 RAG 全文）。"""

    FEISHU_DOC = "feishu_doc", "飞书文档"
    FEISHU_BITABLE = "feishu_bitable", "飞书多维表格"
    EXTERNAL_LINK = "external_link", "外部链接"
    MARKDOWN = "markdown", "Markdown"
    REPO_FILE = "repo_file", "仓库文件"


# 可全文 RAG 摄取的文字载体（图形外链 external_link 仅元数据，不入 RAG 正文）。
TEXT_CARRIERS: frozenset[str] = frozenset(
    {
        ArtifactCarrier.FEISHU_DOC,
        ArtifactCarrier.FEISHU_BITABLE,
        ArtifactCarrier.MARKDOWN,
        ArtifactCarrier.REPO_FILE,
    }
)


class ArtifactType(models.Model):
    """可配置工件类型注册表（ARTIFACT-01/05）。

    内置 8 类经 data migration seed（``builtin=True``）。后台（超管）可新增/禁用/删除自定义类型；
    builtin 禁删只可禁用；禁用类型不可新建实例、既有实例只读（``ArtifactService`` 校验）。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.SlugField(max_length=80, unique=True, verbose_name="类型标识")
    name = models.CharField(max_length=100, verbose_name="类型名称")
    carrier = models.CharField(
        max_length=20,
        choices=ArtifactCarrier.choices,
        default=ArtifactCarrier.EXTERNAL_LINK,
        verbose_name="默认载体",
    )
    ragable = models.BooleanField(default=False, verbose_name="可全文 RAG")
    enabled = models.BooleanField(default=True, verbose_name="启用")
    builtin = models.BooleanField(default=False, verbose_name="内置")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_artifact_types"
        verbose_name = "工件类型"
        verbose_name_plural = "工件类型"
        ordering = ["-builtin", "key"]
        indexes = [
            models.Index(fields=["enabled"]),
        ]

    def __str__(self) -> str:
        return f"{self.name}（{self.key}）"


class Artifact(models.Model):
    """工件实例（ARTIFACT-02），挂项目。

    ``type`` FK ``on_delete=PROTECT``——删除有实例的类型在 DB 层被拒（service 预检为第一道防线）。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "initiatives.Project",
        on_delete=models.CASCADE,
        related_name="artifacts",
        verbose_name="项目",
    )
    type = models.ForeignKey(
        "initiatives.ArtifactType",
        on_delete=models.PROTECT,
        related_name="artifacts",
        verbose_name="类型",
    )
    carrier = models.CharField(
        max_length=20,
        choices=ArtifactCarrier.choices,
        verbose_name="载体",
    )
    title = models.CharField(max_length=300, verbose_name="标题")
    url = models.CharField(
        max_length=1000,
        blank=True,
        default="",
        verbose_name="链接",
        help_text="外链 / 飞书文档·表格链接",
    )
    content_ref = models.TextField(
        blank=True,
        default="",
        verbose_name="内容引用",
        help_text="md/内部工件正文，或仓库文件路径引用",
    )
    version = models.PositiveIntegerField(default=1, verbose_name="版本")
    contributor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contributed_artifacts",
        verbose_name="贡献者",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "initiative_artifacts"
        verbose_name = "工件"
        verbose_name_plural = "工件"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project", "type"]),
            models.Index(fields=["carrier"]),
        ]

    def __str__(self) -> str:
        return self.title
