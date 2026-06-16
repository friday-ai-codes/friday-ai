"""PlanSessionEvent：编排 trace 事件 append-only 持久化（DOMAIN §15，EVENT-01）。

把 Phase 36-40 经 ``PlanSessionService._emit_event`` 钩子产出的编排事件沉淀为稳定
§15 统一信封 ``{event, session_id, work_item_id?, ts, payload}`` 的持久化行，为
v0.11 对外 adapter 留稳定底座（INV-5：progress/trace，非模型私有 CoT）。

设计要点（守 INV-6 精神）：
- **append-only**：只追加、不就地改写——一条 trace 即一行，按 ``created_at`` 排序还原时序。
- **写入单一入口**：写入只经 ``PlanSessionService._emit_event``，模型层**不写**任何
  create/save 业务方法。
- **event 开放集**：``event`` 为开放 ``CharField``（v0.11 可扩展），取值由
  ``event_taxonomy.ALL_EVENTS`` 守护测试约束本 phase 范围，模型层不强制枚举。
- **work_item 软引用**：``UUIDField(null)`` 软引用（§15 信封 ``work_item_id?``），
  不建 FK——对齐 ``PlanSession.current_plan_version`` 软引用范式，避免与 WorkItem
  删除耦合。
"""

import uuid

from django.db import models
from django.utils import timezone


class PlanSessionEvent(models.Model):
    """编排 trace 事件 append-only 行（§15 统一信封持久化）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 归属一次 PlanSession 编排；删 session 级联删其事件流
    session = models.ForeignKey(
        "delivery.PlanSession",
        on_delete=models.CASCADE,
        related_name="events",
    )
    # §15 taxonomy 事件名（开放集，引用 event_taxonomy 常量；模型层不强制枚举）
    event = models.CharField(max_length=64)
    # §15 信封 work_item_id?（软引用 UUID，不建 FK，避免与 WorkItem 删除耦合）
    work_item = models.UUIDField(null=True, blank=True)
    # §15 信封 payload（progress/trace 字段，绝不落模型私有 CoT，INV-5）
    payload = models.JSONField(default=dict)
    # §15 信封事件时间（可由 emit 端传入；默认 now）
    ts = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_plan_session_event"
        verbose_name = "方案编排事件"
        verbose_name_plural = "方案编排事件"
        # append-only 顺序：按写入时间还原 trace 时序
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["session", "ts"]),
            models.Index(fields=["event"]),
        ]

    def __str__(self) -> str:
        return f"PlanSessionEvent({self.event}, {self.session_id})"
