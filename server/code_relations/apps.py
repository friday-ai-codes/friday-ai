"""代码关系图谱 App 配置。"""

from django.apps import AppConfig


class CodeRelationsConfig(AppConfig):
    """code_relations 关系图谱（ChunkRegistry + ChunkEdge）数据持久化 App。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "code_relations"
    verbose_name = "代码关系图谱"

    def ready(self) -> None:
        """initial implementation plan：显式 import signals 触发 @receiver decorator 注册。

        不依赖 Django 自动发现 —— ready() 是 AppConfig 文档明确的 signal 注册时机；
        import 副作用使 `@receiver(pre_delete, sender=ChunkRegistry)` 在 app
        loading 完成后即生效。
        """
        from code_relations import signals  # noqa: F401
