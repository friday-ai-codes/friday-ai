"""AuditEvent：统一不可篡改审计事件 append-only 模型（AUDIT-01）。

为成员/凭证/飞书同步/仓库权限/排除规则/清理任务/API key 等敏感操作提供干净、
不可篡改、可被任意 app 无环 import 的存储契约。逐项镜像 ``WorkItemStatusEvent`` /
``PlanSessionEvent`` 的 append-only 模型形状（UUID PK、双时间戳、查询索引）。

设计要点（per RESEARCH §2）：
- **append-only 模型层守护**：既有行 ``save()`` / 任意 ``delete()`` 抛
  ``AuditEventImmutableError``；首次 create（``_state.adding is True``）放行。
  这是设计上**不期望被触发**的护栏——正常路径只 create（写入单一入口归 Plan 02
  ``AuditService``）。注意 ``.objects.update()`` / ``bulk_*`` 绕过 ``save()``，由
  Plan 02 的 INV-6 grep 守护兜底（双层防御）。
- **actor 标量软引用**：``actor_id`` 用可空标量 UUID（软引用 ``accounts.User.id``）
  + ``actor_repr`` 人类可读快照，**不建 FK**——删用户绝不级联 UPDATE/删除审计行，
  保最纯不可篡改（对齐 ``ProviderCredential.scope_id`` / ``PlanSessionEvent.work_item``
  既有「刻意不用 FK 避免级联」范式，per RESEARCH §2.1）。
- **双时间戳**：``occurred_at`` 业务事件时间（emit 端可传入，默认 now，非
  ``auto_now_add``）+ ``recorded_at`` 不可变落库插入戳（``auto_now_add``）。
"""

import uuid

from django.db import models
from django.utils import timezone


class AuditEventImmutableError(Exception):
    """审计行不可篡改护栏：既有行 save / 任意 delete 触发。

    append-only 语义的第一道防线（模型层）。设计上**不期望**在正常路径被触发——
    正常写入只经首次 create。第二道防线是 Plan 02 的 INV-6 grep 源码守护
    （拦截 ``.objects.update()`` / ``bulk_*`` 等绕过 ``save()`` 的旁路写表）。
    """


class AuditEvent(models.Model):
    """统一不可篡改审计事件（append-only 行，表 ``audit_event``）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # actor 软引用 accounts.User.id（null = 系统/匿名 actor）；不建 FK，删用户不触碰审计行
    actor_id = models.UUIDField(null=True, blank=True, db_index=True)
    # actor 人类可读快照（如 "zhangsan (superuser)"），删用户后仍可读
    actor_repr = models.CharField(max_length=255, blank=True, default="")

    # taxonomy 稳定常量值（verb.object，开放 CharField 不强制 DB 枚举）
    action = models.CharField(max_length=64, db_index=True)

    # 目标实体类型（如 "user" / "provider_credential" / "repository"）
    target_type = models.CharField(max_length=64, blank=True, default="")
    # 目标主键，字符串存（容纳 UUID / int / 复合键，避免类型锁死）
    target_id = models.CharField(max_length=128, blank=True, default="")
    # 目标人类可读快照（如 "仓库 friday-ai"），关联对象删除后审计仍可读
    target_repr = models.CharField(max_length=255, blank=True, default="")

    # 操作前/后值快照（经脱敏入口落库，绝不存明文凭证——脱敏归 Plan 02）
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)

    # 审计来源（web / api / feishu / workflow / system），Phase 55 过滤维度
    source = models.CharField(max_length=32, blank=True, default="")

    # 业务事件发生时间（emit 端可传入，默认 now；非 auto_now_add）
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    # 不可变落库插入戳
    recorded_at = models.DateTimeField(auto_now_add=True)

    # 附加上下文（IP / request_id / 链路 id 等，经脱敏入口落库）
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "audit_event"
        verbose_name = "审计事件"
        verbose_name_plural = "审计事件"
        # 查询默认最近优先
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["action"]),
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["actor_id"]),
            models.Index(fields=["occurred_at"]),
            # 常用「某类操作 + 时间范围」组合（为 Phase 55 查询过滤铺底）
            models.Index(fields=["action", "occurred_at"]),
        ]

    def save(self, *args, **kwargs):
        """append-only 守护：既有行再 save（update）拒绝，首次 create 放行。"""
        if not self._state.adding:
            raise AuditEventImmutableError("AuditEvent 不可更新（append-only）")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """append-only 守护：审计行不可删除。"""
        raise AuditEventImmutableError("AuditEvent 不可删除（append-only）")

    def __str__(self) -> str:
        return f"AuditEvent({self.action}, {self.target_type}:{self.target_id})"
