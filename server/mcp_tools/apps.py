"""mcp_tools app 配置。"""

from django.apps import AppConfig


class McpToolsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mcp_tools"
    verbose_name = "MCP Tools"
