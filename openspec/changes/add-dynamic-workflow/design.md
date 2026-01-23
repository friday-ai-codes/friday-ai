# Design: Dynamic Workflow Engine
> **版本**: v1.0
> **状态**: Draft
> **最后更新**: 2025-01
## 目录
1. [Context](#context)
2. [Goals / Non-Goals](#goals--non-goals)
3. [核心架构](#核心架构)
4. [数据模型详细设计](#数据模型详细设计)
5. [节点类型系统](#节点类型系统)
6. [执行引擎](#执行引擎)
7. [扩展点设计](#扩展点设计)
8. [API 设计](#api-设计)
9. [前端集成](#前端集成)
10. [版本兼容策略](#版本兼容策略)
11. [安全考虑](#安全考虑)
12. [Migration Plan](#migration-plan)
---
## Context
Friday 目前使用固定的状态机驱动任务执行（见 `server/tasks/models.py`）：
```python
# 当前硬编码的状态流转
PENDING → PLANNING → PLAN_REVIEW → EXECUTING → CODE_REVIEW → MERGED
```
这种设计的局限性：
- 无法跳过某些步骤
- 无法添加自定义步骤
- 无法实现条件分支或并行执行
- 无法集成外部系统（如 n8n、部署平台）
### Stakeholders
- **开发团队**：需要灵活配置自动化流程
- **运维团队**：需要集成部署和通知
- **平台用户**：需要自定义工作流
- **第三方集成**：需要 Webhook/API 扩展
---
## Goals / Non-Goals
### Goals
- ✅ 提供可视化的工作流编辑器（Vue Flow）
- ✅ 支持节点自由组合和 DAG 执行
- ✅ 支持人工审批节点暂停/恢复
- ✅ 支持条件分支和并行执行
- ✅ 提供 Webhook 扩展点（可调用 n8n 等外部系统）
- ✅ 提供插件化节点系统（易于扩展新节点类型）
- ✅ 复用现有 Docker 执行架构
- ✅ 实时展示执行状态（WebSocket）
- ✅ **完全替代现有 Task 模型**（将固定流水线迁移为 Workflow）
### Non-Goals (v1)
- ❌ 不实现工作流版本控制（v2 考虑）
- ❌ 不实现跨项目工作流共享（v2 考虑）
- ❌ 不实现复杂表达式引擎（使用简单 JSON 条件）
- ❌ 不实现图形化调试器
---
## 核心架构
### 架构总览
```
┌─────────────────────────────────────────────────────────────────────────┐
│ Friday Workflow Engine │
├─────────────────────────────────────────────────────────────────────────┤
│ │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │
│ │ Vue Flow │ │ Django API │ │ WebSocket │ │
│ │ (Editor) │────▶│ (CRUD/Exec) │────▶│ (Realtime) │ │
│ └──────────────┘ └──────┬───────┘ └──────────────┘ │
│ │ │
│ ════════════════════════════╪═══════════════════════════════════════ │
│ Storage Layer │ Execution Layer │
│ ════════════════════════════╪═══════════════════════════════════════ │
│ │ │
│ ┌──────────────┐ ┌──────▼───────┐ ┌──────────────┐ │
│ │ Workflow │ │ Workflow │ │ Node │ │
│ │ Models │◀────│ Engine │────▶│ Registry │ │
│ └──────────────┘ └──────┬───────┘ └──────┬───────┘ │
│ │ │ │
│ ┌──────▼───────┐ ┌──────▼───────┐ │
│ │ DAG │ │ Node │ │
│ │ Scheduler │ │ Executors │ │
│ └──────┬───────┘ └──────┬───────┘ │
│ │ │ │
│ ════════════════════════════╪════════════════════╪══════════════════ │
│ Extension Points │ │ │
│ ════════════════════════════╪════════════════════╪══════════════════ │
│ │ │ │
│ ┌──────────────┐ ┌──────▼───────┐ ┌──────▼───────┐ │
│ │ Lifecycle │ │ Webhook │ │ Docker │ │
│ │ Hooks │ │ Gateway │ │ Scheduler │ │
│ └──────────────┘ └──────────────┘ └──────────────┘ │
│ │
└─────────────────────────────────────────────────────────────────────────┘
```
### 目录结构
```
server/workflows/
├── __init__.py
├── apps.py
├── models/ # 数据模型
│ ├── __init__.py
│ ├── workflow.py # Workflow, WorkflowVersion
│ ├── node.py # WorkflowNode, WorkflowEdge
│ ├── execution.py # WorkflowExecution, NodeExecution
│ └── webhook.py # WebhookConfig, WebhookLog
│
├── nodes/ # 节点类型定义
│ ├── __init__.py
│ ├── base.py # BaseNode, NodePort, NodeResult
│ ├── registry.py # NodeRegistry (自动发现)
│ ├── triggers/ # 触发器节点
│ │ ├── __init__.py
│ │ ├── manual.py
│ │ ├── webhook.py
│ │ └── schedule.py
│ ├── actions/ # 动作节点
│ │ ├── __init__.py
│ │ ├── git.py # CreateBranch, CreatePR, MergePR
│ │ ├── ai.py # AnalyzeRequirements, CodeImplement
│ │ └── http.py # HTTPRequest, WebhookCall
│ ├── control/ # 控制流节点
│ │ ├── __init__.py
│ │ ├── condition.py # If, Switch
│ │ ├── parallel.py # Fork, Join
│ │ └── wait.py # Delay, WaitForApproval
│ └── integrations/ # 集成节点
│ ├── __init__.py
│ ├── feishu.py
│ └── mcp.py
│
├── engine/ # 执行引擎
│ ├── __init__.py
│ ├── dag.py # DAG 构建和遍历
│ ├── scheduler.py # WorkflowEngine 主调度器
│ ├── executor.py # NodeExecutor 节点执行器
│ └── context.py # ExecutionContext 执行上下文
│
├── hooks/ # 生命周期钩子
│ ├── __init__.py
│ ├── base.py # BaseHook
│ └── builtin.py # 内置钩子（日志、通知等）
│
├── api/ # API 视图
│ ├── __init__.py
│ ├── views.py
│ ├── serializers.py
│ └── permissions.py
│
├── consumers.py # WebSocket consumers
├── routing.py # WebSocket routing
├── signals.py # Django signals
├── admin.py
└── urls.py
```
---
## 数据模型详细设计
### 核心模型关系
```
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ Workflow │────▶│ WorkflowNode │────▶│ WorkflowEdge │
│ (工作流模板) │ 1:n │ (节点) │ 1:n │ (边) │
└─────────────────┘ └─────────────────┘ └─────────────────┘
 │ │
 │ 1:n │ 1:n
 ▼ ▼
┌─────────────────┐ ┌─────────────────┐
│WorkflowExecution│────▶│ NodeExecution │
│ (执行实例) │ 1:n │ (节点执行记录) │
└─────────────────┘ └─────────────────┘
```
### Model: Workflow
```python
# server/workflows/models/workflow.py
import uuid
from django.db import models
from django.contrib.auth import get_user_model
User = get_user_model
class Workflow(models.Model):
 """工作流模板定义"""
 class TriggerType(models.TextChoices):
 MANUAL = "manual", "手动触发"
 WEBHOOK = "webhook", "Webhook 触发"
 SCHEDULE = "schedule", "定时触发"
 EVENT = "event", "事件触发"
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 # 基本信息
 name = models.CharField(max_length=200, verbose_name="名称")
 description = models.TextField(blank=True, default="", verbose_name="描述")
 icon = models.CharField(max_length=50, default="workflow", verbose_name="图标")
 # 关联
 project = models.ForeignKey(
 "projects.Project",
 on_delete=models.CASCADE,
 related_name="workflows",
 verbose_name="所属项目",
 )
 created_by = models.ForeignKey(
 User,
 on_delete=models.SET_NULL,
 null=True,
 related_name="created_workflows",
 verbose_name="创建者",
 )
 # 触发配置
 trigger_type = models.CharField(
 max_length=20,
 choices=TriggerType.choices,
 default=TriggerType.MANUAL,
 verbose_name="触发类型",
 )
 trigger_config = models.JSONField(
 default=dict,
 blank=True,
 verbose_name="触发配置",
 help_text="根据触发类型存储不同配置，如 cron 表达式、webhook secret 等",
 )
 # 状态
 is_active = models.BooleanField(default=True, verbose_name="是否启用")
 is_template = models.BooleanField(
 default=False,
 verbose_name="是否为模板",
 help_text="模板可被其他项目复制",
 )
 # 执行配置
 max_concurrent_executions = models.PositiveIntegerField(
 default=1,
 verbose_name="最大并发执行数",
 help_text="0 表示不限制",
 )
 default_timeout = models.PositiveIntegerField(
 default=3600,
 verbose_name="默认超时(秒)",
 )
 # 元数据
 metadata = models.JSONField(
 default=dict,
 blank=True,
 verbose_name="元数据",
 help_text="存储画布位置、缩放等 UI 状态",
 )
 # 时间戳
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "workflows"
 verbose_name = "工作流"
 verbose_name_plural = "工作流"
 ordering = ["-updated_at"]
 indexes = [
 models.Index(fields=["project", "is_active"]),
 models.Index(fields=["trigger_type"]),
 ]
 def __str__(self):
 return f"{self.name} ({self.project.name})"
 def clone(self, new_project=None, new_name=None):
 """克隆工作流到另一个项目"""
 new_workflow = Workflow.objects.create(
 name=new_name or f"{self.name} (副本)",
 description=self.description,
 project=new_project or self.project,
 trigger_type=self.trigger_type,
 trigger_config=self.trigger_config.copy,
 default_timeout=self.default_timeout,
 metadata=self.metadata.copy,
 )
 # 克隆节点
 node_mapping = {}
 for node in self.nodes.all:
 new_node = node.clone(new_workflow)
 node_mapping[node.id] = new_node.id
 # 克隆边（更新节点引用）
 for edge in self.edges.all:
 edge.clone(new_workflow, node_mapping)
 return new_workflow
 def to_json(self) -> dict:
 """导出为 JSON 格式（用于导入/导出）"""
 return {
 "version": "1.0",
 "workflow": {
 "name": self.name,
 "description": self.description,
 "trigger_type": self.trigger_type,
 "trigger_config": self.trigger_config,
 "default_timeout": self.default_timeout,
 },
 "nodes": [node.to_json for node in self.nodes.all],
 "edges": [edge.to_json for edge in self.edges.all],
 }
 @classmethod
 def from_json(cls, data: dict, project, created_by=None):
 """从 JSON 导入工作流"""
 workflow_data = data["workflow"]
 workflow = cls.objects.create(
 name=workflow_data["name"],
 description=workflow_data.get("description", ""),
 project=project,
 created_by=created_by,
 trigger_type=workflow_data.get("trigger_type", "manual"),
 trigger_config=workflow_data.get("trigger_config", {}),
 default_timeout=workflow_data.get("default_timeout", 3600),
 )
 # 导入节点
 node_id_mapping = {}
 for node_data in data.get("nodes", ):
 old_id = node_data.pop("id", None)
 node = WorkflowNode.objects.create(workflow=workflow, **node_data)
 if old_id:
 node_id_mapping[old_id] = str(node.id)
 # 导入边（映射节点 ID）
 for edge_data in data.get("edges", ):
 source_id = node_id_mapping.get(edge_data["source_node_id"])
 target_id = node_id_mapping.get(edge_data["target_node_id"])
 if source_id and target_id:
 WorkflowEdge.objects.create(
 workflow=workflow,
 source_node_id=source_id,
 target_node_id=target_id,
 source_handle=edge_data.get("source_handle", "default"),
 target_handle=edge_data.get("target_handle", "default"),
 condition=edge_data.get("condition"),
 )
 return workflow
```
### Model: WorkflowNode
```python
# server/workflows/models/node.py
import uuid
from django.db import models
from django.core.exceptions import ValidationError
class WorkflowNode(models.Model):
 """工作流节点"""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 workflow = models.ForeignKey(
 "workflows.Workflow",
 on_delete=models.CASCADE,
 related_name="nodes",
 )
 # 节点类型（对应 NodeRegistry 中注册的类型）
 node_type = models.CharField(
 max_length=100,
 verbose_name="节点类型",
 help_text="如: manual_trigger, create_branch, code_implement",
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
 def __str__(self):
 return f"{self.name} ({self.node_type})"
 def clean(self):
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
 return {
 "id": str(self.id),
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
 def clone(self, new_workflow):
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
 unique_together = [
 ("source_node", "target_node", "source_handle", "target_handle")
 ]
 def __str__(self):
 return f"{self.source_node.name} → {self.target_node.name}"
 def to_json(self) -> dict:
 return {
 "source_node_id": str(self.source_node_id),
 "target_node_id": str(self.target_node_id),
 "source_handle": self.source_handle,
 "target_handle": self.target_handle,
 "condition": self.condition,
 "label": self.label,
 }
 def clone(self, new_workflow, node_mapping: dict):
 """克隆边到新工作流"""
 return WorkflowEdge.objects.create(
 workflow=new_workflow,
 source_node_id=node_mapping[self.source_node_id],
 target_node_id=node_mapping[self.target_node_id],
 source_handle=self.source_handle,
 target_handle=self.target_handle,
 condition=self.condition,
 label=self.label,
 style=self.style.copy,
 )
```
### Model: WorkflowExecution
```python
# server/workflows/models/execution.py
import uuid
from django.db import models
from django.utils import timezone
class ExecutionStatus(models.TextChoices):
 """执行状态"""
 PENDING = "pending", "待执行"
 RUNNING = "running", "执行中"
 PAUSED = "paused", "已暂停"
 COMPLETED = "completed", "已完成"
 FAILED = "failed", "失败"
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
 # 可选关联到 Task（用于从旧系统迁移）
 task = models.ForeignKey(
 "tasks.Task",
 on_delete=models.SET_NULL,
 null=True,
 blank=True,
 related_name="workflow_executions",
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
 def __str__(self):
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
 def mark_started(self):
 """标记开始执行"""
 self.status = ExecutionStatus.RUNNING
 self.started_at = timezone.now
 self.timeout_at = timezone.now + timezone.timedelta(
 seconds=self.workflow.default_timeout
 )
 self.save(update_fields=["status", "started_at", "timeout_at"])
 def mark_completed(self, output_data: dict = None):
 """标记执行完成"""
 self.status = ExecutionStatus.COMPLETED
 self.completed_at = timezone.now
 if output_data:
 self.output_data = output_data
 self.save(update_fields=["status", "completed_at", "output_data"])
 def mark_failed(self, error: str, node_id: uuid.UUID = None):
 """标记执行失败"""
 self.status = ExecutionStatus.FAILED
 self.completed_at = timezone.now
 self.error_message = error
 self.error_node_id = node_id
 self.save(update_fields=[
 "status", "completed_at", "error_message", "error_node_id"
 ])
 def get_context_value(self, key: str, default=None):
 """获取上下文变量"""
 return self.context.get(key, default)
 def set_context_value(self, key: str, value):
 """设置上下文变量"""
 self.context[key] = value
 self.save(update_fields=["context"])
 def update_context(self, data: dict):
 """批量更新上下文"""
 self.context.update(data)
 self.save(update_fields=["context"])
class NodeExecutionStatus(models.TextChoices):
 """节点执行状态"""
 PENDING = "pending", "待执行"
 QUEUED = "queued", "排队中"
 RUNNING = "running", "执行中"
 WAITING_APPROVAL = "waiting_approval", "等待审批"
 WAITING_INPUT = "waiting_input", "等待输入"
 COMPLETED = "completed", "已完成"
 FAILED = "failed", "失败"
 SKIPPED = "skipped", "已跳过"
 CANCELLED = "cancelled", "已取消"
 TIMEOUT = "timeout", "超时"
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
 def __str__(self):
 return f"{self.node.name} - {self.status}"
 @property
 def duration(self) -> float | None:
 """执行时长（秒）"""
 if self.started_at and self.completed_at:
 return (self.completed_at - self.started_at).total_seconds
 return None
 def mark_started(self):
 """标记开始执行"""
 self.status = NodeExecutionStatus.RUNNING
 self.started_at = timezone.now
 self.save(update_fields=["status", "started_at"])
 def mark_completed(self, output_data: dict = None):
 """标记执行完成"""
 self.status = NodeExecutionStatus.COMPLETED
 self.completed_at = timezone.now
 if output_data:
 self.output_data = output_data
 self.save(update_fields=["status", "completed_at", "output_data"])
 # 更新父执行的统计
 self.workflow_execution.completed_nodes += 1
 self.workflow_execution.save(update_fields=["completed_nodes"])
 def mark_failed(self, error: str, traceback: str = ""):
 """标记执行失败"""
 self.status = NodeExecutionStatus.FAILED
 self.completed_at = timezone.now
 self.error_message = error
 self.error_traceback = traceback
 self.save(update_fields=[
 "status", "completed_at", "error_message", "error_traceback"
 ])
 # 更新父执行的统计
 self.workflow_execution.failed_nodes += 1
 self.workflow_execution.save(update_fields=["failed_nodes"])
 def mark_skipped(self, reason: str = ""):
 """标记跳过"""
 self.status = NodeExecutionStatus.SKIPPED
 self.completed_at = timezone.now
 self.error_message = reason
 self.save(update_fields=["status", "completed_at", "error_message"])
 # 更新父执行的统计
 self.workflow_execution.skipped_nodes += 1
 self.workflow_execution.save(update_fields=["skipped_nodes"])
 def mark_waiting_approval(self, approval_request: dict):
 """标记等待审批"""
 self.status = NodeExecutionStatus.WAITING_APPROVAL
 self.approval_data = approval_request
 self.save(update_fields=["status", "approval_data"])
 def approve(self, approver, comment: str = ""):
 """审批通过"""
 self.approval_data.update({
 "approved": True,
 "approver_id": approver.id,
 "approver_name": approver.username,
 "comment": comment,
 "approved_at": timezone.now.isoformat,
 })
 self.save(update_fields=["approval_data"])
 # 状态变更由引擎处理
 def reject(self, approver, comment: str = ""):
 """审批拒绝"""
 self.approval_data.update({
 "approved": False,
 "approver_id": approver.id,
 "approver_name": approver.username,
 "comment": comment,
 "rejected_at": timezone.now.isoformat,
 })
 self.mark_failed(f"审批被拒绝: {comment}")
```
---
## 节点类型系统
### 核心抽象
```python
# server/workflows/nodes/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar
import jsonschema
class NodeCategory(str, Enum):
 """节点分类"""
 TRIGGER = "trigger" # 触发器
 ACTION = "action" # 动作
 CONTROL = "control" # 控制流
 INTEGRATION = "integration" # 集成
 AI = "ai" # AI 相关
class PortType(str, Enum):
 """端口数据类型"""
 ANY = "any"
 STRING = "string"
 NUMBER = "number"
 BOOLEAN = "boolean"
 OBJECT = "object"
 ARRAY = "array"
 FILE = "file"
@dataclass
class NodePort:
 """节点端口定义"""
 name: str
 label: str
 port_type: PortType = PortType.ANY
 required: bool = True
 default: Any = None
 description: str = ""
@dataclass
class NodeResult:
 """节点执行结果"""
 status: str # completed, failed, waiting_approval, waiting_input
 output: dict = field(default_factory=dict)
 error: str | None = None
 next_handle: str = "default" # 用于条件分支，指定走哪个输出
@dataclass
class ExecutionContext:
 """节点执行上下文"""
 execution_id: str
 node_id: str
 node_config: dict
 input_data: dict
 workflow_context: dict # 全局上下文
 previous_outputs: dict[str, dict] # 上游节点输出 {node_id: output}
 # 服务注入
 workflow_execution: Any = None
 node_execution: Any = None
 def get_input(self, key: str, default=None):
 """获取输入数据"""
 return self.input_data.get(key, default)
 def get_config(self, key: str, default=None):
 """获取节点配置"""
 return self.node_config.get(key, default)
 def get_context(self, key: str, default=None):
 """获取工作流上下文"""
 return self.workflow_context.get(key, default)
 def get_previous_output(self, node_id: str, key: str = None, default=None):
 """获取上游节点输出"""
 output = self.previous_outputs.get(node_id, {})
 if key:
 return output.get(key, default)
 return output
 def render_template(self, template: str) -> str:
 """渲染模板字符串，支持变量替换
 支持格式：
 - {{input.key}} - 输入数据
 - {{context.key}} - 工作流上下文
 - {{config.key}} - 节点配置
 - {{nodes.node_id.key}} - 上游节点输出
 """
 import re
 def replace(match):
 path = match.group(1).strip
 parts = path.split(".")
 if parts[0] == "input":
 return str(self.get_input(".".join(parts[1:])))
 elif parts[0] == "context":
 return str(self.get_context(".".join(parts[1:])))
 elif parts[0] == "config":
 return str(self.get_config(".".join(parts[1:])))
 elif parts[0] == "nodes" and len(parts) >= 3:
 node_id = parts[1]
 key = ".".join(parts[2:])
 return str(self.get_previous_output(node_id, key))
 return match.group(0) # 无法解析则保持原样
 return re.sub(r"\{\{(.+?)\}\}", replace, template)
class BaseNode(ABC):
 """节点基类
 所有节点类型必须继承此类并实现 execute 方法。
 """
 # 节点类型标识（必须唯一）
 node_type: ClassVar[str]
 # 显示信息
 display_name: ClassVar[str]
 description: ClassVar[str] = ""
 icon: ClassVar[str] = "box"
 # 分类
 category: ClassVar[NodeCategory]
 # 配置 Schema（JSON Schema 格式）
 config_schema: ClassVar[dict] = {
 "type": "object",
 "properties": {},
 "required":,
 }
 # 输入/输出端口
 inputs: ClassVar[list[NodePort]] = [
 NodePort(name="default", label="输入", required=False)
 ]
 outputs: ClassVar[list[NodePort]] = [
 NodePort(name="default", label="输出")
 ]
 # 执行选项
 requires_container: ClassVar[bool] = False # 是否需要 Docker 容器
 supports_retry: ClassVar[bool] = True # 是否支持重试
 is_blocking: ClassVar[bool] = False # 是否阻塞（如审批节点）
 @classmethod
 def validate_config(cls, config: dict) -> list[str]:
 """验证节点配置"""
 errors =
 try:
 jsonschema.validate(config, cls.config_schema)
 except jsonschema.ValidationError as e:
 errors.append(str(e.message))
 return errors
 @classmethod
 def get_schema(cls) -> dict:
 """获取完整的节点 Schema（用于前端）"""
 return {
 "node_type": cls.node_type,
 "display_name": cls.display_name,
 "description": cls.description,
 "icon": cls.icon,
 "category": cls.category.value,
 "config_schema": cls.config_schema,
 "inputs": [
 {
 "name": p.name,
 "label": p.label,
 "type": p.port_type.value,
 "required": p.required,
 "description": p.description,
 }
 for p in cls.inputs
 ],
 "outputs": [
 {
 "name": p.name,
 "label": p.label,
 "type": p.port_type.value,
 "description": p.description,
 }
 for p in cls.outputs
 ],
 "requires_container": cls.requires_container,
 "is_blocking": cls.is_blocking,
 }
 @abstractmethod
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """执行节点
 Args:
 context: 执行上下文
 Returns:
 NodeResult: 执行结果
 """
 pass
 async def on_cancel(self, context: ExecutionContext):
 """取消执行时的清理操作"""
 pass
 async def on_timeout(self, context: ExecutionContext):
 """超时时的清理操作"""
 pass
```
### 节点注册表
```python
# server/workflows/nodes/registry.py
import importlib
import pkgutil
from typing import Type
import structlog
from .base import BaseNode
logger = structlog.get_logger
class NodeRegistry:
 """节点类型注册表
 使用单例模式，自动发现并注册所有节点类型。
 """
 _instance = None
 _nodes: dict[str, Type[BaseNode]] = {}
 _initialized = False
 def __new__(cls):
 if cls._instance is None:
 cls._instance = super.__new__(cls)
 return cls._instance
 @classmethod
 def register(cls, node_class: Type[BaseNode]):
 """手动注册节点类型"""
 if not hasattr(node_class, "node_type"):
 raise ValueError(f"节点类 {node_class.__name__} 缺少 node_type 属性")
 node_type = node_class.node_type
 if node_type in cls._nodes:
 logger.warning(
 "node_type_already_registered",
 node_type=node_type,
 existing=cls._nodes[node_type].__name__,
 new=node_class.__name__,
 )
 cls._nodes[node_type] = node_class
 logger.debug("node_type_registered", node_type=node_type)
 @classmethod
 def get(cls, node_type: str) -> Type[BaseNode] | None:
 """获取节点类型"""
 cls._ensure_initialized
 return cls._nodes.get(node_type)
 @classmethod
 def get_all(cls) -> dict[str, Type[BaseNode]]:
 """获取所有注册的节点类型"""
 cls._ensure_initialized
 return cls._nodes.copy
 @classmethod
 def get_by_category(cls, category: str) -> list[Type[BaseNode]]:
 """按分类获取节点类型"""
 cls._ensure_initialized
 return [
 node for node in cls._nodes.values
 if node.category.value == category
 ]
 @classmethod
 def get_all_schemas(cls) -> list[dict]:
 """获取所有节点的 Schema（用于前端）"""
 cls._ensure_initialized
 return [node.get_schema for node in cls._nodes.values]
 @classmethod
 def _ensure_initialized(cls):
 """确保已初始化（自动发现节点）"""
 if cls._initialized:
 return
 cls._auto_discover
 cls._initialized = True
 @classmethod
 def _auto_discover(cls):
 """自动发现并注册节点类型
 扫描 workflows.nodes 下的所有模块，找到 BaseNode 的子类。
 """
 import workflows.nodes as nodes_package
 # 遍历 nodes 包下的所有子模块
 for importer, modname, ispkg in pkgutil.walk_packages(
 nodes_package.__path__,
 prefix=nodes_package.__name__ + ".",
 ):
 try:
 module = importlib.import_module(modname)
 # 查找模块中所有 BaseNode 的子类
 for attr_name in dir(module):
 attr = getattr(module, attr_name)
 if (
 isinstance(attr, type)
 and issubclass(attr, BaseNode)
 and attr is not BaseNode
 and hasattr(attr, "node_type")
 ):
 cls.register(attr)
 except Exception as e:
 logger.error(
 "node_discovery_error",
 module=modname,
 error=str(e),
 )
# 装饰器，用于注册节点
def register_node(cls: Type[BaseNode]) -> Type[BaseNode]:
 """节点注册装饰器
 用法：
 @register_node
 class MyNode(BaseNode):
 node_type = "my_node"
 ...
 """
 NodeRegistry.register(cls)
 return cls
```
### 示例节点实现
#### 手动触发器
```python
# server/workflows/nodes/triggers/manual.py
from workflows.nodes.base import (
 BaseNode, NodeCategory, NodePort, NodeResult, ExecutionContext, PortType
)
from workflows.nodes.registry import register_node
@register_node
class ManualTriggerNode(BaseNode):
 """手动触发节点
 工作流的入口点，由用户手动触发执行。
 """
 node_type = "manual_trigger"
 display_name = "手动触发"
 description = "手动触发工作流执行"
 icon = "play"
 category = NodeCategory.TRIGGER
 config_schema = {
 "type": "object",
 "properties": {
 "input_schema": {
 "type": "object",
 "title": "输入参数定义",
 "description": "定义用户触发时需要输入的参数",
 "default": {},
 },
 },
 }
 inputs = # 触发器没有输入
 outputs = [
 NodePort(
 name="default",
 label="输出",
 port_type=PortType.OBJECT,
 description="触发时传入的数据",
 )
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """直接将触发数据作为输出"""
 return NodeResult(
 status="completed",
 output=context.input_data,
 )
```
#### Webhook 触发器
```python
# server/workflows/nodes/triggers/webhook.py
from workflows.nodes.base import (
 BaseNode, NodeCategory, NodePort, NodeResult, ExecutionContext, PortType
)
from workflows.nodes.registry import register_node
@register_node
class WebhookTriggerNode(BaseNode):
 """Webhook 触发节点
 通过 HTTP Webhook 触发工作流执行。
 """
 node_type = "webhook_trigger"
 display_name = "Webhook 触发"
 description = "通过 HTTP Webhook 触发工作流"
 icon = "webhook"
 category = NodeCategory.TRIGGER
 config_schema = {
 "type": "object",
 "properties": {
 "path": {
 "type": "string",
 "title": "Webhook 路径",
 "description": "自定义的 webhook 路径后缀",
 "default": "",
 },
 "method": {
 "type": "string",
 "title": "HTTP 方法",
 "enum": ["POST", "GET", "PUT"],
 "default": "POST",
 },
 "secret": {
 "type": "string",
 "title": "验证密钥",
 "description": "用于验证 webhook 请求的密钥",
 "default": "",
 },
 "response_mode": {
 "type": "string",
 "title": "响应模式",
 "enum": ["immediate", "wait"],
 "default": "immediate",
 "description": "immediate: 立即响应; wait: 等待工作流完成后响应",
 },
 },
 }
 inputs =
 outputs = [
 NodePort(name="default", label="Payload", port_type=PortType.OBJECT),
 NodePort(name="headers", label="Headers", port_type=PortType.OBJECT),
 NodePort(name="query", label="Query Params", port_type=PortType.OBJECT),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """将 webhook 数据作为输出"""
 return NodeResult(
 status="completed",
 output={
 "body": context.input_data.get("body", {}),
 "headers": context.input_data.get("headers", {}),
 "query": context.input_data.get("query", {}),
 },
 )
```
#### HTTP 请求节点（可调用 n8n 等外部系统）
```python
# server/workflows/nodes/actions/http.py
import httpx
from workflows.nodes.base import (
 BaseNode, NodeCategory, NodePort, NodeResult, ExecutionContext, PortType
)
from workflows.nodes.registry import register_node
@register_node
class HTTPRequestNode(BaseNode):
 """HTTP 请求节点
 发送 HTTP 请求到外部 API，可用于调用 n8n webhook 等。
 """
 node_type = "http_request"
 display_name = "HTTP 请求"
 description = "发送 HTTP 请求到外部 API"
 icon = "globe"
 category = NodeCategory.INTEGRATION
 config_schema = {
 "type": "object",
 "properties": {
 "url": {
 "type": "string",
 "title": "URL",
 "description": "请求地址，支持模板变量 {{input.xxx}}",
 },
 "method": {
 "type": "string",
 "title": "方法",
 "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
 "default": "POST",
 },
 "headers": {
 "type": "object",
 "title": "请求头",
 "additionalProperties": {"type": "string"},
 "default": {},
 },
 "body_type": {
 "type": "string",
 "title": "Body 类型",
 "enum": ["none", "json", "form", "raw"],
 "default": "json",
 },
 "body": {
 "type": ["object", "string"],
 "title": "请求体",
 "default": {},
 },
 "timeout": {
 "type": "integer",
 "title": "超时(秒)",
 "default": 30,
 "minimum": 1,
 "maximum": 300,
 },
 "ignore_ssl": {
 "type": "boolean",
 "title": "忽略 SSL 验证",
 "default": False,
 },
 "retry_on_error": {
 "type": "boolean",
 "title": "错误时重试",
 "default": True,
 },
 },
 "required": ["url"],
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = [
 NodePort(name="default", label="响应", port_type=PortType.OBJECT),
 NodePort(name="error", label="错误", port_type=PortType.OBJECT),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 # 渲染模板变量
 url = context.render_template(config.get("url", ""))
 method = config.get("method", "POST")
 headers = {
 k: context.render_template(v)
 for k, v in config.get("headers", {}).items
 }
 timeout = config.get("timeout", 30)
 # 构建请求体
 body_type = config.get("body_type", "json")
 body = config.get("body", {})
 if isinstance(body, str):
 body = context.render_template(body)
 elif isinstance(body, dict):
 # 对 dict 中的字符串值进行模板渲染
 body = self._render_dict(body, context)
 try:
 async with httpx.AsyncClient(
 verify=not config.get("ignore_ssl", False)
 ) as client:
 request_kwargs = {
 "method": method,
 "url": url,
 "headers": headers,
 "timeout": timeout,
 }
 if body_type == "json" and body:
 request_kwargs["json"] = body
 elif body_type == "form" and body:
 request_kwargs["data"] = body
 elif body_type == "raw" and body:
 request_kwargs["content"] = body
 response = await client.request(**request_kwargs)
 # 尝试解析 JSON 响应
 try:
 response_data = response.json
 except Exception:
 response_data = response.text
 return NodeResult(
 status="completed",
 output={
 "status_code": response.status_code,
 "headers": dict(response.headers),
 "body": response_data,
 "ok": response.is_success,
 },
 next_handle="default" if response.is_success else "error",
 )
 except httpx.TimeoutException:
 return NodeResult(
 status="failed",
 error=f"请求超时 ({timeout}s)",
 next_handle="error",
 )
 except Exception as e:
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
 def _render_dict(self, d: dict, context: ExecutionContext) -> dict:
 """递归渲染字典中的模板字符串"""
 result = {}
 for k, v in d.items:
 if isinstance(v, str):
 result[k] = context.render_template(v)
 elif isinstance(v, dict):
 result[k] = self._render_dict(v, context)
 elif isinstance(v, list):
 result[k] = [
 context.render_template(i) if isinstance(i, str) else i
 for i in v
 ]
 else:
 result[k] = v
 return result
```
#### Webhook 调用节点（专门调用外部工作流系统）
```python
# server/workflows/nodes/actions/webhook_call.py
from workflows.nodes.base import (
 BaseNode, NodeCategory, NodePort, NodeResult, ExecutionContext, PortType
)
from workflows.nodes.registry import register_node
@register_node
class WebhookCallNode(BaseNode):
 """Webhook 调用节点
 调用外部工作流系统（如 n8n）的 webhook，并可选择等待响应。
 """
 node_type = "webhook_call"
 display_name = "调用 Webhook"
 description = "调用外部系统的 Webhook（如 n8n、Zapier）"
 icon = "external-link"
 category = NodeCategory.INTEGRATION
 config_schema = {
 "type": "object",
 "properties": {
 "webhook_url": {
 "type": "string",
 "title": "Webhook URL",
 "description": "外部系统的 webhook 地址",
 },
 "wait_for_response": {
 "type": "boolean",
 "title": "等待响应",
 "description": "是否等待外部系统处理完成并返回结果",
 "default": True,
 },
 "timeout": {
 "type": "integer",
 "title": "超时(秒)",
 "default": 60,
 "minimum": 5,
 "maximum": 600,
 },
 "payload_template": {
 "type": "object",
 "title": "请求数据模板",
 "description": "发送给 webhook 的数据，支持模板变量",
 "default": {},
 },
 "authentication": {
 "type": "object",
 "title": "认证配置",
 "properties": {
 "type": {
 "type": "string",
 "enum": ["none", "basic", "bearer", "header"],
 "default": "none",
 },
 "username": {"type": "string"},
 "password": {"type": "string"},
 "token": {"type": "string"},
 "header_name": {"type": "string"},
 "header_value": {"type": "string"},
 },
 },
 "callback_config": {
 "type": "object",
 "title": "回调配置",
 "description": "如果外部系统需要异步回调",
 "properties": {
 "enabled": {"type": "boolean", "default": False},
 "callback_path": {"type": "string"},
 "timeout": {"type": "integer", "default": 3600},
 },
 },
 },
 "required": ["webhook_url"],
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = [
 NodePort(name="default", label="响应", port_type=PortType.OBJECT),
 NodePort(name="error", label="错误", port_type=PortType.OBJECT),
 ]
 is_blocking = True # 可能需要等待回调
 async def execute(self, context: ExecutionContext) -> NodeResult:
 import httpx
 config = context.node_config
 webhook_url = context.render_template(config["webhook_url"])
 # 构建请求数据
 payload = self._build_payload(config.get("payload_template", {}), context)
 # 添加 Friday 元数据（便于外部系统回调）
 payload["_friday_metadata"] = {
 "execution_id": context.execution_id,
 "node_id": context.node_id,
 "callback_url": self._get_callback_url(context),
 }
 # 构建请求头
 headers = {"Content-Type": "application/json"}
 auth_config = config.get("authentication", {})
 auth_type = auth_config.get("type", "none")
 if auth_type == "basic":
 import base64
 credentials = base64.b64encode(
 f"{auth_config['username']}:{auth_config['password']}".encode
 ).decode
 headers["Authorization"] = f"Basic {credentials}"
 elif auth_type == "bearer":
 headers["Authorization"] = f"Bearer {auth_config['token']}"
 elif auth_type == "header":
 headers[auth_config["header_name"]] = auth_config["header_value"]
 try:
 async with httpx.AsyncClient as client:
 response = await client.post(
 webhook_url,
 json=payload,
 headers=headers,
 timeout=config.get("timeout", 60),
 )
 if response.is_success:
 try:
 result = response.json
 except Exception:
 result = {"raw": response.text}
 return NodeResult(
 status="completed",
 output=result,
 )
 else:
 return NodeResult(
 status="failed",
 error=f"Webhook 返回错误: {response.status_code}",
 output={"status_code": response.status_code, "body": response.text},
 next_handle="error",
 )
 except Exception as e:
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
 def _build_payload(self, template: dict, context: ExecutionContext) -> dict:
 """构建请求数据"""
 if not template:
 # 默认传递所有输入数据
 return context.input_data.copy
 # 渲染模板
 result = {}
 for k, v in template.items:
 if isinstance(v, str):
 result[k] = context.render_template(v)
 elif isinstance(v, dict):
 result[k] = self._build_payload(v, context)
 else:
 result[k] = v
 return result
 def _get_callback_url(self, context: ExecutionContext) -> str:
 """获取回调 URL"""
 from django.conf import settings
 base_url = getattr(settings, "FRIDAY_BASE_URL", "http://localhost:8000")
 return f"{base_url}/api/workflows/callbacks/{context.execution_id}/{context.node_id}/"
```
#### 人工审批节点
```python
# server/workflows/nodes/control/approval.py
from workflows.nodes.base import (
 BaseNode, NodeCategory, NodePort, NodeResult, ExecutionContext, PortType
)
from workflows.nodes.registry import register_node
@register_node
class HumanApprovalNode(BaseNode):
 """人工审批节点
 暂停工作流执行，等待人工审批。
 """
 node_type = "human_approval"
 display_name = "人工审批"
 description = "暂停执行，等待人工审批通过后继续"
 icon = "user-check"
 category = NodeCategory.CONTROL
 config_schema = {
 "type": "object",
 "properties": {
 "title": {
 "type": "string",
 "title": "审批标题",
 "default": "请审批",
 },
 "description": {
 "type": "string",
 "title": "审批说明",
 "default": "",
 },
 "approvers": {
 "type": "array",
 "title": "审批人",
 "description": "指定审批人的用户 ID 列表，为空则项目成员均可审批",
 "items": {"type": "string"},
 "default":,
 },
 "require_all": {
 "type": "boolean",
 "title": "需要所有人审批",
 "description": "是否需要所有指定审批人都通过",
 "default": False,
 },
 "timeout_hours": {
 "type": "integer",
 "title": "超时时间(小时)",
 "description": "超时后自动拒绝，0 表示不超时",
 "default": 0,
 },
 "notification": {
 "type": "object",
 "title": "通知配置",
 "properties": {
 "enabled": {"type": "boolean", "default": True},
 "channels": {
 "type": "array",
 "items": {"type": "string", "enum": ["feishu", "email"]},
 "default": ["feishu"],
 },
 },
 },
 "show_data": {
 "type": "array",
 "title": "展示数据",
 "description": "在审批页面展示的输入数据字段",
 "items": {"type": "string"},
 "default":,
 },
 },
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = [
 NodePort(name="approved", label="通过", port_type=PortType.OBJECT),
 NodePort(name="rejected", label="拒绝", port_type=PortType.OBJECT),
 ]
 is_blocking = True
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 # 构建审批请求
 approval_request = {
 "title": context.render_template(config.get("title", "请审批")),
 "description": context.render_template(config.get("description", "")),
 "approvers": config.get("approvers", ),
 "require_all": config.get("require_all", False),
 "timeout_hours": config.get("timeout_hours", 0),
 "display_data": self._extract_display_data(
 context.input_data,
 config.get("show_data", ),
 ),
 "requested_at": context.workflow_context.get("started_at"),
 }
 # 发送通知
 notification_config = config.get("notification", {})
 if notification_config.get("enabled", True):
 await self._send_notifications(
 context,
 approval_request,
 notification_config.get("channels", ["feishu"]),
 )
 # 返回等待审批状态
 return NodeResult(
 status="waiting_approval",
 output=approval_request,
 )
 def _extract_display_data(self, input_data: dict, fields: list) -> dict:
 """提取要展示的数据"""
 if not fields:
 return input_data
 return {k: input_data.get(k) for k in fields if k in input_data}
 async def _send_notifications(
 self,
 context: ExecutionContext,
 approval_request: dict,
 channels: list[str],
 ):
 """发送审批通知"""
 # TODO: 实现通知发送逻辑
 pass
```
#### 条件分支节点
```python
# server/workflows/nodes/control/condition.py
from workflows.nodes.base import (
 BaseNode, NodeCategory, NodePort, NodeResult, ExecutionContext, PortType
)
from workflows.nodes.registry import register_node
@register_node
class ConditionNode(BaseNode):
 """条件分支节点
 根据条件表达式决定走哪个分支。
 """
 node_type = "condition"
 display_name = "条件分支"
 description = "根据条件判断走不同的分支"
 icon = "git-branch"
 category = NodeCategory.CONTROL
 config_schema = {
 "type": "object",
 "properties": {
 "conditions": {
 "type": "array",
 "title": "条件列表",
 "items": {
 "type": "object",
 "properties": {
 "name": {
 "type": "string",
 "title": "分支名称",
 },
 "expression": {
 "type": "object",
 "title": "条件表达式",
 "properties": {
 "field": {"type": "string"},
 "operator": {
 "type": "string",
 "enum": [
 "eq", "ne", "gt", "gte", "lt", "lte",
 "contains", "not_contains",
 "starts_with", "ends_with",
 "is_empty", "is_not_empty",
 "is_true", "is_false",
 ],
 },
 "value": {},
 },
 },
 },
 },
 "default":,
 },
 "default_branch": {
 "type": "string",
 "title": "默认分支",
 "description": "当所有条件都不满足时走的分支",
 "default": "else",
 },
 },
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = # 动态输出，根据条件数量决定
 @classmethod
 def get_dynamic_outputs(cls, config: dict) -> list[NodePort]:
 """根据配置动态生成输出端口"""
 outputs =
 for i, condition in enumerate(config.get("conditions", )):
 outputs.append(NodePort(
 name=f"branch_{i}",
 label=condition.get("name", f"分支 {i + 1}"),
 port_type=PortType.OBJECT,
 ))
 outputs.append(NodePort(
 name=config.get("default_branch", "else"),
 label="默认",
 port_type=PortType.OBJECT,
 ))
 return outputs
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 conditions = config.get("conditions", )
 input_data = context.input_data
 # 评估每个条件
 for i, condition in enumerate(conditions):
 if self._evaluate_condition(condition.get("expression", {}), input_data):
 return NodeResult(
 status="completed",
 output=input_data,
 next_handle=f"branch_{i}",
 )
 # 走默认分支
 return NodeResult(
 status="completed",
 output=input_data,
 next_handle=config.get("default_branch", "else"),
 )
 def _evaluate_condition(self, expression: dict, data: dict) -> bool:
 """评估条件表达式"""
 field = expression.get("field", "")
 operator = expression.get("operator", "eq")
 expected = expression.get("value")
 # 获取字段值（支持嵌套路径）
 actual = self._get_nested_value(data, field)
 # 评估
 if operator == "eq":
 return actual == expected
 elif operator == "ne":
 return actual != expected
 elif operator == "gt":
 return actual > expected
 elif operator == "gte":
 return actual >= expected
 elif operator == "lt":
 return actual < expected
 elif operator == "lte":
 return actual <= expected
 elif operator == "contains":
 return expected in str(actual)
 elif operator == "not_contains":
 return expected not in str(actual)
 elif operator == "starts_with":
 return str(actual).startswith(str(expected))
 elif operator == "ends_with":
 return str(actual).endswith(str(expected))
 elif operator == "is_empty":
 return not actual
 elif operator == "is_not_empty":
 return bool(actual)
 elif operator == "is_true":
 return actual is True
 elif operator == "is_false":
 return actual is False
 return False
 def _get_nested_value(self, data: dict, path: str):
 """获取嵌套字段值"""
 keys = path.split(".")
 value = data
 for key in keys:
 if isinstance(value, dict):
 value = value.get(key)
 else:
 return None
 return value
```
---
## 执行引擎
### DAG 构建器
```python
# server/workflows/engine/dag.py
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
import structlog
if TYPE_CHECKING:
 from workflows.models import WorkflowNode, WorkflowEdge
logger = structlog.get_logger
@dataclass
class DAGNode:
 """DAG 节点包装"""
 node: "WorkflowNode"
 incoming: set[str] = field(default_factory=set) # 入边的源节点 ID
 outgoing: dict[str, set[str]] = field(default_factory=dict) # {handle: {target_node_ids}}
 @property
 def id(self) -> str:
 return str(self.node.id)
 @property
 def in_degree(self) -> int:
 return len(self.incoming)
class DAG:
 """有向无环图
 用于工作流的拓扑排序和执行调度。
 """
 def __init__(self):
 self.nodes: dict[str, DAGNode] = {}
 self.edges: list["WorkflowEdge"] =
 @classmethod
 def from_workflow(cls, workflow) -> "DAG":
 """从工作流模型构建 DAG"""
 dag = cls
 # 添加所有节点
 for node in workflow.nodes.all:
 dag.nodes[str(node.id)] = DAGNode(node=node)
 # 添加所有边
 for edge in workflow.edges.all:
 source_id = str(edge.source_node_id)
 target_id = str(edge.target_node_id)
 handle = edge.source_handle
 if source_id in dag.nodes and target_id in dag.nodes:
 # 记录入边
 dag.nodes[target_id].incoming.add(source_id)
 # 记录出边
 if handle not in dag.nodes[source_id].outgoing:
 dag.nodes[source_id].outgoing[handle] = set
 dag.nodes[source_id].outgoing[handle].add(target_id)
 dag.edges.append(edge)
 return dag
 def validate(self) -> list[str]:
 """验证 DAG 是否有效"""
 errors =
 # 检查是否有环
 if self.has_cycle:
 errors.append("工作流存在循环依赖")
 # 检查是否有入口节点
 entry_nodes = self.get_entry_nodes
 if not entry_nodes:
 errors.append("工作流没有入口节点（触发器）")
 # 检查是否有孤立节点
 for node_id, dag_node in self.nodes.items:
 if dag_node.in_degree == 0 and not dag_node.outgoing:
 if dag_node.node.node_type not in ("manual_trigger", "webhook_trigger"):
 errors.append(f"节点 '{dag_node.node.name}' 是孤立的")
 return errors
 def has_cycle(self) -> bool:
 """检测是否存在环（使用 DFS）"""
 WHITE, GRAY, BLACK = 0, 1, 2
 color = {node_id: WHITE for node_id in self.nodes}
 def dfs(node_id: str) -> bool:
 color[node_id] = GRAY
 dag_node = self.nodes[node_id]
 for targets in dag_node.outgoing.values:
 for target_id in targets:
 if color[target_id] == GRAY:
 return True # 发现回边，存在环
 if color[target_id] == WHITE and dfs(target_id):
 return True
 color[node_id] = BLACK
 return False
 for node_id in self.nodes:
 if color[node_id] == WHITE:
 if dfs(node_id):
 return True
 return False
 def get_entry_nodes(self) -> list[DAGNode]:
 """获取入口节点（入度为 0 的节点）"""
 return [
 dag_node for dag_node in self.nodes.values
 if dag_node.in_degree == 0
 ]
 def get_successors(self, node_id: str, handle: str = "default") -> list[DAGNode]:
 """获取指定节点的后继节点"""
 dag_node = self.nodes.get(node_id)
 if not dag_node:
 return
 successor_ids = dag_node.outgoing.get(handle, set)
 return [self.nodes[sid] for sid in successor_ids if sid in self.nodes]
 def get_all_successors(self, node_id: str) -> list[DAGNode]:
 """获取所有后继节点（所有 handle）"""
 dag_node = self.nodes.get(node_id)
 if not dag_node:
 return
 all_successor_ids = set
 for successor_ids in dag_node.outgoing.values:
 all_successor_ids.update(successor_ids)
 return [self.nodes[sid] for sid in all_successor_ids if sid in self.nodes]
 def topological_sort(self) -> list[DAGNode]:
 """拓扑排序"""
 in_degree = {node_id: dag_node.in_degree for node_id, dag_node in self.nodes.items}
 queue = [node_id for node_id, degree in in_degree.items if degree == 0]
 result =
 while queue:
 node_id = queue.pop(0)
 result.append(self.nodes[node_id])
 for successor in self.get_all_successors(node_id):
 in_degree[successor.id] -= 1
 if in_degree[successor.id] == 0:
 queue.append(successor.id)
 return result
```
### 工作流引擎
```python
# server/workflows/engine/scheduler.py
import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING
import structlog
from django.utils import timezone
from .dag import DAG
from .context import ExecutionContext
from .executor import NodeExecutor
from workflows.models import (
 WorkflowExecution, NodeExecution,
 ExecutionStatus, NodeExecutionStatus,
)
from workflows.nodes.registry import NodeRegistry
from workflows.hooks import HookManager
if TYPE_CHECKING:
 from workflows.models import Workflow, WorkflowNode
logger = structlog.get_logger
class WorkflowEngine:
 """工作流执行引擎
 核心调度器，负责：
 1. 构建 DAG 并验证
 2. 按拓扑顺序调度节点执行
 3. 处理并行执行
 4. 处理审批等阻塞节点
 5. 错误处理和重试
 """
 def __init__(self):
 self.executor = NodeExecutor
 self.hooks = HookManager
 async def start_execution(
 self,
 workflow: "Workflow",
 input_data: dict = None,
 triggered_by=None,
 trigger_type: str = "manual",
 trigger_data: dict = None,
 ) -> WorkflowExecution:
 """启动工作流执行"""
 input_data = input_data or {}
 trigger_data = trigger_data or {}
 # 检查并发限制
 if workflow.max_concurrent_executions > 0:
 running_count = WorkflowExecution.objects.filter(
 workflow=workflow,
 status=ExecutionStatus.RUNNING,
 ).count
 if running_count >= workflow.max_concurrent_executions:
 raise ValueError(
 f"工作流已达到最大并发数 ({workflow.max_concurrent_executions})"
 )
 # 创建执行实例
 execution = await asyncio.to_thread(
 WorkflowExecution.objects.create,
 workflow=workflow,
 status=ExecutionStatus.PENDING,
 trigger_type=trigger_type,
 triggered_by=triggered_by,
 trigger_data=trigger_data,
 input_data=input_data,
 context={
 "workflow_id": str(workflow.id),
 "workflow_name": workflow.name,
 "started_at": timezone.now.isoformat,
 },
 )
 # 构建 DAG
 dag = DAG.from_workflow(workflow)
 errors = dag.validate
 if errors:
 execution.mark_failed("\n".join(errors))
 return execution
 # 初始化节点执行记录
 execution.total_nodes = len(dag.nodes)
 await asyncio.to_thread(
 execution.save,
 update_fields=["total_nodes"],
 )
 for dag_node in dag.nodes.values:
 await asyncio.to_thread(
 NodeExecution.objects.create,
 workflow_execution=execution,
 node=dag_node.node,
 status=NodeExecutionStatus.PENDING,
 )
 # 触发开始钩子
 await self.hooks.trigger("execution_started", execution=execution)
 # 开始执行
 asyncio.create_task(self._run_execution(execution, dag, input_data))
 return execution
 async def _run_execution(
 self,
 execution: WorkflowExecution,
 dag: DAG,
 input_data: dict,
 ):
 """执行工作流主循环"""
 try:
 execution.mark_started
 await self.hooks.trigger("execution_running", execution=execution)
 # 节点输出缓存
 node_outputs: dict[str, dict] = {}
 # 节点完成状态
 completed_nodes: set[str] = set
 failed_nodes: set[str] = set
 skipped_nodes: set[str] = set
 # 待处理节点
 pending_nodes = set(dag.nodes.keys)
 # 入口节点的输入数据
 entry_inputs = {
 dag_node.id: input_data
 for dag_node in dag.get_entry_nodes
 }
 while pending_nodes:
 # 找出可以执行的节点（所有前置已完成）
 ready_nodes =
 for node_id in pending_nodes:
 dag_node = dag.nodes[node_id]
 # 检查所有前置节点是否完成
 all_deps_completed = all(
 dep_id in completed_nodes or dep_id in skipped_nodes
 for dep_id in dag_node.incoming
 )
 # 检查是否有前置失败（需要跳过）
 any_dep_failed = any(
 dep_id in failed_nodes
 for dep_id in dag_node.incoming
 )
 if any_dep_failed:
 # 前置失败，跳过此节点
 await self._skip_node(execution, dag_node, "前置节点失败")
 skipped_nodes.add(node_id)
 pending_nodes.remove(node_id)
 continue
 if all_deps_completed:
 ready_nodes.append(dag_node)
 if not ready_nodes:
 # 检查是否有正在等待审批的节点
 waiting_nodes = await asyncio.to_thread(
 lambda: list(NodeExecution.objects.filter(
 workflow_execution=execution,
 status=NodeExecutionStatus.WAITING_APPROVAL,
 ))
 )
 if waiting_nodes:
 # 有节点在等待审批，等待状态变化
 await asyncio.sleep(5)
 # 刷新状态
 for ne in waiting_nodes:
 await asyncio.to_thread(ne.refresh_from_db)
 if ne.status == NodeExecutionStatus.COMPLETED:
 completed_nodes.add(str(ne.node_id))
 node_outputs[str(ne.node_id)] = ne.output_data
 pending_nodes.discard(str(ne.node_id))
 elif ne.status == NodeExecutionStatus.FAILED:
 failed_nodes.add(str(ne.node_id))
 pending_nodes.discard(str(ne.node_id))
 continue
 else:
 # 死锁检测
 logger.error(
 "workflow_deadlock",
 execution_id=str(execution.id),
 pending_nodes=list(pending_nodes),
 )
 break
 # 并行执行就绪节点
 tasks =
 for dag_node in ready_nodes:
 # 收集输入数据
 if dag_node.id in entry_inputs:
 node_input = entry_inputs[dag_node.id]
 else:
 node_input = self._collect_inputs(dag_node, dag, node_outputs)
 tasks.append(self._execute_node(
 execution, dag_node, node_input, node_outputs
 ))
 pending_nodes.remove(dag_node.id)
 results = await asyncio.gather(*tasks, return_exceptions=True)
 # 处理结果
 for dag_node, result in zip(ready_nodes, results):
 if isinstance(result, Exception):
 logger.error(
 "node_execution_exception",
 node_id=dag_node.id,
 error=str(result),
 )
 failed_nodes.add(dag_node.id)
 elif result.get("status") == "completed":
 completed_nodes.add(dag_node.id)
 node_outputs[dag_node.id] = result.get("output", {})
 elif result.get("status") == "waiting_approval":
 # 节点正在等待审批，保持在 pending
 pending_nodes.add(dag_node.id)
 else:
 failed_nodes.add(dag_node.id)
 # 检查超时
 await asyncio.to_thread(execution.refresh_from_db)
 if execution.timeout_at and timezone.now > execution.timeout_at:
 execution.status = ExecutionStatus.TIMEOUT
 await asyncio.to_thread(execution.save, update_fields=["status"])
 await self.hooks.trigger("execution_timeout", execution=execution)
 return
 # 执行完成
 if failed_nodes:
 execution.mark_failed(f"失败节点: {len(failed_nodes)}")
 else:
 # 收集最终输出（终端节点的输出）
 final_output = {}
 for node_id in completed_nodes:
 dag_node = dag.nodes.get(node_id)
 if dag_node and not dag_node.outgoing:
 final_output.update(node_outputs.get(node_id, {}))
 execution.mark_completed(final_output)
 await self.hooks.trigger("execution_completed", execution=execution)
 except Exception as e:
 logger.exception("workflow_execution_error", execution_id=str(execution.id))
 execution.mark_failed(str(e))
 await self.hooks.trigger("execution_failed", execution=execution, error=e)
 async def _execute_node(
 self,
 execution: WorkflowExecution,
 dag_node,
 input_data: dict,
 previous_outputs: dict,
 ) -> dict:
 """执行单个节点"""
 node = dag_node.node
 node_execution = await asyncio.to_thread(
 NodeExecution.objects.get,
 workflow_execution=execution,
 node=node,
 )
 try:
 node_execution.input_data = input_data
 node_execution.mark_started
 await self.hooks.trigger(
 "node_started",
 execution=execution,
 node_execution=node_execution,
 )
 # 获取节点处理器
 node_class = NodeRegistry.get(node.node_type)
 if not node_class:
 raise ValueError(f"未知的节点类型: {node.node_type}")
 # 构建执行上下文
 context = ExecutionContext(
 execution_id=str(execution.id),
 node_id=str(node.id),
 node_config=node.config,
 input_data=input_data,
 workflow_context=execution.context,
 previous_outputs=previous_outputs,
 workflow_execution=execution,
 node_execution=node_execution,
 )
 # 执行节点
 node_instance = node_class
 result = await self.executor.execute(node_instance, context)
 # 处理结果
 if result.status == "completed":
 node_execution.mark_completed(result.output)
 await self.hooks.trigger(
 "node_completed",
 execution=execution,
 node_execution=node_execution,
 )
 return {"status": "completed", "output": result.output, "handle": result.next_handle}
 elif result.status == "waiting_approval":
 node_execution.mark_waiting_approval(result.output)
 await self.hooks.trigger(
 "node_waiting_approval",
 execution=execution,
 node_execution=node_execution,
 )
 return {"status": "waiting_approval"}
 else:
 node_execution.mark_failed(result.error or "未知错误")
 await self.hooks.trigger(
 "node_failed",
 execution=execution,
 node_execution=node_execution,
 )
 return {"status": "failed", "error": result.error}
 except Exception as e:
 logger.exception(
 "node_execution_error",
 node_id=str(node.id),
 execution_id=str(execution.id),
 )
 node_execution.mark_failed(str(e))
 await self.hooks.trigger(
 "node_failed",
 execution=execution,
 node_execution=node_execution,
 error=e,
 )
 return {"status": "failed", "error": str(e)}
 def _collect_inputs(
 self,
 dag_node,
 dag: DAG,
 node_outputs: dict,
 ) -> dict:
 """收集节点的输入数据（从上游节点输出）"""
 inputs = {}
 for source_id in dag_node.incoming:
 if source_id in node_outputs:
 # 合并上游输出到输入
 inputs.update(node_outputs[source_id])
 return inputs
 async def _skip_node(self, execution: WorkflowExecution, dag_node, reason: str):
 """跳过节点"""
 node_execution = await asyncio.to_thread(
 NodeExecution.objects.get,
 workflow_execution=execution,
 node=dag_node.node,
 )
 node_execution.mark_skipped(reason)
 await self.hooks.trigger(
 "node_skipped",
 execution=execution,
 node_execution=node_execution,
 )
 async def pause_execution(self, execution: WorkflowExecution):
 """暂停执行"""
 if execution.status != ExecutionStatus.RUNNING:
 raise ValueError("只能暂停运行中的执行")
 execution.status = ExecutionStatus.PAUSED
 await asyncio.to_thread(execution.save, update_fields=["status"])
 await self.hooks.trigger("execution_paused", execution=execution)
 async def resume_execution(self, execution: WorkflowExecution):
 """恢复执行"""
 if execution.status != ExecutionStatus.PAUSED:
 raise ValueError("只能恢复已暂停的执行")
 execution.status = ExecutionStatus.RUNNING
 await asyncio.to_thread(execution.save, update_fields=["status"])
 await self.hooks.trigger("execution_resumed", execution=execution)
 # TODO: 重新启动执行循环
 async def cancel_execution(self, execution: WorkflowExecution):
 """取消执行"""
 if execution.status in (ExecutionStatus.COMPLETED, ExecutionStatus.CANCELLED):
 raise ValueError("执行已完成或已取消")
 execution.status = ExecutionStatus.CANCELLED
 execution.completed_at = timezone.now
 await asyncio.to_thread(
 execution.save,
 update_fields=["status", "completed_at"],
 )
 # 取消所有运行中的节点
 running_nodes = await asyncio.to_thread(
 lambda: list(NodeExecution.objects.filter(
 workflow_execution=execution,
 status__in=[NodeExecutionStatus.RUNNING, NodeExecutionStatus.QUEUED],
 ))
 )
 for node_exec in running_nodes:
 node_exec.status = NodeExecutionStatus.CANCELLED
 await asyncio.to_thread(node_exec.save, update_fields=["status"])
 await self.hooks.trigger("execution_cancelled", execution=execution)
 async def approve_node(
 self,
 node_execution: NodeExecution,
 approver,
 comment: str = "",
 ):
 """审批通过节点"""
 if node_execution.status != NodeExecutionStatus.WAITING_APPROVAL:
 raise ValueError("节点不在等待审批状态")
 node_execution.approve(approver, comment)
 node_execution.mark_completed(node_execution.approval_data)
 await self.hooks.trigger(
 "node_approved",
 execution=node_execution.workflow_execution,
 node_execution=node_execution,
 approver=approver,
 )
 async def reject_node(
 self,
 node_execution: NodeExecution,
 approver,
 comment: str = "",
 ):
 """审批拒绝节点"""
 if node_execution.status != NodeExecutionStatus.WAITING_APPROVAL:
 raise ValueError("节点不在等待审批状态")
 node_execution.reject(approver, comment)
 await self.hooks.trigger(
 "node_rejected",
 execution=node_execution.workflow_execution,
 node_execution=node_execution,
 approver=approver,
 )
```
---
## 扩展点设计
### 生命周期钩子
```python
# server/workflows/hooks/base.py
from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine
import structlog
logger = structlog.get_logger
class BaseHook(ABC):
 """钩子基类"""
 # 钩子优先级（数字越小越先执行）
 priority: int = 100
 @abstractmethod
 async def execute(self, event: str, **kwargs) -> None:
 """执行钩子"""
 pass
class HookManager:
 """钩子管理器"""
 # 支持的事件
 EVENTS = [
 "execution_started",
 "execution_running",
 "execution_completed",
 "execution_failed",
 "execution_paused",
 "execution_resumed",
 "execution_cancelled",
 "execution_timeout",
 "node_started",
 "node_completed",
 "node_failed",
 "node_skipped",
 "node_waiting_approval",
 "node_approved",
 "node_rejected",
 ]
 def __init__(self):
 self._hooks: dict[str, list[BaseHook]] = {event: for event in self.EVENTS}
 self._callbacks: dict[str, list[Callable]] = {event: for event in self.EVENTS}
 def register_hook(self, event: str, hook: BaseHook):
 """注册钩子"""
 if event not in self._hooks:
 raise ValueError(f"未知事件: {event}")
 self._hooks[event].append(hook)
 self._hooks[event].sort(key=lambda h: h.priority)
 def register_callback(self, event: str, callback: Callable):
 """注册回调函数"""
 if event not in self._callbacks:
 raise ValueError(f"未知事件: {event}")
 self._callbacks[event].append(callback)
 async def trigger(self, event: str, **kwargs):
 """触发事件"""
 if event not in self._hooks:
 return
 # 执行钩子
 for hook in self._hooks[event]:
 try:
 await hook.execute(event, **kwargs)
 except Exception as e:
 logger.error(
 "hook_execution_error",
 event=event,
 hook=hook.__class__.__name__,
 error=str(e),
 )
 # 执行回调
 for callback in self._callbacks[event]:
 try:
 result = callback(event, **kwargs)
 if asyncio.iscoroutine(result):
 await result
 except Exception as e:
 logger.error(
 "callback_execution_error",
 event=event,
 error=str(e),
 )
```
### 内置钩子
```python
# server/workflows/hooks/builtin.py
import structlog
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .base import BaseHook
logger = structlog.get_logger
class LoggingHook(BaseHook):
 """日志钩子"""
 priority = 1 # 最先执行
 async def execute(self, event: str, **kwargs):
 execution = kwargs.get("execution")
 node_execution = kwargs.get("node_execution")
 log_data = {"event": event}
 if execution:
 log_data["execution_id"] = str(execution.id)
 log_data["workflow"] = execution.workflow.name
 if node_execution:
 log_data["node_id"] = str(node_execution.node.id)
 log_data["node_name"] = node_execution.node.name
 logger.info("workflow_event", **log_data)
class WebSocketBroadcastHook(BaseHook):
 """WebSocket 广播钩子"""
 priority = 10
 async def execute(self, event: str, **kwargs):
 execution = kwargs.get("execution")
 if not execution:
 return
 channel_layer = get_channel_layer
 if not channel_layer:
 return
 message = {
 "type": "workflow.event",
 "event": event,
 "execution_id": str(execution.id),
 "status": execution.status,
 }
 node_execution = kwargs.get("node_execution")
 if node_execution:
 message["node_id"] = str(node_execution.node.id)
 message["node_status"] = node_execution.status
 await channel_layer.group_send(
 f"execution_{execution.id}",
 message,
 )
class NotificationHook(BaseHook):
 """通知钩子"""
 priority = 50
 NOTIFY_EVENTS = [
 "execution_completed",
 "execution_failed",
 "node_waiting_approval",
 ]
 async def execute(self, event: str, **kwargs):
 if event not in self.NOTIFY_EVENTS:
 return
 execution = kwargs.get("execution")
 if not execution:
 return
 # TODO: 实现通知发送逻辑
 # 可以调用飞书、邮件等通知服务
 pass
```
### Webhook 配置模型
```python
# server/workflows/models/webhook.py
import uuid
import hashlib
import hmac
from django.db import models
class WebhookConfig(models.Model):
 """Webhook 配置
 用于配置外部系统回调 Friday 的 webhook。
 """
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 workflow = models.ForeignKey(
 "workflows.Workflow",
 on_delete=models.CASCADE,
 related_name="webhook_configs",
 )
 name = models.CharField(max_length=200, verbose_name="名称")
 description = models.TextField(blank=True, default="")
 # Webhook 路径（自动生成或自定义）
 path = models.CharField(
 max_length=100,
 unique=True,
 verbose_name="路径",
 help_text="Webhook URL 的路径部分",
 )
 # 安全配置
 secret = models.CharField(
 max_length=200,
 blank=True,
 default="",
 verbose_name="签名密钥",
 )
 allowed_ips = models.JSONField(
 default=list,
 blank=True,
 verbose_name="允许的 IP",
 )
 # 状态
 is_active = models.BooleanField(default=True)
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "workflow_webhook_configs"
 verbose_name = "Webhook 配置"
 verbose_name_plural = "Webhook 配置"
 def __str__(self):
 return f"{self.name} ({self.workflow.name})"
 def get_full_url(self) -> str:
 """获取完整的 webhook URL"""
 from django.conf import settings
 base_url = getattr(settings, "FRIDAY_BASE_URL", "http://localhost:8000")
 return f"{base_url}/api/workflows/webhooks/{self.path}/"
 def verify_signature(self, payload: bytes, signature: str) -> bool:
 """验证请求签名"""
 if not self.secret:
 return True
 expected = hmac.new(
 self.secret.encode,
 payload,
 hashlib.sha256,
 ).hexdigest
 return hmac.compare_digest(f"sha256={expected}", signature)
class WebhookLog(models.Model):
 """Webhook 调用日志"""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 webhook_config = models.ForeignKey(
 WebhookConfig,
 on_delete=models.CASCADE,
 related_name="logs",
 )
 # 请求信息
 request_method = models.CharField(max_length=10)
 request_headers = models.JSONField(default=dict)
 request_body = models.TextField(blank=True, default="")
 request_ip = models.GenericIPAddressField(null=True, blank=True)
 # 响应信息
 response_status = models.IntegerField(null=True, blank=True)
 response_body = models.TextField(blank=True, default="")
 # 关联的执行
 execution = models.ForeignKey(
 "workflows.WorkflowExecution",
 on_delete=models.SET_NULL,
 null=True,
 blank=True,
 related_name="webhook_logs",
 )
 # 状态
 success = models.BooleanField(default=False)
 error_message = models.TextField(blank=True, default="")
 created_at = models.DateTimeField(auto_now_add=True)
 class Meta:
 db_table = "workflow_webhook_logs"
 verbose_name = "Webhook 日志"
 verbose_name_plural = "Webhook 日志"
 ordering = ["-created_at"]
```
---
## API 设计
### URL 结构
```python
# server/workflows/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
router = DefaultRouter
router.register(r"workflows", views.WorkflowViewSet, basename="workflow")
router.register(r"executions", views.WorkflowExecutionViewSet, basename="execution")
router.register(r"node-types", views.NodeTypeViewSet, basename="node-type")
urlpatterns = [
 path("", include(router.urls)),
 # Webhook 端点
 path(
 "webhooks/<str:path>/",
 views.WebhookTriggerView.as_view,
 name="webhook-trigger",
 ),
 # 回调端点（供外部系统回调）
 path(
 "callbacks/<uuid:execution_id>/<uuid:node_id>/",
 views.NodeCallbackView.as_view,
 name="node-callback",
 ),
 # 节点操作
 path(
 "executions/<uuid:execution_id>/nodes/<uuid:node_id>/approve/",
 views.NodeApproveView.as_view,
 name="node-approve",
 ),
 path(
 "executions/<uuid:execution_id>/nodes/<uuid:node_id>/reject/",
 views.NodeRejectView.as_view,
 name="node-reject",
 ),
]
```
### API 端点详情
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/workflows/` | GET | 列表（支持 project 过滤） |
| `/api/workflows/` | POST | 创建工作流 |
| `/api/workflows/{id}/` | GET | 获取详情（含节点和边） |
| `/api/workflows/{id}/` | PUT/PATCH | 更新工作流 |
| `/api/workflows/{id}/` | DELETE | 删除工作流 |
| `/api/workflows/{id}/execute/` | POST | 触发执行 |
| `/api/workflows/{id}/duplicate/` | POST | 复制工作流 |
| `/api/workflows/{id}/export/` | GET | 导出 JSON |
| `/api/workflows/import/` | POST | 导入 JSON |
| `/api/executions/` | GET | 执行历史 |
| `/api/executions/{id}/` | GET | 执行详情（含节点状态） |
| `/api/executions/{id}/pause/` | POST | 暂停 |
| `/api/executions/{id}/resume/` | POST | 恢复 |
| `/api/executions/{id}/cancel/` | POST | 取消 |
| `/api/node-types/` | GET | 获取所有节点类型 |
| `/api/webhooks/{path}/` | POST/GET | Webhook 入口 |
| `/api/callbacks/{exec_id}/{node_id}/` | POST | 外部回调 |
---
## 版本兼容策略
### 节点配置版本化
```python
# 节点配置 schema 版本
class BaseNode:
 config_schema = {
 "$schema": "https://json-schema.org/draft/2020-12/schema",
 "$id": "friday://workflow-nodes/http_request/v1",
 "version": "1.0.0",
 # ...
 }
 @classmethod
 def migrate_config(cls, config: dict, from_version: str) -> dict:
 """配置迁移方法
 子类可覆盖实现配置升级逻辑。
 """
 return config
```
### API 版本化
```python
# 未来版本可通过 URL 前缀区分
# /api/v1/workflows/
# /api/v2/workflows/
```
### 数据库迁移策略
- 使用 Django migrations 管理 schema 变更
- 重大变更前导出数据备份
- 提供迁移脚本处理数据格式变化
---
## 安全考虑
1. **Webhook 签名验证**: 使用 work item 验证请求来源
2. **权限控制**: 基于 Django 权限系统，细粒度控制工作流访问
3. **敏感数据加密**: 节点配置中的密钥等敏感信息加密存储
4. **执行沙箱**: Docker 容器隔离执行环境
5. **速率限制**: API 和 Webhook 端点的请求频率限制
6. **审计日志**: 记录所有操作和执行历史
---
## Migration Plan
### Phase: 基础框架（2 周）
1. 创建 `workflows` Django App
2. 实现完整数据模型
3. 实现 DAG 构建器和验证
4. 实现基础执行引擎
5. 实现 3 个核心节点: `manual_trigger`, `http_request`, `human_approval`
### Phase: API 和前端（2 周）
1. 实现完整 REST API
2. 集成 Vue Flow 编辑器
3. 实现节点拖拽和连接
4. 实现工作流保存/加载
### Phase: 扩展节点（2 周）
1. Git 操作节点
2. AI 分析/代码实现节点
3. 条件分支节点
4. 通知集成节点
### Phase: 高级功能（2 周）
1. WebSocket 实时状态
2. Webhook 触发器
3. 外部回调机制
4. 执行历史和监控
### Rollback
- 新功能通过 feature flag 控制
- 现有 Task 功能完全保留
- 数据库使用独立表，不影响现有数据
