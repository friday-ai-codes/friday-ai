"""feedback app 配置：用户反馈收集与处理。"""

from django.apps import AppConfig


class FeedbackConfig(AppConfig):
    """用户反馈 app 配置。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "feedback"
    verbose_name = "用户反馈"
