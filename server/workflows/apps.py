"""Workflows app configuration."""
from django.apps import AppConfig
class WorkflowsConfig(AppConfig):
 """Workflows app config."""
 default_auto_field = "django.db.models.BigAutoField"
 name = "workflows"
 verbose_name = "工作流"
 def ready(self):
 """Initialize app when ready."""
 # 自动发现并注册节点类型
 from workflows.nodes.registry import NodeRegistry
 NodeRegistry._ensure_initialized
