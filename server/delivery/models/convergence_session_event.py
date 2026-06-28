"""ConvergenceSessionEvent：收敛会话 trace 事件 append-only 持久化（Chassis v2 · P2）。

把 ``ConvergenceSessionService._emit_event`` 钩子产出的 trace 事件沉淀为稳定信封
``{event, session_id, work_item_id?, ts, payload}`` 的持久化行，为对外 adapter /
signal 投影（``process_event`` 来源，见 WORKFLOW-RUNTIME-SPEC §3）留稳定底座。

设计要点（守 INV-6 精神）：
- **append-only**：只追加、不就地改写——一条 trace 即一行，按 ``created_at`` 排序还原时序。
- **写入单一入口**：写入只经 ``ConvergenceSessionService._emit_event``，模型层不写任何
  create/save 业务方法。
- **event 开放集**：``event`` 为开放 ``CharField``，取值由 ``event_taxonomy`` 守护约束。
- **work_item 软引用**：``UUIDField(null)`` 软引用，不建 FK，避免与 WorkItem 删除耦合。
"""

import uuid

from django.db import models
from django.utils import timezone


class ConvergenceSessionEvent(models.Model):
    """收敛会话 trace 事件 append-only 行（统一信封持久化）。"""

    objects: "models.Manager[ConvergenceSessionEvent]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 归属一次 ConvergenceSession 收敛；删 session 级联删其事件流
    session = models.ForeignKey(
        "delivery.ConvergenceSession",
        on_delete=models.CASCADE,
        related_name="events",
    )
    # taxonomy 事件名（开放集，引用 event_taxonomy 常量；模型层不强制枚举）
    event = models.CharField(max_length=64)
    # 信封 work_item_id?（软引用 UUID，不建 FK，避免与 WorkItem 删除耦合）
    work_item = models.UUIDField(null=True, blank=True)
    # 信封 payload（progress/trace 字段，绝不落模型私有 CoT，INV-5）
    payload = models.JSONField(default=dict)
    # 信封事件时间（可由 emit 端传入；默认 now）
    ts = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "delivery_convergence_session_event"
        verbose_name = "收敛会话事件"
        verbose_name_plural = "收敛会话事件"
        # append-only 顺序：按写入时间还原 trace 时序
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["session", "ts"]),
            models.Index(fields=["event"]),
        ]

    def __str__(self) -> str:
        return f"ConvergenceSessionEvent({self.event}, {self.session_id})"
