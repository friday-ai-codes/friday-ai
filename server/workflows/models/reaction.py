"""Reaction runtime model definitions (Chassis v2 · P0).

反应运行时（Signal → Reaction）的持久化底座。设计要点（见
`.planning/WORKFLOW-RUNTIME-SPEC.md`）：

- `WorkflowReaction`：一条"在宿主某信号上触发某横切副作用"的声明式配置
  （通知 / 文档 / 字段回写 / webhook / 告警）。它是横切反应的事实源，
  画布上的隐藏边只是它的派生渲染（P4）。
- `ReactionExecution`：一次反应执行的留痕，带幂等键，服务重启后可据此
  判断"是否已执行过"，避免同一信号重放导致重复副作用。

复用既有 `AlertRule`/`AlertRuleExecution` 的成熟"匹配→执行→留痕 + 幂等
(unique_together) + 冷却"模式，但把触发源从写死的 4 个生命周期事件泛化为
任意 lifecycle signal（见 `workflows.reactions.signal`）。
"""

import uuid

from django.db import models
from django.utils import timezone


class ReactionBlockingMode(models.TextChoices):
    """反应阻塞模式。

    - ``non_blocking``：通知 / 文档 / 回写 / webhook 等横切副作用，失败可见、
      可重试，但**绝不**误杀主交付链路（默认）。
    - ``gate``：会改变"主交付是否继续"的能力（如人工审批）。gate 语义仍由
      DAG 节点承载，这里仅作标注，运行时不把 gate 当普通订阅触发。
    - ``compensation``：失败补偿动作（后续阶段使用）。
    """

    NON_BLOCKING = "non_blocking", "非阻塞"
    GATE = "gate", "闸门"
    COMPENSATION = "compensation", "补偿"


class ReactionExecutionStatus(models.TextChoices):
    """反应执行状态。"""

    PENDING = "pending", "待执行"
    DELIVERED = "delivered", "已送达"
    FAILED = "failed", "失败"


class WorkflowReaction(models.Model):
    """工作流反应配置：在宿主节点的某个信号上触发横切副作用。"""

    objects: "models.Manager[WorkflowReaction]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    workflow = models.ForeignKey(
        "workflows.Workflow",
        on_delete=models.CASCADE,
        related_name="reactions",
        verbose_name="所属工作流",
    )

    # 宿主节点（信号来源主体）。null = 工作流级反应（订阅任意节点的该信号）。
    host_node = models.ForeignKey(
        "workflows.WorkflowNode",
        on_delete=models.CASCADE,
        related_name="reactions",
        null=True,
        blank=True,
        verbose_name="宿主节点",
        help_text="null 表示订阅工作流内任意节点的该信号",
    )

    # 订阅的信号名（见 workflows.reactions.signal.SIGNAL_NAMES）。
    signal_name = models.CharField(
        max_length=64,
        verbose_name="订阅信号",
        help_text="如 node.completed / node.failed / artifact.produced",
    )

    # 目标副作用类型（见 workflows.reactions.runtime 的 executor 注册表）。
    target_type = models.CharField(
        max_length=40,
        verbose_name="目标类型",
        help_text="notify_feishu_im / feishu_doc_create / writeback / webhook / alert",
    )

    # 目标执行所需配置（chat_id / url / 模板等），随 target_type 而异。
    config = models.JSONField(default=dict, blank=True, verbose_name="目标配置")

    blocking_mode = models.CharField(
        max_length=20,
        choices=ReactionBlockingMode.choices,
        default=ReactionBlockingMode.NON_BLOCKING,
        verbose_name="阻塞模式",
    )

    # 重试策略：{max_attempts: int, backoff_seconds: int}
    retry_policy = models.JSONField(default=dict, blank=True, verbose_name="重试策略")

    enabled = models.BooleanField(default=True, verbose_name="启用")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workflow_reactions"
        verbose_name = "工作流反应"
        verbose_name_plural = "工作流反应"
        indexes = [
            models.Index(fields=["workflow", "signal_name", "enabled"]),
            models.Index(fields=["host_node", "signal_name"]),
        ]

    def __str__(self) -> str:
        return f"{self.signal_name} -> {self.target_type} ({self.id})"

    @property
    def max_attempts(self) -> int:
        try:
            return max(1, int((self.retry_policy or {}).get("max_attempts", 1)))
        except (TypeError, ValueError):
            return 1

    @property
    def backoff_seconds(self) -> int:
        try:
            return max(0, int((self.retry_policy or {}).get("backoff_seconds", 0)))
        except (TypeError, ValueError):
            return 0


class ReactionExecution(models.Model):
    """反应执行留痕（幂等 + 可重试 + 失败可见）。"""

    objects: "models.Manager[ReactionExecution]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    reaction = models.ForeignKey(
        WorkflowReaction,
        on_delete=models.CASCADE,
        related_name="executions",
        verbose_name="反应配置",
    )
    workflow_execution = models.ForeignKey(
        "workflows.WorkflowExecution",
        on_delete=models.CASCADE,
        related_name="reaction_executions",
        verbose_name="工作流执行",
    )

    # 幂等键：execution_id + host_node_id + signal_name + reaction_id。
    # 同一信号重放时命中已有记录 → 不重复执行副作用。
    idempotency_key = models.CharField(
        max_length=255,
        verbose_name="幂等键",
    )

    status = models.CharField(
        max_length=20,
        choices=ReactionExecutionStatus.choices,
        default=ReactionExecutionStatus.PENDING,
        verbose_name="状态",
    )

    attempts = models.PositiveIntegerField(default=0, verbose_name="尝试次数")
    last_error = models.TextField(blank=True, default="", verbose_name="最近错误")
    triggered_signal = models.CharField(
        max_length=64, blank=True, default="", verbose_name="触发信号"
    )
    response_data = models.JSONField(default=dict, blank=True, verbose_name="响应数据")

    triggered_at = models.DateTimeField(auto_now_add=True, verbose_name="触发时间")
    delivered_at = models.DateTimeField(null=True, blank=True, verbose_name="送达时间")

    class Meta:
        db_table = "workflow_reaction_executions"
        verbose_name = "反应执行记录"
        verbose_name_plural = "反应执行记录"
        ordering = ["-triggered_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["reaction", "workflow_execution", "idempotency_key"],
                name="uniq_reaction_execution_idempotency",
            )
        ]
        indexes = [
            models.Index(fields=["workflow_execution", "status"]),
            models.Index(fields=["status", "triggered_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.idempotency_key} - {self.status}"

    def mark_delivered(self, response: dict | None = None) -> None:
        self.status = ReactionExecutionStatus.DELIVERED
        self.delivered_at = timezone.now()
        if response is not None:
            self.response_data = response
        self.save(update_fields=["status", "delivered_at", "response_data"])

    async def amark_delivered(self, response: dict | None = None) -> None:
        self.status = ReactionExecutionStatus.DELIVERED
        self.delivered_at = timezone.now()
        if response is not None:
            self.response_data = response
        await self.asave(update_fields=["status", "delivered_at", "response_data"])

    async def amark_failed(self, error: str) -> None:
        self.status = ReactionExecutionStatus.FAILED
        self.last_error = (error or "")[:2000]
        await self.asave(update_fields=["status", "last_error"])
