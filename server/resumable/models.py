"""可恢复任务真相源模型。

``ResumableTask`` 统一登记所有需要"断点恢复"的长任务。设计要点：

- DB 是 checkpoint 真相源：进程被 ``docker compose up -d`` 升级、Pod 被 k8s
  调度重建后，运行态信息仍在 DB，``RecoveryScheduler`` 据此自动续跑。
- 租约（lease）区分"任务还活着"与"进程已死"：运行中的任务周期性刷新
  ``lease_expires_at`` / ``heartbeat_at``；启动扫描只领取租约过期的 RUNNING 行，
  天然避开另一个 worker / Pod 刚起的活任务（多副本安全）。
- ``(kind, target_id)`` 唯一约束：同一目标（仓库 / 执行 / 会话）同时只有一个
  活跃任务行，重复触发走 update_or_create 复用同一行。
"""

import uuid

from django.db import models


class ResumableTaskKind(models.TextChoices):
    """可恢复任务类型。"""

    INDEX = "index", "索引构建"
    GRAPH = "graph", "图谱构建"
    WORKFLOW = "workflow", "工作流执行"
    CHAT = "chat", "AI 对话"


class ResumableTaskStatus(models.TextChoices):
    """可恢复任务状态机。"""

    PENDING = "pending", "等待中"
    RUNNING = "running", "运行中"
    COMPLETED = "completed", "已完成"
    FAILED = "failed", "失败"
    CANCELLED = "cancelled", "已取消"


class ResumableTask(models.Model):
    """断点恢复任务登记行（真相源）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=20, choices=ResumableTaskKind.choices)
    # 目标对象 ID（仓库 / WorkflowExecution / Conversation 的 UUID 字符串）。
    target_id = models.CharField(max_length=200)
    status = models.CharField(
        max_length=20,
        choices=ResumableTaskStatus.choices,
        default=ResumableTaskStatus.PENDING,
    )
    # 续跑所需的最小参数（如 branch / trigger / history 关联）。
    payload = models.JSONField(default=dict, blank=True)
    # 当前持有任务的进程实例标识（hostname:pid:uuid）。空表示无人持有。
    lease_owner = models.CharField(max_length=200, blank=True, default="")
    # 租约到期时间；< now 视为持有进程已死，可被启动扫描领取续跑。
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    # 最近一次心跳时间（仅可观测，租约判定以 lease_expires_at 为准）。
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    # 已尝试次数与上限：超过 max_attempts 不再自动续跑，标 FAILED。
    attempt = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)
    # 后台任务名（与 background_runner / cancel_background_task 对齐）。
    name = models.CharField(max_length=200, blank=True, default="")
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "resumable_tasks"
        verbose_name = "可恢复任务"
        verbose_name_plural = "可恢复任务"
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "target_id"],
                name="uq_resumable_kind_target",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "lease_expires_at"],
                name="idx_resumable_status_lease",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.target_id} ({self.status})"
