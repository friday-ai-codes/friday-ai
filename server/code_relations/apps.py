"""代码关系图谱 App 配置。"""
from django.apps import AppConfig
class CodeRelationsConfig(AppConfig):
 """code_relations 关系图谱（ChunkRegistry + ChunkEdge）数据持久化 App。"""
 default_auto_field = "django.db.models.BigAutoField"
 name = "code_relations"
 verbose_name = "代码关系图谱"
