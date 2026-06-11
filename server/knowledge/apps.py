"""交付知识图谱 App 配置。"""

from django.apps import AppConfig


class KnowledgeConfig(AppConfig):
    """knowledge 交付知识图谱（实体 / 版本链 / bi-temporal 边）数据持久化 App。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "knowledge"
    verbose_name = "交付知识图谱"
