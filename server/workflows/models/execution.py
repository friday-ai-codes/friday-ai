"""WorkflowExecution and NodeExecution model definitions."""
import uuid
from typing import Any
from django.db import models
from django.utils import timezone
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
class WorkflowExecution(models.Model):
 """工作流执行实例"""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 workflow = models.ForeignKey(
 "workflows.Workflow",
 on_delete=models.CASCADE,
 related_name="executions",
 )
 # 状态
 status = models.CharField(
 max_length=20,
 choices=ExecutionStatus.choices,
 default=ExecutionStatus.PENDING,
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
 ]
 def __str__(self) -> str:
 return f"{self.workflow.name} - {self.status} ({self.id})"
 @property
 def duration(self) -> float | None:
 """执行时长（秒）"""
 if self.started_at and self.completed_at:
 return (self.completed_at - self.started_at).total_seconds
 elif self.started_at:
 return (timezone.now - self.started_at).total_seconds
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
 self.started_at = timezone.now
 self.timeout_at = timezone.now + timezone.timedelta(seconds=self.workflow.default_timeout)
 self.save(update_fields=["status", "started_at", "timeout_at"])
 def mark_completed(self, output_data: dict | None = None) -> None:
 """标记执行完成"""
 self.status = ExecutionStatus.COMPLETED
 self.completed_at = timezone.now
 if output_data:
 self.output_data = output_data
 self.save(update_fields=["status", "completed_at", "output_data"])
 def mark_failed(self, error: str, node_id: uuid.UUID | None = None) -> None:
 """标记执行失败"""
 self.status = ExecutionStatus.FAILED
 self.completed_at = timezone.now
 self.error_message = error
 self.error_node_id = node_id
 self.save(update_fields=["status", "completed_at", "error_message", "error_node_id"])
 def mark_suspended(self) -> None:
 """标记工作流挂起"""
 self.status = ExecutionStatus.SUSPENDED
 self.save(update_fields=["status"])
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
 return (self.completed_at - self.started_at).total_seconds
 return None
 def mark_started(self, input_data: dict | None = None) -> None:
 """标记开始执行"""
 self.status = NodeExecutionStatus.RUNNING
 self.started_at = timezone.now
 if input_data is not None:
 self.input_data = input_data
 self.save(update_fields=["status", "started_at", "input_data"])
 def mark_completed(self, output_data: dict | None = None) -> None:
 """标记执行完成"""
 self.status = NodeExecutionStatus.COMPLETED
 self.completed_at = timezone.now
 if output_data:
 self.output_data = output_data
 self.save(update_fields=["status", "completed_at", "output_data"])
 # 更新父执行的统计
 self.workflow_execution.completed_nodes += 1
 self.workflow_execution.save(update_fields=["completed_nodes"])
 def mark_failed(self, error: str, traceback: str = "") -> None:
 """标记执行失败"""
 self.status = NodeExecutionStatus.FAILED
 self.completed_at = timezone.now
 self.error_message = error
 self.error_traceback = traceback
 self.save(update_fields=["status", "completed_at", "error_message", "error_traceback"])
 # 更新父执行的统计
 self.workflow_execution.failed_nodes += 1
 self.workflow_execution.save(update_fields=["failed_nodes"])
 def mark_skipped(self, reason: str = "") -> None:
 """标记跳过"""
 self.status = NodeExecutionStatus.SKIPPED
 self.completed_at = timezone.now
 self.error_message = reason
 self.save(update_fields=["status", "completed_at", "error_message"])
 # 更新父执行的统计
 self.workflow_execution.skipped_nodes += 1
 self.workflow_execution.save(update_fields=["skipped_nodes"])
 def mark_waiting_approval(self, approval_request: dict) -> None:
 """标记等待审批"""
 self.status = NodeExecutionStatus.WAITING_APPROVAL
 self.approval_data = approval_request
 self.save(update_fields=["status", "approval_data"])
 def approve(self, approver, comment: str = "") -> None:
 """审批通过"""
 self.approval_data.update(
 {
 "approved": True,
 "approver_id": approver.id,
 "approver_name": approver.username,
 "comment": comment,
 "approved_at": timezone.now.isoformat,
 }
 )
 self.save(update_fields=["approval_data"])
 # 状态变更由引擎处理
 def reject(self, approver, comment: str = "") -> None:
 """审批拒绝"""
 self.approval_data.update(
 {
 "approved": False,
 "approver_id": approver.id,
 "approver_name": approver.username,
 "comment": comment,
 "rejected_at": timezone.now.isoformat,
 }
 )
 self.mark_failed(f"审批被拒绝: {comment}")
 def mark_waiting_event(self, subscription_data: dict) -> None:
 """标记节点等待外部事件"""
 self.status = NodeExecutionStatus.WAITING_EVENT
 self.approval_data = subscription_data # 复用 approval_data 字段存储等待信息
 self.save(update_fields=["status", "approval_data"])
class WorkflowEventSubscription(models.Model):
 """工作流事件订阅记录
 记录挂起的工作流正在等待的外部事件条件。
 当 Webhook 收到匹配事件时，通过此表查找并唤醒对应工作流。
 """
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
 self.matched_at = timezone.now
 self.matched_payload = payload
 self.save(update_fields=["is_active", "matched_at", "matched_payload"])
 def mark_inactive(self) -> None:
 """标记订阅为非活跃（工作流取消/超时时调用）"""
 self.is_active = False
 self.save(update_fields=["is_active"])
