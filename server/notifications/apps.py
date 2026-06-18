"""notifications app 配置：通用站内信通知中心。"""

from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    """站内信通知 app 配置。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"
    verbose_name = "站内信通知"
