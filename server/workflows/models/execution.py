"""WorkflowExecution and NodeExecution model definitions."""

import uuid
from typing import TYPE_CHECKING, Any

from django.db import models
from django.db.models import F
from django.utils import timezone

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from workflows.models.coding_task import CodingTask
    from workflows.models.webhook import WebhookLog


class ExecutionStatus(models.TextChoices):
    """执行状态"""

    PENDING = "pending", "待执行"
    RUNNING = "running", "执行中"
    PAUSED = "paused", "已暂停"
    SUSPENDED = "suspended", "挂起中"
    COMPLETED = "completed", "已完成"
    FAILED = "failed", "失败"
    CANCELLED = "cancelled", "已取消"
    TIMEOUT = "timeout", "超时"


class NodeExecutionStatus(models.TextChoices):
    """节点执行状态"""

    PENDING = "pending", "待执行"
    QUEUED = "queued", "排队中"
    RUNNING = "running", "执行中"
    WAITING_APPROVAL = "waiting_approval", "等待审批"
    WAITING_INPUT = "waiting_input", "等待输入"
    WAITING_EVENT = "waiting_event", "等待事件"
    COMPLETED = "completed", "已完成"
    FAILED = "failed", "失败"
    SKIPPED = "skipped", "已跳过"
    CANCELLED = "cancelled", "已取消"
    TIMEOUT = "timeout", "超时"


class SubStepStatus(models.TextChoices):
    """子步骤执行状态"""

    PENDING = "pending", "待执行"
    RUNNING = "running", "执行中"
    COMPLETED = "completed", "已完成"
    FAILED = "failed", "失败"


class WorkflowErrorCode(models.TextChoices):
    """工作流错误分类码"""

    TIMEOUT = "timeout", "执行超时"
    PERMISSION = "permission", "权限不足"
    RESOURCE = "resource", "资源不足"
    API = "api", "外部 API 错误"
    RUNTIME = "runtime", "运行时错误"
    UNKNOWN = "unknown", "未知错误"


class WorkflowExecution(models.Model):
    """工作流执行实例"""

    # 管理器类型声明
    objects: "models.Manager[WorkflowExecution]"

    # 反向关系类型声明
    node_executions: "QuerySet[NodeExecution]"
    event_subscriptions: "QuerySet[WorkflowEventSubscription]"
    webhook_logs: "QuerySet[WebhookLog]"
    coding_tasks: "QuerySet[CodingTask]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    workflow = models.ForeignKey(
        "workflows.Workflow",
        on_delete=models.CASCADE,
        related_name="executions",
    )

    space = models.ForeignKey(
        "projects.Space",
        on_delete=models.CASCADE,
        related_name="workflow_executions",
        verbose_name="所属空间",
    )

    # 状态
    status = models.CharField(
        max_length=20,
        choices=ExecutionStatus.choices,
        default=ExecutionStatus.PENDING,
    )

    # Provider 类型（v8.1 成本归因）
    provider_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Provider 类型",
        help_text="执行时使用的主 Provider，用于成本归因",
    )

    # 触发信息
    trigger_type = models.CharField(max_length=20, verbose_name="触发类型")
    triggered_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="触发者",
    )
    trigger_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="触发数据",
        help_text="如 webhook payload、定时任务信息等",
    )

    # 手动触发标识
    is_manual_trigger = models.BooleanField(
        default=False,
        verbose_name="是否手动触发",
        help_text="手动触发时模拟事件数据",
    )

    # 调试模式
    is_debug = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="调试执行",
        help_text="调试执行不计入正式记录，不触发通知，不受并发限制",
    )
    feishu_message_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name="飞书消息 ID",
        help_text="最近一次工作流通知的飞书消息 ID",
    )
    debug_paused_at_node = models.UUIDField(
        null=True,
        blank=True,
        verbose_name="调试暂停节点",
        help_text="记录当前暂停在哪个节点 ID，用于前端展示调试状态",
    )

    # 关联飞书触发日志
    trigger_log = models.ForeignKey(
        "feishu.TriggerLog",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflow_executions",
        verbose_name="触发日志",
        help_text="关联的飞书 Webhook 触发日志",
    )

    # 从失败节点继续：指向原失败执行实例
    resumed_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resumed_executions",
        verbose_name="继续自",
        help_text="从失败节点继续时，指向原失败执行实例",
    )

    # 工作流定义快照（执行时的 DAG 布局数据）
    workflow_definition = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="工作流定义快照",
        help_text="执行创建时保存的精简 DAG 数据（节点位置、连接关系、类型和名称），确保历史执行始终反映当时的 DAG",
    )

    # 全局参数（节点可读写，前端可见）
    global_params = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="全局参数",
        help_text="节点间共享的全局参数，可通过 {{global.key}} 引用",
    )

    # 执行上下文（全局变量，节点间共享）
    context = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="执行上下文",
    )

    # 输入参数（执行开始时传入）
    input_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="输入数据",
    )

    # 最终输出
    output_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="输出数据",
    )

    # 错误信息
    error_message = models.TextField(blank=True, default="")
    error_node_id = models.UUIDField(null=True, blank=True)

    # 统计信息
    total_nodes = models.PositiveIntegerField(default=0)
    completed_nodes = models.PositiveIntegerField(default=0)
    failed_nodes = models.PositiveIntegerField(default=0)
    skipped_nodes = models.PositiveIntegerField(default=0)

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    timeout_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "workflow_executions"
        verbose_name = "工作流执行"
        verbose_name_plural = "工作流执行"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workflow", "status"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["space", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.workflow.name} - {self.status} ({self.id})"

    @property
    def duration(self) -> float | None:
        """执行时长（秒）"""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        elif self.started_at:
            return (timezone.now() - self.started_at).total_seconds()
        return None

    @property
    def progress(self) -> float:
        """执行进度 (0-100)"""
        if self.total_nodes == 0:
            return 0
        return (self.completed_nodes + self.skipped_nodes) / self.total_nodes * 100

    def mark_started(self) -> None:
        """标记开始执行"""
        self.status = ExecutionStatus.RUNNING
        self.started_at = timezone.now()
        self.timeout_at = timezone.now() + timezone.timedelta(seconds=self.workflow.default_timeout)
        self.save(update_fields=["status", "started_at", "timeout_at"])

    async def amark_started(self) -> None:
        """标记开始执行（async 版本）"""
        self.status = ExecutionStatus.RUNNING
        self.started_at = timezone.now()
        default_timeout = await type(self).objects.filter(
            pk=self.pk
        ).values_list("workflow__default_timeout", flat=True).afirst()
        self.timeout_at = timezone.now() + timezone.timedelta(seconds=default_timeout or 3600)
        await self.asave(update_fields=["status", "started_at", "timeout_at"])

    def mark_completed(self, output_data: dict | None = None) -> None:
        """标记执行完成"""
        self.status = ExecutionStatus.COMPLETED
        self.completed_at = timezone.now()
        if output_data:
            self.output_data = output_data
        self.save(update_fields=["status", "completed_at", "output_data"])

    async def amark_completed(self, output_data: dict | None = None) -> None:
        """标记执行完成（async 版本）"""
        self.status = ExecutionStatus.COMPLETED
        self.completed_at = timezone.now()
        if output_data:
            self.output_data = output_data
        await self.asave(update_fields=["status", "completed_at", "output_data"])

    def mark_failed(self, error: str, node_id: uuid.UUID | None = None) -> None:
        """标记执行失败"""
        self.status = ExecutionStatus.FAILED
        self.completed_at = timezone.now()
        self.error_message = error
        self.error_node_id = node_id
        self.save(update_fields=["status", "completed_at", "error_message", "error_node_id"])

    async def amark_failed(self, error: str, node_id: uuid.UUID | None = None) -> None:
        """标记执行失败（async 版本）"""
        self.status = ExecutionStatus.FAILED
        self.completed_at = timezone.now()
        self.error_message = error
        self.error_node_id = node_id
        await self.asave(update_fields=["status", "completed_at", "error_message", "error_node_id"])

    def mark_suspended(self) -> None:
        """标记工作流挂起"""
        self.status = ExecutionStatus.SUSPENDED
        self.save(update_fields=["status"])

    async def amark_suspended(self) -> None:
        """标记工作流挂起（async 版本）"""
        self.status = ExecutionStatus.SUSPENDED
        await self.asave(update_fields=["status"])

    def get_context_value(self, key: str, default: Any = None) -> Any:
        """获取上下文变量"""
        return self.context.get(key, default)

    def set_context_value(self, key: str, value: Any) -> None:
        """设置上下文变量"""
        self.context[key] = value
        self.save(update_fields=["context"])

    def update_context(self, data: dict) -> None:
        """批量更新上下文"""
        self.context.update(data)
        self.save(update_fields=["context"])

    # 全局参数管理方法
    def get_global_param(self, key: str, default: Any = None) -> Any:
        """获取全局参数

        Args:
            key: 参数键
            default: 默认值

        Returns:
            参数值
        """
        return self.global_params.get(key, default)

    def set_global_param(self, key: str, value: Any) -> None:
        """设置全局参数

        Args:
            key: 参数键
            value: 参数值
        """
        self.global_params[key] = value
        self.save(update_fields=["global_params"])

    async def aset_global_param(self, key: str, value: Any) -> None:
        """设置全局参数（async 版本）

        Args:
            key: 参数键
            value: 参数值
        """
        self.global_params[key] = value
        await self.asave(update_fields=["global_params"])

    def update_global_params(self, data: dict) -> None:
        """批量更新全局参数

        Args:
            data: 要更新的参数字典
        """
        self.global_params.update(data)
        self.save(update_fields=["global_params"])

    def get_context_snapshot(self) -> dict:
        """获取上下文快照（用于前端展示）

        Returns:
            包含执行状态、全局参数、节点输出的完整上下文
        """
        return {
            "execution_id": str(self.id),
            "status": self.status,
            "progress": self.progress,
            "is_manual_trigger": self.is_manual_trigger,
            "trigger_data": self.trigger_data,
            "input_data": self.input_data,
            "global_params": self.global_params,
            "global_variables": self.context.get("global_variables", {}),
            "node_outputs": self.context.get("node_outputs", {}),
        }

    # ===== 全局变量管理（带元数据） =====

    def set_global_variable(self, key: str, variable: dict) -> None:
        """设置全局变量

        Args:
            key: 变量标识符
            variable: 变量数据（包含 key, name, value, desc, required, source_node）
        """
        if "global_variables" not in self.context:
            self.context["global_variables"] = {}
        self.context["global_variables"][key] = variable
        self.save(update_fields=["context"])

    async def aset_global_variable(self, key: str, variable: dict) -> None:
        """设置全局变量（async 版本）

        Args:
            key: 变量标识符
            variable: 变量数据（包含 key, name, value, desc, required, source_node）
        """
        if "global_variables" not in self.context:
            self.context["global_variables"] = {}
        self.context["global_variables"][key] = variable
        await self.asave(update_fields=["context"])

    def get_global_variable(self, key: str) -> dict | None:
        """获取全局变量

        Args:
            key: 变量标识符

        Returns:
            变量数据或 None
        """
        return self.context.get("global_variables", {}).get(key)

    def get_all_global_variables(self) -> dict:
        """获取所有全局变量

        Returns:
            {key: variable} 字典
        """
        return self.context.get("global_variables", {})


class NodeExecution(models.Model):
    """节点执行记录"""

    # 管理器类型声明
    objects: "models.Manager[NodeExecution]"

    # 反向关系类型声明
    event_subscriptions: "QuerySet[WorkflowEventSubscription]"
    sub_steps: "QuerySet[NodeSubStep]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    workflow_execution = models.ForeignKey(
        WorkflowExecution,
        on_delete=models.CASCADE,
        related_name="node_executions",
    )
    node = models.ForeignKey(
        "workflows.WorkflowNode",
        on_delete=models.CASCADE,
        related_name="executions",
    )

    # 状态
    status = models.CharField(
        max_length=20,
        choices=NodeExecutionStatus.choices,
        default=NodeExecutionStatus.PENDING,
    )

    # Provider 类型（v8.1 成本归因）
    provider_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Provider 类型",
        help_text="节点实际使用的 Provider，执行时写入",
    )

    # 输入/输出
    input_data = models.JSONField(default=dict, blank=True)
    output_data = models.JSONField(default=dict, blank=True)

    # 错误信息
    error_message = models.TextField(blank=True, default="")
    error_traceback = models.TextField(blank=True, default="")

    # 重试信息
    attempt = models.PositiveIntegerField(default=1, verbose_name="当前尝试次数")

    # 审批信息（用于审批节点）
    approval_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="审批数据",
        help_text="存储审批请求、审批人、审批意见等",
    )

    # 容器执行信息（用于 Docker 节点）
    container_id = models.CharField(max_length=100, blank=True, default="")
    container_logs = models.TextField(blank=True, default="")

    # 结构化执行日志
    logs = models.JSONField(
        default=list,
        blank=True,
        verbose_name="执行日志",
        help_text="结构化日志数组，每个元素为 {timestamp, level, message, context}",
    )

    # 错误分类码
    error_code = models.CharField(
        max_length=20,
        choices=WorkflowErrorCode.choices,
        null=True,
        blank=True,
        verbose_name="错误码",
        help_text="节点失败时的错误分类",
    )

    # 子步骤进度缓存（由 emit_sub_step() 同步更新）
    sub_step_completed_count = models.IntegerField(
        default=0, verbose_name="已完成子步骤数"
    )
    sub_step_total_count = models.IntegerField(
        default=0, verbose_name="子步骤总数"
    )

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "node_executions"
        verbose_name = "节点执行"
        verbose_name_plural = "节点执行"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["workflow_execution", "status"]),
            models.Index(fields=["node", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.node.name} - {self.status}"

    @property
    def duration(self) -> float | None:
        """执行时长（秒）"""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def _append_log(
        self,
        level: str,
        message: str,
        context: dict | None = None,
    ) -> None:
        """追加单条日志到 logs 数组（同步版本）。"""
        entry: dict[str, Any] = {
            "timestamp": timezone.now().isoformat(),
            "level": level,
            "message": message,
        }
        if context:
            entry["context"] = context
        current_logs: list[dict] = list(self.logs or [])
        current_logs.append(entry)
        # 限制最大条数 100，防止 JSONField 膨胀
        if len(current_logs) > 100:
            current_logs = current_logs[-100:]
        self.logs = current_logs
        self.save(update_fields=["logs"])

    async def aappend_log(
        self,
        level: str,
        message: str,
        context: dict | None = None,
    ) -> None:
        """追加单条日志到 logs 数组（异步版本）。"""
        entry: dict[str, Any] = {
            "timestamp": timezone.now().isoformat(),
            "level": level,
            "message": message,
        }
        if context:
            entry["context"] = context
        current_logs: list[dict] = list(self.logs or [])
        current_logs.append(entry)
        if len(current_logs) > 100:
            current_logs = current_logs[-100:]
        self.logs = current_logs
        await self.asave(update_fields=["logs"])

    def mark_started(self, input_data: dict | None = None) -> None:
        """标记开始执行"""
        self.status = NodeExecutionStatus.RUNNING
        self.started_at = timezone.now()
        if input_data is not None:
            self.input_data = input_data
        self.save(update_fields=["status", "started_at", "input_data"])

    async def amark_started(self, input_data: dict | None = None) -> None:
        """标记开始执行（async 版本）"""
        self.status = NodeExecutionStatus.RUNNING
        self.started_at = timezone.now()
        if input_data is not None:
            self.input_data = input_data
        await self.asave(update_fields=["status", "started_at", "input_data"])

    def mark_completed(self, output_data: dict | None = None) -> None:
        """标记执行完成"""
        self.status = NodeExecutionStatus.COMPLETED
        self.completed_at = timezone.now()
        if output_data:
            self.output_data = output_data
        self.save(update_fields=["status", "completed_at", "output_data"])

        # 更新父执行的统计
        self.workflow_execution.completed_nodes += 1
        self.workflow_execution.save(update_fields=["completed_nodes"])

    async def amark_completed(self, output_data: dict | None = None) -> None:
        """标记执行完成（async 版本）"""
        self.status = NodeExecutionStatus.COMPLETED
        self.completed_at = timezone.now()
        if output_data:
            self.output_data = output_data
        await self.asave(update_fields=["status", "completed_at", "output_data"])
        # 级联更新父执行统计（避免加载 FK，直接原子更新）
        await WorkflowExecution.objects.filter(pk=self.workflow_execution_id).aupdate(
            completed_nodes=F("completed_nodes") + 1
        )

    def mark_failed(self, error: str, traceback: str = "", error_code: str | None = None) -> None:
        """标记执行失败"""
        self.status = NodeExecutionStatus.FAILED
        self.completed_at = timezone.now()
        self.error_message = error
        self.error_traceback = traceback
        if error_code:
            self.error_code = error_code
        self.save(update_fields=["status", "completed_at", "error_message", "error_traceback", "error_code"])

        # 更新父执行的统计
        self.workflow_execution.failed_nodes += 1
        self.workflow_execution.save(update_fields=["failed_nodes"])

    async def amark_failed(self, error: str, traceback: str = "", error_code: str | None = None) -> None:
        """标记执行失败（async 版本）"""
        self.status = NodeExecutionStatus.FAILED
        self.completed_at = timezone.now()
        self.error_message = error
        self.error_traceback = traceback
        if error_code:
            self.error_code = error_code
        await self.asave(update_fields=["status", "completed_at", "error_message", "error_traceback", "error_code"])
        # 级联更新父执行统计（避免加载 FK，直接原子更新）
        await WorkflowExecution.objects.filter(pk=self.workflow_execution_id).aupdate(
            failed_nodes=F("failed_nodes") + 1
        )

    def mark_skipped(self, reason: str = "") -> None:
        """标记跳过"""
        self.status = NodeExecutionStatus.SKIPPED
        self.completed_at = timezone.now()
        self.error_message = reason
        self.save(update_fields=["status", "completed_at", "error_message"])

        # 更新父执行的统计
        self.workflow_execution.skipped_nodes += 1
        self.workflow_execution.save(update_fields=["skipped_nodes"])

    async def amark_skipped(self, reason: str = "") -> None:
        """标记跳过（async 版本）"""
        self.status = NodeExecutionStatus.SKIPPED
        self.completed_at = timezone.now()
        self.error_message = reason
        await self.asave(update_fields=["status", "completed_at", "error_message"])
        # 级联更新父执行统计（避免加载 FK，直接原子更新）
        await WorkflowExecution.objects.filter(pk=self.workflow_execution_id).aupdate(
            skipped_nodes=F("skipped_nodes") + 1
        )

    def mark_waiting_approval(self, approval_request: dict) -> None:
        """标记等待审批"""
        self.status = NodeExecutionStatus.WAITING_APPROVAL
        self.approval_data = approval_request
        self.save(update_fields=["status", "approval_data"])

    async def amark_waiting_approval(self, approval_request: dict) -> None:
        """标记等待审批（async 版本）"""
        self.status = NodeExecutionStatus.WAITING_APPROVAL
        self.approval_data = approval_request
        await self.asave(update_fields=["status", "approval_data"])

    def approve(self, approver, comment: str = "") -> None:
        """审批通过"""
        self.approval_data.update(
            {
                "approved": True,
                "approver_id": approver.id,
                "approver_name": approver.username,
                "comment": comment,
                "approved_at": timezone.now().isoformat(),
            }
        )
        self.save(update_fields=["approval_data"])
        # 状态变更由引擎处理

    async def aapprove(self, approver, comment: str = "") -> None:
        """审批通过（async 版本）"""
        self.approval_data.update(
            {
                "approved": True,
                "approver_id": approver.id,
                "approver_name": approver.username,
                "comment": comment,
                "approved_at": timezone.now().isoformat(),
            }
        )
        await self.asave(update_fields=["approval_data"])

    def reject(self, approver, comment: str = "") -> None:
        """审批拒绝"""
        self.approval_data.update(
            {
                "approved": False,
                "approver_id": approver.id,
                "approver_name": approver.username,
                "comment": comment,
                "rejected_at": timezone.now().isoformat(),
            }
        )
        self.mark_failed(f"审批被拒绝: {comment}")

    def mark_waiting_event(self, subscription_data: dict) -> None:
        """标记节点等待外部事件"""
        self.status = NodeExecutionStatus.WAITING_EVENT
        self.output_data = subscription_data
        self.approval_data = subscription_data  # 复用 approval_data 字段存储等待信息
        self.save(update_fields=["status", "output_data", "approval_data"])

    async def amark_waiting_event(self, subscription_data: dict) -> None:
        """标记节点等待外部事件（async 版本）"""
        self.status = NodeExecutionStatus.WAITING_EVENT
        self.output_data = subscription_data
        self.approval_data = subscription_data
        await self.asave(update_fields=["status", "output_data", "approval_data"])


class NodeSubStep(models.Model):
    """节点执行子步骤。

    记录 AI 节点内部的执行步骤（如 tool_call、thinking、code_generation），
    由 AI 节点在执行过程中 emit 创建，前端展示时按 step_order 排序。
    """

    # 管理器类型声明
    objects: "models.Manager[NodeSubStep]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    node_execution = models.ForeignKey(
        NodeExecution,
        on_delete=models.CASCADE,
        related_name="sub_steps",
        verbose_name="节点执行",
    )

    # 步骤描述
    name = models.CharField(max_length=200, verbose_name="步骤名称")
    step_type = models.CharField(
        max_length=50,
        verbose_name="步骤类型",
        help_text="子步骤类型标识，如 tool_call、thinking、code_generation",
    )
    step_order = models.IntegerField(verbose_name="步骤顺序")

    # 状态
    status = models.CharField(
        max_length=20,
        choices=SubStepStatus.choices,
        default=SubStepStatus.PENDING,
        verbose_name="状态",
    )

    # 输入/输出
    input_data = models.JSONField(default=dict, blank=True, verbose_name="输入数据")
    output_data = models.JSONField(default=dict, blank=True, verbose_name="输出数据")

    # 时间戳
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="开始时间")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")

    class Meta:
        db_table = "node_sub_steps"
        verbose_name = "节点子步骤"
        verbose_name_plural = "节点子步骤"
        ordering = ["step_order"]
        indexes = [
            models.Index(fields=["node_execution", "step_order"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.step_type}) - {self.status}"

    @property
    def duration(self) -> float | None:
        """执行时长（秒）"""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def mark_started(self) -> None:
        """标记开始执行"""
        self.status = SubStepStatus.RUNNING
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at"])

    async def amark_started(self) -> None:
        """标记开始执行（async 版本）"""
        self.status = SubStepStatus.RUNNING
        self.started_at = timezone.now()
        await self.asave(update_fields=["status", "started_at"])

    def mark_completed(self, output_data: dict | None = None) -> None:
        """标记执行完成"""
        self.status = SubStepStatus.COMPLETED
        self.completed_at = timezone.now()
        if output_data:
            self.output_data = output_data
        self.save(update_fields=["status", "completed_at", "output_data"])

    async def amark_completed(self, output_data: dict | None = None) -> None:
        """标记执行完成（async 版本）"""
        self.status = SubStepStatus.COMPLETED
        self.completed_at = timezone.now()
        if output_data:
            self.output_data = output_data
        await self.asave(update_fields=["status", "completed_at", "output_data"])

    def mark_failed(self, error: str = "") -> None:
        """标记执行失败"""
        self.status = SubStepStatus.FAILED
        self.completed_at = timezone.now()
        if error:
            self.output_data = {**self.output_data, "error": error}
        self.save(update_fields=["status", "completed_at", "output_data"])

    async def amark_failed(self, error: str = "") -> None:
        """标记执行失败（async 版本）"""
        self.status = SubStepStatus.FAILED
        self.completed_at = timezone.now()
        if error:
            self.output_data = {**self.output_data, "error": error}
        await self.asave(update_fields=["status", "completed_at", "output_data"])


class WorkflowEventSubscription(models.Model):
    """工作流事件订阅记录

    记录挂起的工作流正在等待的外部事件条件。
    当 Webhook 收到匹配事件时，通过此表查找并唤醒对应工作流。
    """

    # 管理器类型声明
    objects: "models.Manager[WorkflowEventSubscription]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    workflow_execution = models.ForeignKey(
        WorkflowExecution,
        on_delete=models.CASCADE,
        related_name="event_subscriptions",
        verbose_name="工作流执行",
    )
    node_execution = models.ForeignKey(
        NodeExecution,
        on_delete=models.CASCADE,
        related_name="event_subscriptions",
        verbose_name="节点执行",
    )

    # 等待的事件信息
    event_type = models.CharField(
        max_length=50,
        verbose_name="事件类型",
        help_text="如 WorkitemUpdateEvent, WorkitemStatusEvent",
    )
    project_key = models.CharField(
        max_length=100,
        verbose_name="项目标识",
    )
    work_item_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="工作项 ID",
        help_text="为空表示匹配该项目的所有工作项",
    )
    work_item_type = models.CharField(
        max_length=50,
        default="story",
        verbose_name="工作项类型",
    )

    # 条件表达式（JSON 格式，支持 AND/OR 组合）
    condition_expression = models.JSONField(
        default=dict,
        verbose_name="条件表达式",
        help_text="JSON 格式的条件表达式，支持 logic:and/or + conditions 数组",
    )

    # 超时配置
    timeout_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="超时时间",
    )
    timeout_action = models.CharField(
        max_length=20,
        choices=[
            ("fail", "失败终止"),
            ("skip", "跳过继续"),
            ("retry", "重试"),
        ],
        default="fail",
        verbose_name="超时动作",
    )

    # 状态追踪
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否活跃",
        help_text="工作流完成/取消后设为 False",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    matched_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="匹配时间",
    )
    matched_payload = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="匹配的事件数据",
    )

    class Meta:
        db_table = "workflow_event_subscriptions"
        verbose_name = "工作流事件订阅"
        verbose_name_plural = "工作流事件订阅"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_active", "project_key", "work_item_id"]),
            models.Index(fields=["is_active", "event_type"]),
            models.Index(fields=["timeout_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.workflow_execution_id} waiting for {self.event_type}"

    def mark_matched(self, payload: dict) -> None:
        """标记订阅已匹配"""
        self.is_active = False
        self.matched_at = timezone.now()
        self.matched_payload = payload
        self.save(update_fields=["is_active", "matched_at", "matched_payload"])

    async def amark_matched(self, payload: dict) -> None:
        """标记订阅已匹配（async 版本）"""
        self.is_active = False
        self.matched_at = timezone.now()
        self.matched_payload = payload
        await self.asave(update_fields=["is_active", "matched_at", "matched_payload"])

    def mark_inactive(self) -> None:
        """标记订阅为非活跃（工作流取消/超时时调用）"""
        self.is_active = False
        self.save(update_fields=["is_active"])

    async def amark_inactive(self) -> None:
        """标记订阅为非活跃（async 版本）"""
        self.is_active = False
        await self.asave(update_fields=["is_active"])


class AlertRule(models.Model):
    """告警规则"""

    objects: "models.Manager[AlertRule]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        "workflows.Workflow",
        on_delete=models.CASCADE,
        related_name="alert_rules",
        null=True, blank=True,
        verbose_name="关联工作流",
        help_text="null 表示全局规则（所有工作流）",
    )
    space = models.ForeignKey(
        "projects.Space",
        on_delete=models.CASCADE,
        related_name="alert_rules",
        verbose_name="所属空间",
    )
    name = models.CharField(max_length=200, verbose_name="规则名称")
    enabled = models.BooleanField(default=True, verbose_name="启用")

    CONDITION_TYPES = [
        ("execution_failed", "执行失败"),
        ("execution_timeout", "执行超时"),
        ("cost_threshold", "成本超阈值"),
        ("node_error_code", "节点错误码"),
    ]
    condition_type = models.CharField(
        max_length=30, choices=CONDITION_TYPES, verbose_name="条件类型"
    )
    condition_config = models.JSONField(
        default=dict, blank=True, verbose_name="条件配置"
    )

    ACTION_TYPES = [
        ("feishu_notification", "飞书通知"),
        ("webhook", "Webhook"),
    ]
    action_type = models.CharField(
        max_length=30, choices=ACTION_TYPES, verbose_name="动作类型"
    )
    action_config = models.JSONField(
        default=dict, blank=True, verbose_name="动作配置"
    )

    cooldown_seconds = models.PositiveIntegerField(
        default=0, verbose_name="冷却时间(秒)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workflow_alert_rules"
        indexes = [
            models.Index(fields=["space", "enabled"]),
            models.Index(fields=["workflow", "enabled"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.condition_type})"


class AlertRuleExecution(models.Model):
    """告警规则触发记录"""

    objects: "models.Manager[AlertRuleExecution]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    alert_rule = models.ForeignKey(
        AlertRule,
        on_delete=models.CASCADE,
        related_name="executions",
        verbose_name="告警规则",
    )
    workflow_execution = models.ForeignKey(
        WorkflowExecution,
        on_delete=models.CASCADE,
        related_name="alert_rule_executions",
        verbose_name="工作流执行",
    )
    triggered_at = models.DateTimeField(auto_now_add=True, verbose_name="触发时间")
    status = models.CharField(
        max_length=20,
        choices=[
            ("triggered", "已触发"),
            ("delivered", "已送达"),
            ("failed", "发送失败"),
        ],
        default="triggered",
        verbose_name="状态",
    )
    response_data = models.JSONField(
        default=dict, blank=True, verbose_name="响应数据"
    )
    error_message = models.TextField(blank=True, default="", verbose_name="错误消息")
    triggered_event = models.CharField(
        max_length=50, blank=True, default="", verbose_name="触发事件"
    )

    class Meta:
        db_table = "workflow_alert_rule_executions"
        unique_together = [["alert_rule", "workflow_execution"]]
        ordering = ["-triggered_at"]
        verbose_name = "告警规则执行记录"
        verbose_name_plural = "告警规则执行记录"

    def __str__(self) -> str:
        return f"{self.alert_rule.name} - {self.status}"
