"""access_tokens app 配置 —— Friday Access Token 生命周期管理。"""

from django.apps import AppConfig


class AccessTokensConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "access_tokens"
    verbose_name = "Access Tokens"
