"""WorkflowNode and WorkflowEdge model definitions."""
import uuid
from typing import TYPE_CHECKING
from django.core.exceptions import ValidationError
from django.db import models
from common.short_id import generate_short_id
if TYPE_CHECKING:
 from django.db.models import QuerySet
 from workflows.models.execution import NodeExecution
 from workflows.models.workflow import Workflow
class WorkflowNode(models.Model):
 """工作流节点"""
 # 反向关系类型声明
 executions: "QuerySet[NodeExecution]"
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 # 短 ID，用于前端显示和模板变量引用 (如 {{nodes.abc.xxx}})
 short_id = models.CharField(
 max_length=12,
 default=generate_short_id,
 verbose_name="短 ID",
 help_text="用于模板变量引用，如 {{nodes.abc.field}}",
 )
 workflow = models.ForeignKey(
 "workflows.Workflow",
 on_delete=models.CASCADE,
 related_name="nodes",
 )
 # 节点类型（对应 NodeRegistry 中注册的类型）
 node_type = models.CharField(
 max_length=100,
 verbose_name="节点类型",
 help_text="如: manual_trigger, create_branch, ai_coding",
 )
 # 显示信息
 name = models.CharField(max_length=200, verbose_name="节点名称")
 description = models.TextField(blank=True, default="", verbose_name="描述")
 # 画布位置（Vue Flow 使用）
 position_x = models.FloatField(default=0, verbose_name="X 坐标")
 position_y = models.FloatField(default=0, verbose_name="Y 坐标")
 # 节点配置（JSON Schema 验证）
 config = models.JSONField(
 default=dict,
 blank=True,
 verbose_name="节点配置",
 help_text="节点特定的配置参数",
 )
 # 执行配置
 timeout = models.PositiveIntegerField(
 null=True,
 blank=True,
 verbose_name="超时(秒)",
 help_text="覆盖工作流默认超时",
 )
 retry_count = models.PositiveIntegerField(
 default=0,
 verbose_name="重试次数",
 )
 retry_delay = models.PositiveIntegerField(
 default=60,
 verbose_name="重试间隔(秒)",
 )
 # 条件执行
 run_condition = models.JSONField(
 null=True,
 blank=True,
 verbose_name="执行条件",
 help_text="JSON 格式的条件表达式，为 null 时始终执行",
 )
 # 元数据
 metadata = models.JSONField(
 default=dict,
 blank=True,
 verbose_name="元数据",
 help_text="存储 UI 状态、注释等",
 )
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "workflow_nodes"
 verbose_name = "工作流节点"
 verbose_name_plural = "工作流节点"
 ordering = ["created_at"]
 indexes = [
 models.Index(fields=["workflow", "short_id"]),
 ]
 def __str__(self) -> str:
 return f"{self.name} ({self.node_type})"
 def clean(self) -> None:
 """验证节点配置"""
 from workflows.nodes.registry import NodeRegistry
 node_class = NodeRegistry.get(self.node_type)
 if not node_class:
 raise ValidationError(f"未知的节点类型: {self.node_type}")
 # 验证配置 schema
 errors = node_class.validate_config(self.config)
 if errors:
 raise ValidationError({"config": errors})
 def get_effective_timeout(self) -> int:
 """获取有效超时时间"""
 return self.timeout or self.workflow.default_timeout
 def to_json(self) -> dict:
 """导出为 JSON"""
 return {
 "id": str(self.id),
 "short_id": self.short_id,
 "node_type": self.node_type,
 "name": self.name,
 "description": self.description,
 "position_x": self.position_x,
 "position_y": self.position_y,
 "config": self.config,
 "timeout": self.timeout,
 "retry_count": self.retry_count,
 "retry_delay": self.retry_delay,
 "run_condition": self.run_condition,
 }
 def clone(self, new_workflow: "Workflow") -> "WorkflowNode":
 """克隆节点到新工作流"""
 return WorkflowNode.objects.create(
 workflow=new_workflow,
 node_type=self.node_type,
 name=self.name,
 description=self.description,
 position_x=self.position_x,
 position_y=self.position_y,
 config=self.config.copy,
 timeout=self.timeout,
 retry_count=self.retry_count,
 retry_delay=self.retry_delay,
 run_condition=self.run_condition,
 metadata=self.metadata.copy,
 )
class WorkflowEdge(models.Model):
 """工作流边（节点连接）"""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 workflow = models.ForeignKey(
 "workflows.Workflow",
 on_delete=models.CASCADE,
 related_name="edges",
 )
 # 连接的节点
 source_node = models.ForeignKey(
 WorkflowNode,
 on_delete=models.CASCADE,
 related_name="outgoing_edges",
 )
 target_node = models.ForeignKey(
 WorkflowNode,
 on_delete=models.CASCADE,
 related_name="incoming_edges",
 )
 # 连接点（用于条件分支等多输出节点）
 source_handle = models.CharField(
 max_length=50,
 default="default",
 verbose_name="源连接点",
 help_text="如: default, true, false, branch_1",
 )
 target_handle = models.CharField(
 max_length=50,
 default="default",
 verbose_name="目标连接点",
 )
 # 条件（用于条件边）
 condition = models.JSONField(
 null=True,
 blank=True,
 verbose_name="通过条件",
 help_text="JSON 格式的条件表达式",
 )
 # 边的样式（可选）
 label = models.CharField(max_length=100, blank=True, default="")
 style = models.JSONField(default=dict, blank=True)
 created_at = models.DateTimeField(auto_now_add=True)
 class Meta:
 db_table = "workflow_edges"
 verbose_name = "工作流边"
 verbose_name_plural = "工作流边"
 # 同一对节点 + 同一连接点只能有一条边
 unique_together = [("source_node", "target_node", "source_handle", "target_handle")]
 def __str__(self) -> str:
 return f"{self.source_node.name} → {self.target_node.name}"
 def to_json(self) -> dict:
 """导出为 JSON"""
 return {
 "source_node_id": str(self.source_node_id), # type: ignore[attr-defined]
 "target_node_id": str(self.target_node_id), # type: ignore[attr-defined]
 "source_handle": self.source_handle,
 "target_handle": self.target_handle,
 "condition": self.condition,
 "label": self.label,
 }
 def clone(
 self, new_workflow: "Workflow", node_mapping: dict[uuid.UUID, uuid.UUID]
 ) -> "WorkflowEdge":
 """克隆边到新工作流"""
 return WorkflowEdge.objects.create(
 workflow=new_workflow,
 source_node_id=node_mapping[self.source_node_id], # type: ignore[attr-defined]
 target_node_id=node_mapping[self.target_node_id], # type: ignore[attr-defined]
 source_handle=self.source_handle,
 target_handle=self.target_handle,
 condition=self.condition,
 label=self.label,
 style=self.style.copy,
 )
