"""Document / DocumentVersion 操作态实体（DOMAIN §3 / §12.5，DOC-01 模型位）。

区分外部飞书文档与内部生成文档：

- **external_feishu**：PRD/技术方案等飞书 docx，飞书为权威，存 ``both``
  （快照 + ``canonical_url`` 引用），按 ``(feishu_tenant, external_ref)`` 去重定位。
- **internal_generated**：上线说明 / SDD spec 等 Friday 拥有的文档，可
  ``writeback_allowed`` 回写飞书——本 phase 仅立字段位，实际产出归 v0.7+。

版本链经 ``DocumentVersion.supersedes``（self FK）+ ``unique_together(document,
version)`` 强制版本唯一；``Document.current_version`` 指向当前版本。``work_item``
FK 关联交付脊柱（REFERENCES 操作态对应）。

落库只经 delivery ``DocumentService``（INV-6）；模型层不写业务 create/save 逻辑。
"""

import uuid

from django.db import models

from delivery.models.work_item import WorkItem


class DocumentType(models.TextChoices):
    """文档类型枚举（DOMAIN §3）。"""

    PRD = "prd", "PRD"
    TECH_PLAN = "tech_plan", "技术方案"
    RELEASE_NOTE = "release_note", "上线说明"
    SDD_SPEC = "sdd_spec", "SDD spec"
    OTHER = "other", "其他"


class DocumentSourceKind(models.TextChoices):
    """文档来源枚举：外部飞书 vs 内部生成（DOMAIN §3）。"""

    EXTERNAL_FEISHU = "external_feishu", "外部飞书"
    INTERNAL_GENERATED = "internal_generated", "内部生成"


class ContentStorage(models.TextChoices):
    """正文存储方式：快照 / 引用 / 二者（DOMAIN §3）。"""

    SNAPSHOT = "snapshot", "快照"
    REFERENCE = "reference", "引用"
    BOTH = "both", "快照+引用"


class Document(models.Model):
    """文档操作态实体（区分外部飞书 / 内部生成，DOMAIN §3 / §12.5）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    document_type = models.CharField(max_length=32, choices=DocumentType.choices)
    source_kind = models.CharField(max_length=32, choices=DocumentSourceKind.choices)

    # external 标识（飞书 doc token / 其他外部标识）
    external_ref = models.CharField(max_length=255, blank=True, default="")
    # 自托管/多租户深链可超默认 200，沿用 WorkItem.prd_url 的 1000 宽度
    canonical_url = models.URLField(max_length=1000, blank=True, default="")
    content_storage = models.CharField(
        max_length=16,
        choices=ContentStorage.choices,
        default=ContentStorage.BOTH,
    )

    # 前向字符串引用 + related_name="+" 避免与 DocumentVersion.document 反查名冲突；
    # SET_NULL 避免删版本抹 Document。
    current_version = models.ForeignKey(
        "delivery.DocumentVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    last_synced_at = models.DateTimeField(null=True, blank=True)
    # 内部生成且需回写飞书时 True；本 phase 仅字段位。
    writeback_allowed = models.BooleanField(default=False)

    # 同 app 直接类引用，REFERENCES 操作态对应；null 允许=反查未落库占位。
    work_item = models.ForeignKey(
        WorkItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    # 多租户区分（如 acme）
    feishu_tenant = models.CharField(max_length=64, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "delivery_document"
        verbose_name = "文档"
        verbose_name_plural = "文档"
        indexes = [
            # 30-04 PRD 检索路径
            models.Index(fields=["work_item", "document_type"]),
            # 30-02 external_feishu 去重定位
            models.Index(fields=["feishu_tenant", "external_ref"]),
        ]
        constraints = [
            # external_feishu 去重键 DB 级唯一（WR-01）：并发摄取下 get_or_create 的
            # SELECT FOR UPDATE 在目标行尚不存在时无行可锁，无约束会建出重复 Document。
            # 条件限非空 external_ref——internal_generated / 空 ref 行豁免，不在空键上互撞。
            models.UniqueConstraint(
                fields=["feishu_tenant", "external_ref"],
                condition=~models.Q(external_ref=""),
                name="uniq_document_feishu_tenant_external_ref",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.document_type}/{self.source_kind}:{self.external_ref}"


class DocumentVersion(models.Model):
    """文档版本（版本链经 supersedes self FK + unique_together，DOMAIN §12.5）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version = models.PositiveIntegerField()
    # 被本版本取代的旧版本；SET_NULL 与 §12.5 "supersedes FK(self,null)" 对齐。
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="superseded_by",
    )
    # 文档正文快照；降级缺料时可空，对齐"缺段不缺实体"。
    content = models.TextField(blank=True, default="")
    # sha256 hex；内容相等不翻版本，30-02 复用 knowledge hash 范式。
    content_hash = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_document_version"
        verbose_name = "文档版本"
        verbose_name_plural = "文档版本"
        unique_together = (("document", "version"),)
        indexes = [
            models.Index(fields=["document", "-version"]),
        ]

    def __str__(self) -> str:
        return f"{self.document_id}:v{self.version}"
