"""audit app 配置：v0.10.0 操作审计横切治理。"""

from django.apps import AppConfig


class AuditConfig(AppConfig):
    """操作审计 app 配置（横切叶子包）。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "audit"
    verbose_name = "操作审计"
