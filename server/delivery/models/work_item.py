"""canonical WorkItem 模型（操作态交付主对象）。

身份 = 飞书三元组 ``(feishu_project_key, work_item_type, work_item_id)``，由 DB
``unique_together`` 强制 INV-1（一个飞书需求/缺陷只对应一个 canonical WorkItem）。

字段按 source-of-truth 三分类（DOMAIN §1.2）：
- **mirror**：飞书权威，本地只读副本，每次 sync 覆盖。
- **friday_enhanced**：Friday 本地拥有，sync 不动。
- **writeback**：Friday 写回飞书再镜像回来。

落库只经 ``WorkItemService.upsert``（INV-6）；模型层不写业务 create/save 逻辑。
"""

import uuid

from django.db import models


class WorkItemOrigin(models.TextChoices):
    """WorkItem / SyncState 来源枚举。

    ``bitable_import`` / ``mr_reverse`` 本 phase 仅作枚举占位，真实调用方在
    Phase 31 / 32 接入。
    """

    FEISHU_WEBHOOK = "feishu_webhook", "飞书 webhook"
    MANUAL = "manual", "手动按 ID"
    BITABLE_IMPORT = "bitable_import", "Bitable 历史导入"
    MR_REVERSE = "mr_reverse", "MR 反查"


class WorkItem(models.Model):
    """飞书工作项的 canonical 操作态聚合（交付脊柱）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 自然键三元组（INV-1，unique_together 强制）
    feishu_project_key = models.CharField(max_length=64)
    work_item_type = models.CharField(max_length=32)
    work_item_id = models.BigIntegerField()

    feishu_project_simple_name = models.CharField(max_length=128, blank=True, default="")
    space = models.ForeignKey(
        "projects.Space",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_items",
    )
    origin = models.CharField(max_length=32, choices=WorkItemOrigin.choices)

    # mirror（飞书权威）
    title = models.CharField(max_length=512, blank=True, default="")
    status_state_key = models.CharField(max_length=64, blank=True, default="")
    status_sub_stage = models.CharField(max_length=64, blank=True, default="")
    status_display_name = models.CharField(max_length=128, blank=True, default="")
    is_archived_state = models.BooleanField(default=False)
    is_init_state = models.BooleanField(default=False)
    feishu_fields = models.JSONField(default=list)
    prd_url = models.URLField(max_length=1000, blank=True, default="")
    tech_doc_url = models.URLField(max_length=1000, blank=True, default="")

    # friday_enhanced（Friday 拥有）
    business_line_normalized = models.CharField(max_length=128, blank=True, default="")
    module_normalized = models.CharField(max_length=128, blank=True, default="")
    internal_note = models.TextField(blank=True, default="")

    # writeback（Friday 写回飞书再镜像）
    feishu_chat_id = models.CharField(max_length=128, blank=True, default="")

    # 元数据
    field_provenance = models.JSONField(default=dict)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    event_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "delivery_work_item"
        verbose_name = "工作项"
        verbose_name_plural = "工作项"
        unique_together = (("feishu_project_key", "work_item_type", "work_item_id"),)
        indexes = [
            models.Index(fields=["space", "work_item_type"]),
            models.Index(fields=["status_state_key"]),
        ]

    def __str__(self) -> str:
        return f"{self.work_item_type}/{self.work_item_id}:{self.title}"
