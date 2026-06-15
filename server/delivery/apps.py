"""delivery app 配置：v0.6.0 操作态交付脊柱。"""

from django.apps import AppConfig


class DeliveryConfig(AppConfig):
    """交付脊柱 app 配置。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "delivery"
    verbose_name = "交付脊柱"
