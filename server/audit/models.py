"""审计事件模型 —— append-only 审计日志。

覆盖管理员/敏感操作的统一审计留痕（AUDIT-01）：

- ``AuditEvent``：单一审计事件，记录 actor / action / target / before-after 快照。

**append-only 约束**：记录只增不改不删，`save()` 拒绝更新已有记录，
`delete()` 直接抛异常。审计完整性由模型层守护。

**软关联**：target 使用 ``target_type`` + ``target_id`` 软引用，不建 FK，
避免 CASCADE 复杂度。actor 使用 FK 到 User（nullable, SET_NULL），系统操作
时 actor 为 NULL、actor_type 为 "system"。
"""

import uuid

from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    """统一审计事件记录（AUDIT-01）。

    每次敏感操作（成员增删改、凭证操作、配置变更等）写入一条，
    append-only：不提供更新或删除语义。
    """

    class Source(models.TextChoices):
        API = "api", "API 请求"
        SYSTEM = "system", "系统操作"
        SCHEDULER = "scheduler", "定时任务"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ---- Actor ----
    # FK 到 User，nullable（系统操作时为 NULL）；SET_NULL 避免级联删除审计记录。
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    # 冗余存储用户名，防止 actor 被删后审计记录丢失标识。
    actor_display = models.CharField(max_length=150, default="")
    actor_type = models.CharField(max_length=20, default="user")  # user / system

    # ---- Action ----
    action = models.CharField(max_length=100, db_index=True)  # e.g. "user.created"

    # ---- Target（软关联） ----
    target_type = models.CharField(max_length=100, db_index=True)  # e.g. "User"
    target_id = models.CharField(max_length=255, default="")  # PK as string

    # ---- Snapshots ----
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)

    # ---- Metadata ----
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.API)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(default="")

    class Meta:
        db_table = "audit_event"
        verbose_name = "审计事件"
        verbose_name_plural = "审计事件"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["actor", "timestamp"]),
        ]

    def __str__(self) -> str:
        return f"AuditEvent({self.action}, {self.target_type}:{self.target_id})"

    # ---- append-only 守护 ----

    def save(self, *args, **kwargs):
        """拒绝更新已有记录 —— 审计事件只能新增，不能修改。"""
        if self.pk and AuditEvent.objects.filter(pk=self.pk).exists():
            raise ValueError("AuditEvent is append-only — updates are not allowed")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """拒绝删除 —— 审计事件永久保留。"""
        raise ValueError("AuditEvent is append-only — deletion is not allowed")
