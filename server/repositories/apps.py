"""Repositories app configuration."""
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
 # Avoid running during migrations or when not fully initialized
 try:
 from repositories.models import IndexStatus, Repository
 # Reset any repositories stuck in "indexing" state
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
 # Silently ignore errors during startup (e.g., database not ready)
 logger.debug("skip_reset_indexing_status", reason=str(e))
