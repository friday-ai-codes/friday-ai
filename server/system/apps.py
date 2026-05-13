"""System app configuration."""
from django.apps import AppConfig
class SystemConfig(AppConfig):
 """System app configuration."""
 default_auto_field = "django.db.models.BigAutoField"
 name = "system"
 verbose_name = "系统设置"
 def ready(self) -> None:
 # 注册 SystemSetting post_save/post_delete 副作用：
 # 失效 settings cache + 改 qdrant_url/qdrant_api_key 时重建 Qdrant client。
 from . import signals # noqa: F401
