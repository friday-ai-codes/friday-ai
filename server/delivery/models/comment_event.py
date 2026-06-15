"""WorkItemCommentEvent：append-only 评论事件流（DOMAIN §2 / §12.4，CMT-01/CMT-02）。

评论不建"当前快照表"，而是以事件流式入库（created/replied/edited/deleted/
approval），当前评论树由对事件流的投影（读时计算）得出——为灰区讨论/方案再生成
提供清晰事件边界。

append-only：编辑/删除是**新事件行**（event_type=edited/deleted），不就地改写既有行
（CMT-02，保留可追溯历史）。模型层不写任何 create/save 业务逻辑——落库归 29-02
``CommentEventService`` 单一入口（守 INV-6 精神）。
"""

import uuid

from django.db import models

from delivery.models.work_item import WorkItem


class CommentEventType(models.TextChoices):
    """评论事件类型枚举。

    ``edited`` / ``deleted`` 为枚举占位：若飞书 webhook/API 不提供编辑/删除信号，
    本 phase 仅实际落 ``created`` / ``replied`` / ``approval``，``edited`` / ``deleted``
    留位 deferred（per CONTEXT Grey Area 3，CMT-01），后续真实信号可得时接入。
    """

    CREATED = "created", "根评论创建"
    REPLIED = "replied", "回复"
    EDITED = "edited", "编辑"
    DELETED = "deleted", "删除"
    APPROVAL = "approval", "审批"


class ApprovalSemantic(models.TextChoices):
    """审批语义枚举（通过/驳回）。"""

    NONE = "none", "无"
    APPROVE = "approve", "通过"
    REJECT = "reject", "驳回"


class WorkItemCommentEvent(models.Model):
    """工作项评论事件（追加流，非快照）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_item = models.ForeignKey(
        WorkItem,
        on_delete=models.CASCADE,
        related_name="comment_events",
    )
    feishu_comment_id = models.CharField(max_length=128)
    # 线程父：根评论为空，回复指向父评论 id
    thread_parent_id = models.CharField(max_length=128, blank=True, default="")
    event_type = models.CharField(max_length=16, choices=CommentEventType.choices)
    author = models.CharField(max_length=128, blank=True, default="")
    body = models.TextField(blank=True, default="")
    attachments = models.JSONField(default=list)
    approval_semantic = models.CharField(
        max_length=16,
        choices=ApprovalSemantic.choices,
        default=ApprovalSemantic.NONE,
    )
    event_time = models.DateTimeField(null=True, blank=True)
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_work_item_comment_event"
        verbose_name = "工作项评论事件"
        verbose_name_plural = "工作项评论事件"
        indexes = [
            models.Index(fields=["work_item", "event_time"]),
        ]
        # 去重锚 DB 级唯一约束：让 ``get_or_create`` 在并发/跨路径摄取
        # （webhook 后台 append 与 ingest_comments 经 run_in_background 竞态）下落到
        # 唯一索引兜底——check-then-insert 间隙的重复 INSERT 触发 IntegrityError，
        # service 据此回退视作"已追加"，避免重复事件行（WR-02）。
        # 注意：``event_time`` 可空，Postgres/SQLite 下 NULL 互不相等，故该约束对
        # ``event_time IS NULL`` 的事件不强制唯一——跨路径应统一时间戳来源以减少锚漂移。
        constraints = [
            models.UniqueConstraint(
                fields=["work_item", "feishu_comment_id", "event_type", "event_time"],
                name="uniq_comment_event_anchor",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.work_item_id}:{self.feishu_comment_id}:{self.event_type}"
