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
 NodeRegistry._ensure_initialized
 # 连接子步骤状态变更 signal → WebSocket 广播 handler
 from workflows.signal_handlers import handle_sub_step_updated
 from workflows.signals import sub_step_updated
 sub_step_updated.connect(handle_sub_step_updated)
