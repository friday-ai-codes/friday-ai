"""Workflows app configuration."""

from django.apps import AppConfig


class WorkflowsConfig(AppConfig):
    """Workflows app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "workflows"
    verbose_name = "工作流"

    def ready(self) -> None:
        """Initialize app when ready."""
        # 自动发现并注册节点类型
        from workflows.nodes.registry import NodeRegistry

        NodeRegistry._ensure_initialized()

        # 连接子步骤状态变更 signal → WebSocket 广播 handler
        from workflows.signal_handlers import handle_sub_step_updated
        from workflows.signals import sub_step_updated

        sub_step_updated.connect(handle_sub_step_updated)

        # Chassis v2 · P4：附着插件 → WorkflowReaction 配置同步（post_save）+ 注册内置
        # reaction 执行器（import 触发 @register_executor 副作用）。
        from django.db.models.signals import post_save

        from workflows.models.workflow import Workflow
        from workflows.reactions import (
            builtin_executors,  # noqa: F401 — 注册 feishu_doc_create/writeback 执行器
        )
        from workflows.reactions.config_sync import on_workflow_saved

        post_save.connect(
            on_workflow_saved,
            sender=Workflow,
            dispatch_uid="workflows.reactions.config_sync.on_workflow_saved",
        )
