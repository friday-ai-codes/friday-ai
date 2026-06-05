"""Chat app configuration."""

from django.apps import AppConfig


class ChatConfig(AppConfig):
    """Chat app configuration."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "chat"
    verbose_name = "对话服务"
