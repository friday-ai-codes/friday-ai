"""Permissions app configuration."""

from django.apps import AppConfig


class PermissionsConfig(AppConfig):
    """权限管理应用配置。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "permissions"
    verbose_name = "权限管理"
