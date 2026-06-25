"""initiatives app 配置：v0.15.0 项目聚合根。"""

from django.apps import AppConfig


class InitiativesConfig(AppConfig):
    """项目聚合根 app 配置。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "initiatives"
    verbose_name = "项目聚合根"
