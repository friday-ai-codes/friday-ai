"""System app configuration."""
from django.apps import AppConfig
class SystemConfig(AppConfig):
 """System app configuration."""
 default_auto_field = "django.db.models.BigAutoField"
 name = "system"
 verbose_name = "系统设置"
