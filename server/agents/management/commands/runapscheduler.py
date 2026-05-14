"""Django management command to run the APScheduler.
Starts the background scheduler for session timeout tasks:
- check_timeout_reminders: Every hour
- cleanup_expired_sessions: Daily at 3:00 AM
- refresh_repo_caches: Daily at 2:00 AM (Phase)
- prune_cache_volumes: Daily at 5:00 AM (Phase)
- cleanup_orchestration_checkpoints: Daily at 3:30 UTC (Phase)
- backfill_chunk_edges: One-shot at scheduler startup (Phase ½)
"""
import asyncio
import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from django_apscheduler import util
from django_apscheduler.jobstores import DjangoJobStore
from django_apscheduler.models import DjangoJobExecution
logger = structlog.get_logger(__name__)
def run_async_task(coro_func):
 """Wrapper to run async task in sync context."""
 try:
 loop = asyncio.get_event_loop
 if loop.is_running:
 # Create a new loop in a thread if current is running
 import concurrent.futures
 with concurrent.futures.ThreadPoolExecutor as pool:
 future = pool.submit(asyncio.run, coro_func)
 return future.result
 else:
 return loop.run_until_complete(coro_func)
 except RuntimeError:
 # No event loop, create one
 return asyncio.run(coro_func)
def check_timeout_reminders_job:
 """Job wrapper for check_timeout_reminders task."""
 from tasks.session_timeout_tasks import check_timeout_reminders
 log = logger.bind(job="check_timeout_reminders")
 log.info("job_start")
 try:
 result = run_async_task(check_timeout_reminders)
 log.info("job_complete", result=result)
 except Exception as e:
 log.exception("job_error", error=str(e))
def cleanup_expired_sessions_job:
 """Job wrapper for cleanup_expired_sessions task."""
 from tasks.session_timeout_tasks import cleanup_expired_sessions
 log = logger.bind(job="cleanup_expired_sessions")
 log.info("job_start")
 try:
 result = run_async_task(cleanup_expired_sessions)
 log.info("job_complete", result=result)
 except Exception as e:
 log.exception("job_error", error=str(e))
@util.close_old_connections
def delete_old_job_executions(max_age: int = 604_800):
 """Delete job execution logs older than max_age seconds (default: 7 days)."""
 DjangoJobExecution.objects.delete_old_job_executions(max_age)
 logger.info("old_job_executions_deleted", max_age_seconds=max_age)
def refresh_repo_caches_job:
 """Job wrapper for refresh_repo_caches task (Phase)."""
 from tasks.cache_tasks import refresh_repo_caches
 log = logger.bind(job="refresh_repo_caches")
 log.info("job_start")
 try:
 result = run_async_task(refresh_repo_caches)
 log.info("job_complete", result=result)
 except Exception as e:
 log.exception("job_error", error=str(e))
def prune_cache_volumes_job:
 """Job wrapper for prune_cache_volumes task (Phase)."""
 from tasks.cache_tasks import prune_cache_volumes
 log = logger.bind(job="prune_cache_volumes")
 log.info("job_start")
 try:
 result = run_async_task(prune_cache_volumes)
 log.info("job_complete", result=result)
 except Exception as e:
 log.exception("job_error", error=str(e))
def poll_repository_updates_job:
 """Job wrapper for poll_repository_updates task (Phase)."""
 from tasks.index_trigger_tasks import poll_repository_updates
 log = logger.bind(job="poll_repository_updates")
 log.info("job_start")
 try:
 result = run_async_task(poll_repository_updates)
 log.info("job_complete", result=result)
 except Exception as e:
 log.exception("job_error", error=str(e))
def calculate_behind_commits_job -> None:
 """：计算 STALE 仓库的 behind_commits 差值并缓存。"""
 from repositories.freshness_service import update_behind_commits_for_stale_repos
 log = logger.bind(job="calculate_behind_commits")
 log.info("job_start")
 try:
 run_async_task(update_behind_commits_for_stale_repos)
 log.info("job_complete")
 except Exception as e:
 log.exception("job_error", error=str(e))
def cleanup_stale_branch_indexes_job:
 """Job wrapper for cleanup_stale_branch_indexes (Phase)."""
 from tasks.index_trigger_tasks import cleanup_stale_branch_indexes
 log = logger.bind(job="cleanup_stale_branch_indexes")
 log.info("job_start")
 try:
 result = run_async_task(cleanup_stale_branch_indexes)
 log.info("job_complete", result=result)
 except Exception as e:
 log.exception("job_error", error=str(e))
def cleanup_orchestration_checkpoints_job:
 """Job wrapper for cleanup_orchestration_checkpoints command (Phase).
 与其他 *_job 的差异：
 - 不用 run_async_task 包装（cleanup command 内部已 asyncio.run）
 - 通过 call_command 调 management command（而非 tasks.* 的异步函数）
 """
 from django.core.management import call_command
 log = logger.bind(job="cleanup_orchestration_checkpoints")
 log.info("job_start")
 try:
 call_command("cleanup_orchestration_checkpoints")
 log.info("job_complete")
 except Exception as e:
 log.exception("job_error", error=str(e))
def backfill_chunk_edges_job -> None:
 """Phase：scheduler 启动时一次性扫所有 INDEXED 仓库 backfill ChunkEdge.
 DateTrigger(run_date=now) 单次任务模式：跑完即结束，不周期重复（per CONTEXT
 Claude Discretion，避免 IntervalTrigger 浪费资源）；失败下次 scheduler
 启动 DjangoJobStore 持久化自动重试（job_state 仍在 DB）。
 与 ``cleanup_orchestration_checkpoints_job`` 同 ``call_command`` 模式（不走
 ``run_async_task`` 包装——``rebuild_chunk_edges`` 命令内部已 ``asyncio.run``）；
 单 repo dispatch 失败由命令自身吞掉 + ``stderr`` 提示 + 跳过 last_built_at 更新
 （Phase Plan 容错语义），不会冒泡到本 wrapper。
 """
 from django.core.management import call_command
 log = logger.bind(job="backfill_chunk_edges")
 log.info("job_start")
 try:
 call_command("rebuild_chunk_edges", all=True)
 log.info("job_complete")
 except Exception as e:
 log.exception("job_error", error=str(e))
class Command(BaseCommand):
 help = "Runs APScheduler for session timeout tasks."
 def handle(self, *args, **options):
 scheduler = BackgroundScheduler(timezone=settings.TIME_ZONE)
 scheduler.add_jobstore(DjangoJobStore, "default")
 # Check timeout reminders every hour
 scheduler.add_job(
 check_timeout_reminders_job,
 trigger=IntervalTrigger(hours=1),
 id="check_timeout_reminders",
 name="Check timeout reminders for suspended sessions",
 max_instances=1,
 replace_existing=True,
 )
 logger.info("job_registered", job="check_timeout_reminders", schedule="every 1 hour")
 # Cleanup expired sessions daily at 3:00 AM
 scheduler.add_job(
 cleanup_expired_sessions_job,
 trigger=CronTrigger(hour=3, minute=0),
 id="cleanup_expired_sessions",
 name="Cleanup sessions suspended > 30 days",
 max_instances=1,
 replace_existing=True,
 )
 logger.info("job_registered", job="cleanup_expired_sessions", schedule="daily at 03:00")
 # Cleanup orchestration checkpoints daily at 3:30 UTC (Phase)
 # 选 3:30 而非 3:00 避免与 cleanup_expired_sessions 争 SQLite 写锁（Claude's Discretion）
 scheduler.add_job(
 cleanup_orchestration_checkpoints_job,
 trigger=CronTrigger(hour=3, minute=30),
 id="cleanup_orchestration_checkpoints",
 name="Cleanup orchestration checkpoints older than 7 days",
 max_instances=1,
 replace_existing=True,
 )
 logger.info(
 "job_registered",
 job="cleanup_orchestration_checkpoints",
 schedule="daily at 03:30",
 )
 # Delete old job executions weekly
 scheduler.add_job(
 delete_old_job_executions,
 trigger=CronTrigger(day_of_week="mon", hour=0, minute=0),
 id="delete_old_job_executions",
 name="Delete old job execution logs",
 max_instances=1,
 replace_existing=True,
 )
 logger.info("job_registered", job="delete_old_job_executions", schedule="weekly on Monday")
 # Refresh repository caches daily at 2:00 AM (Phase)
 scheduler.add_job(
 refresh_repo_caches_job,
 trigger=CronTrigger(hour=2, minute=0),
 id="refresh_repo_caches",
 name="Refresh repository caches",
 max_instances=1,
 replace_existing=True,
 )
 logger.info("job_registered", job="refresh_repo_caches", schedule="daily at 02:00")
 # Prune cache volumes daily at 5:00 AM (Phase)
 scheduler.add_job(
 prune_cache_volumes_job,
 trigger=CronTrigger(hour=5, minute=0),
 id="prune_cache_volumes",
 name="Prune unused cache volumes",
 max_instances=1,
 replace_existing=True,
 )
 logger.info("job_registered", job="prune_cache_volumes", schedule="daily at 05:00")
 # Poll repository updates every N seconds (Phase，间隔由 settings.SYNC_INTERVAL_SECONDS 统一管理)
 scheduler.add_job(
 poll_repository_updates_job,
 trigger=IntervalTrigger(seconds=settings.SYNC_INTERVAL_SECONDS),
 id="poll_repository_updates",
 name="Poll for repository updates via git ls-remote",
 max_instances=1,
 replace_existing=True,
 )
 # Deploy 注意（ Pitfall 4）：首次部署新代码前，在生产 SQLite 上执行：
 # DELETE FROM django_apscheduler_djangojob WHERE id='poll_repository_updates';
 # 启动新代码后 scheduler 会自动重建，避免旧 job_state 残留旧 trigger。
 logger.info("job_registered", job="poll_repository_updates", schedule=f"every {settings.SYNC_INTERVAL_SECONDS}s")
 # 计算 STALE 仓库 behind_commits 差值，串联 poll_repository_updates（Phase）
 scheduler.add_job(
 calculate_behind_commits_job,
 trigger=IntervalTrigger(seconds=settings.SYNC_INTERVAL_SECONDS),
 id="calculate_behind_commits",
 name="Calculate behind commits for stale repositories",
 max_instances=1,
 replace_existing=True,
 )
 logger.info(
 "job_registered",
 job="calculate_behind_commits",
 schedule="every 2 hours",
 )
 scheduler.add_job(
 cleanup_stale_branch_indexes_job,
 trigger=IntervalTrigger(hours=1),
 id="cleanup_stale_branch_indexes",
 name="Cleanup orphaned branch overlays via git ls-remote",
 max_instances=1,
 replace_existing=True,
 )
 logger.info(
 "job_registered",
 job="cleanup_stale_branch_indexes",
 schedule="every 1 hour",
 )
 # Phase ½：scheduler 启动后一次性 backfill ChunkEdge（老仓库
 # v23.0 索引完无 ChunkEdge）。DateTrigger 单次 trigger 跑完即结束；与 v23.0
 # IntervalTrigger poll_repository_updates / calculate_behind_commits 共存。
 #
 # 修复（Phase REVIEW）：必须传 timezone-aware datetime；裸
 # ``datetime.now`` 是 naive，APScheduler 会按 scheduler tz
 # (``Asia/Shanghai``) 解释，但 UTC 容器（生产常见 Docker/K8s 默认 UTC）
 # 实际系统时间已是 UTC，naive 解释成 +08:00 = **早 8 小时**，落入
 # ``misfire_grace_time`` 窗口外被丢弃 → Phase ½ 整个机制
 # 在 UTC 部署下失效。``django.utils.timezone.now`` 返回 aware datetime
 # (USE_TZ=True，与项目惯例一致)，APScheduler 直接按其携带 tz 解释。
 # 同时显式 ``misfire_grace_time=3600`` 兜底 scheduler 启动慢场景。
 scheduler.add_job(
 backfill_chunk_edges_job,
 trigger=DateTrigger(run_date=timezone.now),
 id="backfill_chunk_edges",
 name="Phase: one-shot backfill ChunkEdge for legacy repositories",
 max_instances=1,
 replace_existing=True,
 misfire_grace_time=3600,
 )
 logger.info(
 "job_registered",
 job="backfill_chunk_edges",
 schedule="one-shot at scheduler startup (DateTrigger)",
 )
 try:
 logger.info("scheduler_starting")
 scheduler.start
 self.stdout.write(self.style.SUCCESS("Scheduler started. Press Ctrl+C to exit."))
 # Keep the main thread alive
 import time
 while True:
 time.sleep(1)
 except KeyboardInterrupt:
 logger.info("scheduler_shutdown_requested")
 scheduler.shutdown
 self.stdout.write(self.style.SUCCESS("Scheduler shut down successfully."))
