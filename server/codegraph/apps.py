"""代码图谱 App 配置。"""
from django.apps import AppConfig
class CodegraphConfig(AppConfig):
 """codegraph 图谱数据持久化 App。"""
 default_auto_field = "django.db.models.BigAutoField"
 name = "codegraph"
 verbose_name = "代码图谱"
