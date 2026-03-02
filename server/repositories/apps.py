"""Repositories app configuration."""
import threading
import structlog
from django.apps import AppConfig
logger = structlog.get_logger(__name__)
class RepositoriesConfig(AppConfig):
 """Repositories app configuration."""
 default_auto_field = "django.db.models.BigAutoField"
 name = "repositories"
 verbose_name = "仓库管理"
 def ready(self) -> None:
 """Reset stuck indexing status on startup."""
 # Run in a separate thread to avoid "SynchronousOnlyOperation" error
 # when the ASGI server's event loop is already running.
 thread = threading.Thread(target=self._reset_stuck_indexing, daemon=True)
 thread.start
 thread.join(timeout=5)
 @staticmethod
 def _reset_stuck_indexing -> None:
 try:
 from repositories.models import IndexStatus, Repository
 stuck_count = Repository.objects.filter(index_status=IndexStatus.INDEXING).update(
 index_status=IndexStatus.FAILED,
 index_error="索引任务因服务重启而中断，请重新开始索引",
 )
 if stuck_count > 0:
 logger.info(
 "reset_stuck_indexing_status",
 count=stuck_count,
 message=f"Reset {stuck_count} repositories from INDEXING to FAILED state",
 )
 except Exception as e:
 logger.debug("skip_reset_indexing_status", reason=str(e))
