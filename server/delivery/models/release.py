"""Release 账本宽容模型（DOMAIN §4 / §12.6，REL-01）。

先建**宽容模型**，不被 Bitable 列名绑死：每个 row-bearing 模型带 ``raw_row``
JSONField 保留 Bitable 原始行，adapter 演进 / 列映射变化**不丢数据**（REL-01
核心）。真实多维表格列结构映射归 v2 REL-03，本模块只立宽容字段子集。

- ``ReleaseBatch``：一次上线 / 发布窗口。
- ``ReleaseRecord``：某需求 / 缺陷在某次上线中的记录（= 一个 Bitable 行）。
  ``work_item`` FK 反查目标未落库时为 ``None``，用 ``work_item_external_id``
  占位（对齐 ``WorkItemRelation.target_external_id`` / ``Document.work_item``
  范式），待 31-02 ``ReleaseService`` 反查回填。Bitable natural key
  ``{app_token}:{table_id}:{record_id}`` 落 ``bitable_record_key``，非空时
  DB 级条件唯一（镜像 ``Document`` uniq 范式，支撑 31-03 adapter 幂等 upsert）。
- ``ReleaseArtifact``：证据（MR / 分支 / commit / diff / 上线说明 / 文档）。

落库只经 delivery ``ReleaseService``（INV-6 精神，归 31-02）；模型层不写业务
create/save 逻辑。
"""

import uuid

from django.db import models

from delivery.models.work_item import WorkItem


class ReleaseSource(models.TextChoices):
    """Release 批次来源枚举（DOMAIN §4）。"""

    BITABLE = "bitable", "多维表格"
    MANUAL = "manual", "手动"


class ReleaseArtifactType(models.TextChoices):
    """Release 证据类型枚举（DOMAIN §4 / §12.6）。"""

    MR = "mr", "合并请求"
    BRANCH = "branch", "分支"
    COMMIT = "commit", "提交"
    DIFF = "diff", "差异"
    RELEASE_NOTE = "release_note", "上线说明"
    DOC = "doc", "文档"


def build_bitable_record_key(app_token: str, table_id: str, record_id: str) -> str:
    """构造 Bitable 记录 natural key ``{app_token}:{table_id}:{record_id}``。

    natural key 唯一构造入口（31-03 adapter 复用，避免拼接漂移）。任一段为空
    时返回 ``""``——无法定位即不立 key（条件唯一约束据此豁免空键行）。
    """
    if not app_token or not table_id or not record_id:
        return ""
    return f"{app_token}:{table_id}:{record_id}"


class ReleaseBatch(models.Model):
    """一次上线 / 发布窗口（DOMAIN §4 / §12.6）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=512, blank=True, default="")
    released_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=16, choices=ReleaseSource.choices)
    # 批次级外部引用（如 Bitable app/table 标识或人工标签）
    external_ref = models.CharField(max_length=255, blank=True, default="")
    # 保留 Bitable 原始行，adapter 演进不丢数据（REL-01）
    raw_row = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "delivery_release_batch"
        verbose_name = "上线批次"
        verbose_name_plural = "上线批次"
        constraints = [
            # 非空 external_ref DB 级唯一（支撑 batch 级幂等：重复摄取同一张表
            # external_ref={app_token}:{table_id} 收敛同批，不累积空批次，WR-02）。
            # 条件限非空——空键批次（如手动录入未给键）豁免，镜像 ReleaseRecord
            # uniq_release_record_bitable_key 范式。
            models.UniqueConstraint(
                fields=["external_ref"],
                condition=~models.Q(external_ref=""),
                name="uniq_release_batch_external_ref",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source}:{self.name or self.id}"


class ReleaseRecord(models.Model):
    """某需求 / 缺陷在某次上线中的记录（一个 Bitable 行，DOMAIN §4 / §12.6）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        ReleaseBatch,
        on_delete=models.CASCADE,
        related_name="records",
    )
    # 同 app 直接类引用；null 允许=反查目标未落库时占位，SET_NULL 避免删 wi 抹记录。
    work_item = models.ForeignKey(
        WorkItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="release_records",
    )
    # 反查目标未落库占位（对齐 WorkItemRelation.target_external_id）
    work_item_external_id = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=64, blank=True, default="")
    note = models.TextField(blank=True, default="")
    # 上线日期（ms epoch）——从 Bitable「上线日期」列派生，用于看板按时间倒序与展示。
    # 可空：旧行 / 无日期行豁免；建索引支撑排序。
    release_date = models.BigIntegerField(null=True, blank=True)
    # Bitable natural key {app_token}:{table_id}:{record_id} 落地点（独立字段，便于
    # 幂等 upsert，不复用 external_ref）；非空时 DB 级条件唯一。
    bitable_record_key = models.CharField(max_length=255, blank=True, default="")
    # 保留 Bitable 原始行，adapter 演进不丢数据（REL-01）
    raw_row = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "delivery_release_record"
        verbose_name = "上线记录"
        verbose_name_plural = "上线记录"
        indexes = [
            # 反查路径：经 work_item / work_item_external_id 关联交付脊柱
            models.Index(fields=["work_item"]),
            models.Index(fields=["work_item_external_id"]),
            # 看板按上线日期倒序（同 batch 下分页排序）
            models.Index(fields=["batch", "-release_date"]),
        ]
        constraints = [
            # 非空 natural key DB 级唯一（支撑 31-03 adapter 幂等 upsert）。
            # 条件限非空——空键行（无法定位的 Bitable 行）豁免，不在空键上互撞，
            # 镜像 document.py uniq_document_feishu_tenant_external_ref 范式。
            models.UniqueConstraint(
                fields=["bitable_record_key"],
                condition=~models.Q(bitable_record_key=""),
                name="uniq_release_record_bitable_key",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.batch_id}:{self.bitable_record_key or self.id}"


class ReleaseArtifact(models.Model):
    """上线证据：MR / 分支 / commit / diff / 上线说明 / 文档（DOMAIN §4 / §12.6）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    release_record = models.ForeignKey(
        ReleaseRecord,
        on_delete=models.CASCADE,
        related_name="artifacts",
    )
    artifact_type = models.CharField(max_length=16, choices=ReleaseArtifactType.choices)
    # MR URL / sha / doc token；URL 可超长沿用 1000 宽度（对齐 WorkItem.prd_url）。
    ref = models.CharField(max_length=1000, blank=True, default="")
    payload = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_release_artifact"
        verbose_name = "上线证据"
        verbose_name_plural = "上线证据"

    def __str__(self) -> str:
        return f"{self.release_record_id}:{self.artifact_type}"


__all__ = [
    "ReleaseSource",
    "ReleaseArtifactType",
    "ReleaseBatch",
    "ReleaseRecord",
    "ReleaseArtifact",
    "build_bitable_record_key",
]
