"""HumanTask：统一人类待办模型（Chassis v2 · P8 Human Task Center）。

把散落在各处的"点状人类待办"——澄清问答（``Clarification``）、工作流审批
（``NodeExecution.status=waiting_approval``）、失败反应重试（``ReactionExecution.failed``）、
以及风险确认 / 接管等——收敛为**一种**一等待办对象，使"我需要处理什么"有单一事实形态：

- ``task_type``：``clarification | approval | risk_ack | takeover | reaction_retry``。
- ``scope`` + ``subject_id``：待办挂靠的主体（``workflow_execution | process_session |
  artifact`` 的某行 id 软引用，跨 app 不建硬 FK，避免对 workflows 形成耦合）。
- ``status``：``open | done | skipped | expired``（超时 / 跳过 / 接管 / 转派在
  ``HumanTaskService`` 这一层建模）。
- ``assignee_user_id`` / ``assignee_role``：可空，支撑"指派到人 / 指派到角色 / 未指派"。
- ``artifact_ref``：可空 FK → ``ArtifactVersion``（审批 / 风险确认常绑定到某产物版本）。
- ``dedup_key``：物化幂等键（如 ``clarification:<id>``）。同一来源重复物化命中已有行即短路，
  避免投影/物化双写出重复待办（partial unique，仅非空时唯一）。

设计要点（守 INV-6 精神）：
- **写入单一入口**：``HumanTask`` 落库 / 状态变更只经 ``HumanTaskService``，模型层**不写**任何
  create / save / 状态变更业务方法。
- **不旁路既有事实源**：澄清仍是 ``Clarification`` 的事实、审批仍是 ``NodeExecution`` 的事实、
  失败反应仍是 ``ReactionExecution`` 的事实；HumanTask 对它们是**投影 / 物化**，
  查询"我的待办"时按需聚合（见 ``HumanTaskService.list_inbox``），不复制它们的权威状态。
"""

import uuid

from django.db import models


class HumanTaskType(models.TextChoices):
    """人类待办类型。"""

    CLARIFICATION = "clarification", "待答澄清"
    APPROVAL = "approval", "待审批"
    RISK_ACK = "risk_ack", "风险确认"
    TAKEOVER = "takeover", "可接管"
    REACTION_RETRY = "reaction_retry", "失败反应重试"


class HumanTaskScope(models.TextChoices):
    """待办挂靠主体的作用域。"""

    WORKFLOW_EXECUTION = "workflow_execution", "工作流执行"
    PROCESS_SESSION = "process_session", "收敛会话"
    ARTIFACT = "artifact", "交付物"


class HumanTaskStatus(models.TextChoices):
    """人类待办状态。"""

    OPEN = "open", "待处理"
    DONE = "done", "已处理"
    SKIPPED = "skipped", "已跳过"
    EXPIRED = "expired", "已超时"


class HumanTask(models.Model):
    """统一人类待办（澄清 / 审批 / 风险确认 / 接管 / 失败反应重试）。"""

    objects: "models.Manager[HumanTask]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 待办类型（与发出它的信号 / 来源解耦，统一收件箱按此分组）
    task_type = models.CharField(
        max_length=20,
        choices=HumanTaskType.choices,
        verbose_name="待办类型",
    )

    # 挂靠主体作用域 + 主体 id（跨 app 软引用，不建硬 FK）
    scope = models.CharField(
        max_length=24,
        choices=HumanTaskScope.choices,
        verbose_name="作用域",
    )
    subject_id = models.CharField(max_length=64, verbose_name="主体 id")

    # 指派：到人 / 到角色 / 未指派（均可空）
    assignee_user_id = models.CharField(
        max_length=64, null=True, blank=True, verbose_name="指派用户 id"
    )
    assignee_role = models.CharField(
        max_length=64, null=True, blank=True, verbose_name="指派角色"
    )

    status = models.CharField(
        max_length=12,
        choices=HumanTaskStatus.choices,
        default=HumanTaskStatus.OPEN,
        verbose_name="状态",
    )

    # 处理结果（答案 / 审批决议 / 接管说明等结构化留痕）
    resolution = models.JSONField(default=dict, blank=True, verbose_name="处理结果")

    # 产生该待办的信号名（见 workflows.reactions.signal.SIGNAL_NAMES，自由字符串）
    source_signal = models.CharField(
        max_length=64, blank=True, default="", verbose_name="来源信号"
    )

    # 绑定的产物版本（审批 / 风险确认常绑定到某 ArtifactVersion）
    artifact_ref = models.ForeignKey(
        "delivery.ArtifactVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="human_tasks",
        verbose_name="关联产物版本",
    )

    # 物化幂等键（如 clarification:<id>）；partial unique 仅非空时唯一。
    dedup_key = models.CharField(
        max_length=128, blank=True, default="", verbose_name="物化幂等键"
    )

    due_at = models.DateTimeField(null=True, blank=True, verbose_name="截止时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name="处理时间")

    class Meta:
        db_table = "delivery_human_task"
        verbose_name = "人类待办"
        verbose_name_plural = "人类待办"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "task_type"]),
            models.Index(fields=["assignee_user_id", "status"]),
            models.Index(fields=["scope", "subject_id"]),
        ]
        constraints = [
            # dedup_key 非空时唯一（物化幂等）；空串不参与唯一约束（原生待办无需 dedup）。
            models.UniqueConstraint(
                fields=["dedup_key"],
                condition=models.Q(dedup_key__gt=""),
                name="uniq_human_task_dedup_key",
            ),
        ]

    def __str__(self) -> str:
        return f"HumanTask({self.task_type}/{self.status}:{self.id})"
