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
        # 进程角色门禁（DURABLE-02）：仅 web 进程跑此 web-only 启动副作用，
        # worker/migrate/test 进程短路（记 info 日志），避免误杀在途索引行。
        from durable.roles import should_run_startup_side_effects

        if not should_run_startup_side_effects(job="reset_stuck_indexing"):
            return

        # Run in a separate thread to avoid "SynchronousOnlyOperation" error
        # when the ASGI server's event loop is already running.
        thread = threading.Thread(target=self._reset_stuck_indexing, daemon=True)
        thread.start()
        thread.join(timeout=5)

    @staticmethod
    def _reset_stuck_indexing() -> None:
        try:
            from django.utils import timezone

            from repositories.models import (
                IndexHistory,
                IndexHistoryStatus,
                IndexStatus,
                Repository,
            )

            # 断点恢复：有可恢复 ResumableTask(kind=index) 的仓库交给
            # RecoveryScheduler 自动续跑，不在此无脑标 FAILED（避免与续跑互踩）。
            # 表/应用未就绪时退化为空集合（保持旧行为）。
            recoverable_ids: set[str] = set()
            try:
                from resumable.models import ResumableTaskKind
                from resumable.recovery import recoverable_target_ids

                recoverable_ids = recoverable_target_ids(ResumableTaskKind.INDEX)
            except Exception:
                recoverable_ids = set()

            stuck_qs = Repository.objects.filter(index_status=IndexStatus.INDEXING)
            if recoverable_ids:
                stuck_qs = stuck_qs.exclude(id__in=recoverable_ids)
            stuck_count = stuck_qs.update(
                index_status=IndexStatus.FAILED,
                index_error="索引任务因服务重启而中断，请重新开始索引",
            )
            if stuck_count > 0:
                logger.info(
                    "reset_stuck_indexing_status",
                    count=stuck_count,
                    message=f"Reset {stuck_count} repositories from INDEXING to FAILED state",
                )

            # 同步把孤儿 IndexHistory.RUNNING 标为 FAILED，避免"索引历史"列表里
            # 永远在转圈的僵尸记录（容器更新 / 异常崩溃 / embedding 服务挂等场景）
            stuck_history_count = IndexHistory.objects.filter(
                status=IndexHistoryStatus.RUNNING
            ).update(
                status=IndexHistoryStatus.FAILED,
                finished_at=timezone.now(),
                error_message="索引任务因服务重启而中断，请重新开始索引",
            )
            if stuck_history_count > 0:
                logger.info(
                    "reset_stuck_index_history",
                    count=stuck_history_count,
                    message=(
                        f"Reset {stuck_history_count} IndexHistory rows "
                        f"from RUNNING to FAILED state"
                    ),
                )
        except Exception as e:
            logger.debug("skip_reset_indexing_status", reason=str(e))
