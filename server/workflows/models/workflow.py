"""Workflow model definition."""

import uuid
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.db import models

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from workflows.models.execution import WorkflowExecution
    from workflows.models.node import WorkflowEdge, WorkflowNode
    from workflows.models.trigger import WorkflowTrigger
    from workflows.models.webhook import WebhookConfig

User = get_user_model()


class Workflow(models.Model):
    """工作流模板定义"""

    # 反向关系类型声明（由 ForeignKey 的 related_name 生成）
    nodes: "QuerySet[WorkflowNode]"
    edges: "QuerySet[WorkflowEdge]"
    executions: "QuerySet[WorkflowExecution]"
    triggers: "QuerySet[WorkflowTrigger]"
    webhook_configs: "QuerySet[WebhookConfig]"

    class TriggerType(models.TextChoices):
        # TRIG-02 / D-02：移除僵尸枚举 schedule（无 handler/无画布节点/无 dispatch）。
        # 定时触发改用「外部 cron → 调 webhook」模式（沿用 templates/daily_summary.json
        # 既定口径），不实现原生定时调度，避免用户配出不生效的触发器。
        MANUAL = "manual", "手动触发"
        WEBHOOK = "webhook", "Webhook 触发"
        EVENT = "event", "事件触发"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 基本信息
    name = models.CharField(max_length=200, verbose_name="名称")
    description = models.TextField(blank=True, default="", verbose_name="描述")
    icon = models.CharField(max_length=50, default="workflow", verbose_name="图标")

    # 关联
    space = models.ForeignKey(
        "projects.Space",
        on_delete=models.CASCADE,
        related_name="workflows",
        verbose_name="所属空间",
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
            models.Index(fields=["space", "is_active"]),
            models.Index(fields=["trigger_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.space.name})"

    def clone(self, new_project=None, new_name: str | None = None) -> "Workflow":
        """克隆工作流到另一个项目"""
        new_workflow = Workflow.objects.create(
            name=new_name or f"{self.name} (副本)",
            description=self.description,
            space=new_project or self.space,
            trigger_type=self.trigger_type,
            trigger_config=self.trigger_config.copy(),
            default_timeout=self.default_timeout,
            metadata=self.metadata.copy(),
        )
        # 克隆节点
        node_mapping: dict[uuid.UUID, uuid.UUID] = {}
        for node in self.nodes.all():
            new_node = node.clone(new_workflow)
            node_mapping[node.id] = new_node.id

        # 克隆边（更新节点引用）
        for edge in self.edges.all():
            edge.clone(new_workflow, node_mapping)

        return new_workflow

    async def aclone(self, new_project=None, new_name: str | None = None) -> "Workflow":
        """克隆工作流到另一个项目（async 版本）"""
        from workflows.models.node import WorkflowEdge, WorkflowNode

        new_workflow = await Workflow.objects.acreate(
            name=new_name or f"{self.name} (副本)",
            description=self.description,
            space=new_project or self.space,
            trigger_type=self.trigger_type,
            trigger_config=self.trigger_config.copy(),
            default_timeout=self.default_timeout,
            metadata=self.metadata.copy(),
        )
        # 克隆节点
        node_mapping: dict[uuid.UUID, uuid.UUID] = {}
        async for node in self.nodes.all():
            new_node = await WorkflowNode.objects.acreate(
                workflow=new_workflow,
                node_type=node.node_type,
                name=node.name,
                description=node.description,
                position_x=node.position_x,
                position_y=node.position_y,
                config=node.config.copy() if node.config else {},
            )
            node_mapping[node.id] = new_node.id

        # 克隆边（更新节点引用）
        async for edge in self.edges.all():
            source_id = node_mapping.get(edge.source_node_id)
            target_id = node_mapping.get(edge.target_node_id)
            if source_id and target_id:
                await WorkflowEdge.objects.acreate(
                    workflow=new_workflow,
                    source_node_id=source_id,
                    target_node_id=target_id,
                    source_handle=edge.source_handle,
                    target_handle=edge.target_handle,
                    condition=edge.condition,
                )

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
            "nodes": [node.to_json() for node in self.nodes.all()],
            "edges": [edge.to_json() for edge in self.edges.all()],
        }

    async def ato_json(self) -> dict:
        """导出为 JSON 格式（async 版本）"""
        nodes = [node.to_json() async for node in self.nodes.all()]
        edges = [edge.to_json() async for edge in self.edges.all()]
        return {
            "version": "1.0",
            "workflow": {
                "name": self.name,
                "description": self.description,
                "trigger_type": self.trigger_type,
                "trigger_config": self.trigger_config,
                "default_timeout": self.default_timeout,
            },
            "nodes": nodes,
            "edges": edges,
        }

    @classmethod
    def from_json(cls, data: dict, project, created_by=None) -> "Workflow":
        """从 JSON 导入工作流"""
        from workflows.models.node import WorkflowEdge, WorkflowNode

        workflow_data = data["workflow"]
        workflow = cls.objects.create(
            name=workflow_data["name"],
            description=workflow_data.get("description", ""),
            space=project,
            created_by=created_by,
            trigger_type=workflow_data.get("trigger_type", "manual"),
            trigger_config=workflow_data.get("trigger_config", {}),
            default_timeout=workflow_data.get("default_timeout", 3600),
        )

        # 导入节点
        node_id_mapping: dict[str, str] = {}
        for node_data in data.get("nodes", []):
            old_id = node_data.pop("id", None)
            node = WorkflowNode.objects.create(workflow=workflow, **node_data)
            if old_id:
                node_id_mapping[old_id] = str(node.id)

        # 导入边（映射节点 ID）
        for edge_data in data.get("edges", []):
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

    @classmethod
    async def afrom_json(cls, data: dict, project, created_by=None) -> "Workflow":
        """从 JSON 导入工作流（async 版本）"""
        from workflows.models.node import WorkflowEdge, WorkflowNode

        workflow_data = data["workflow"]
        workflow = await cls.objects.acreate(
            name=workflow_data["name"],
            description=workflow_data.get("description", ""),
            space=project,
            created_by=created_by,
            trigger_type=workflow_data.get("trigger_type", "manual"),
            trigger_config=workflow_data.get("trigger_config", {}),
            default_timeout=workflow_data.get("default_timeout", 3600),
        )

        # 导入节点
        node_id_mapping: dict[str, str] = {}
        for node_data in data.get("nodes", []):
            old_id = node_data.pop("id", None)
            node = await WorkflowNode.objects.acreate(workflow=workflow, **node_data)
            if old_id:
                node_id_mapping[old_id] = str(node.id)

        # 导入边（映射节点 ID）
        for edge_data in data.get("edges", []):
            source_id = node_id_mapping.get(edge_data["source_node_id"])
            target_id = node_id_mapping.get(edge_data["target_node_id"])
            if source_id and target_id:
                await WorkflowEdge.objects.acreate(
                    workflow=workflow,
                    source_node_id=source_id,
                    target_node_id=target_id,
                    source_handle=edge_data.get("source_handle", "default"),
                    target_handle=edge_data.get("target_handle", "default"),
                    condition=edge_data.get("condition"),
                )

        return workflow
