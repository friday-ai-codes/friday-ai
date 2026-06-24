"""Django management command to run the APScheduler.

Starts the background scheduler for session timeout tasks:
- check_timeout_reminders: Every hour
- cleanup_expired_sessions: Daily at 3:00 AM
- refresh_repo_caches: Daily at 2:00 AM (Phase)
- prune_cache_volumes: Daily at 5:00 AM (Phase)
- cleanup_orchestration_checkpoints: Daily at 3:30 UTC (implementation contract)
- backfill_chunk_edges: One-shot at scheduler startup (implementation ½)
"""

import asyncio
import functools

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


def _with_scheduler_log_context(func):
    """装饰器：周期任务执行体外层绑定调度器日志上下文（CTX-02）。

    apscheduler 任务在独立线程触发、contextvars 不自动传播：系统周期任务无触发
    用户，统一记 ``user_id="system"`` + ``source="scheduler"`` + ``component=
    "scheduler"``，使任务体内 structlog 事件可归因为系统调度。best-effort，绑定
    失败绝不打断 job 主体（沿用观测代码绝不反噬业务）。
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # 仅保护「构造上下文管理器」这一步；func 仍恰好执行一次，其异常正常上抛
        # （with 退出会清理 contextvars），避免 best-effort 误吞 job 真实错误 /
        # 误致重复执行。
        try:
            from common.log_context import bind_task_context

            cm = bind_task_context(
                user_id="system", source="scheduler", component="scheduler"
            )
        except Exception:  # noqa: BLE001 — bind 不可用则降级为无上下文执行
            cm = None
        if cm is None:
            return func(*args, **kwargs)
        with cm:
            return func(*args, **kwargs)

    return wrapper


def run_async_task(coro_func):
    """Wrapper to run async task in sync context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Create a new loop in a thread if current is running
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro_func())
                return future.result()
        else:
            return loop.run_until_complete(coro_func())
    except RuntimeError:
        # No event loop, create one
        return asyncio.run(coro_func())


@_with_scheduler_log_context
def check_timeout_reminders_job():
    """Job wrapper for check_timeout_reminders task."""
    from tasks.session_timeout_tasks import check_timeout_reminders

    log = logger.bind(job="check_timeout_reminders")
    log.info("job_start")

    try:
        result = run_async_task(check_timeout_reminders)
        log.info("job_complete", result=result)
    except Exception as e:
        log.exception("job_error", error=str(e))


@_with_scheduler_log_context
def cleanup_expired_sessions_job():
    """Job wrapper for cleanup_expired_sessions task."""
    from tasks.session_timeout_tasks import cleanup_expired_sessions

    log = logger.bind(job="cleanup_expired_sessions")
    log.info("job_start")

    try:
        result = run_async_task(cleanup_expired_sessions)
        log.info("job_complete", result=result)
    except Exception as e:
        log.exception("job_error", error=str(e))


@_with_scheduler_log_context
@util.close_old_connections
def delete_old_job_executions(max_age: int = 604_800):
    """Delete job execution logs older than max_age seconds (default: 7 days)."""
    DjangoJobExecution.objects.delete_old_job_executions(max_age)
    logger.info("old_job_executions_deleted", max_age_seconds=max_age)



@_with_scheduler_log_context
def refresh_repo_caches_job():
    """Job wrapper for refresh_repo_caches task (Phase)."""
    from tasks.cache_tasks import refresh_repo_caches

    log = logger.bind(job="refresh_repo_caches")
    log.info("job_start")

    try:
        result = run_async_task(refresh_repo_caches)
        log.info("job_complete", result=result)
    except Exception as e:
        log.exception("job_error", error=str(e))


@_with_scheduler_log_context
def prune_cache_volumes_job():
    """Job wrapper for prune_cache_volumes task (Phase)."""
    from tasks.cache_tasks import prune_cache_volumes

    log = logger.bind(job="prune_cache_volumes")
    log.info("job_start")

    try:
        result = run_async_task(prune_cache_volumes)
        log.info("job_complete", result=result)
    except Exception as e:
        log.exception("job_error", error=str(e))


@_with_scheduler_log_context
def poll_repository_updates_job():
    """Job wrapper for poll_repository_updates task (implementation)."""
    from tasks.index_trigger_tasks import poll_repository_updates

    log = logger.bind(job="poll_repository_updates")
    log.info("job_start")

    try:
        result = run_async_task(poll_repository_updates)
        log.info("job_complete", result=result)
    except Exception as e:
        log.exception("job_error", error=str(e))


@_with_scheduler_log_context
def calculate_behind_commits_job() -> None:
    """contract：计算 STALE 仓库的 behind_commits 差值并缓存。"""
    from repositories.freshness_service import update_behind_commits_for_stale_repos

    log = logger.bind(job="calculate_behind_commits")
    log.info("job_start")

    try:
        run_async_task(update_behind_commits_for_stale_repos)
        log.info("job_complete")
    except Exception as e:
        log.exception("job_error", error=str(e))


@_with_scheduler_log_context
def cleanup_stale_branch_indexes_job():
    """Job wrapper for cleanup_stale_branch_indexes (implementation)."""
    from tasks.index_trigger_tasks import cleanup_stale_branch_indexes

    log = logger.bind(job="cleanup_stale_branch_indexes")
    log.info("job_start")

    try:
        result = run_async_task(cleanup_stale_branch_indexes)
        log.info("job_complete", result=result)
    except Exception as e:
        log.exception("job_error", error=str(e))


@_with_scheduler_log_context
def cleanup_orchestration_checkpoints_job():
    """Job wrapper for cleanup_orchestration_checkpoints command (implementation contract).

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


@_with_scheduler_log_context
def cleanup_coding_sessions_job():
    """Job wrapper for cleanup_coding_sessions command (resume SDK session TTL).

    与 cleanup_orchestration_checkpoints_job 同 call_command 模式（命令内部为同步
    ORM update，无需 run_async_task 包装）。清理 7 天前编码会话的 SDK transcript/
    session_id，防 DB 因 resume 持久化无限膨胀。
    """
    from django.core.management import call_command

    log = logger.bind(job="cleanup_coding_sessions")
    log.info("job_start")

    try:
        call_command("cleanup_coding_sessions")
        log.info("job_complete")
    except Exception as e:
        log.exception("job_error", error=str(e))


@_with_scheduler_log_context
def backfill_chunk_edges_job() -> None:
    """scheduler 启动时一次性扫所有 INDEXED 仓库 backfill ChunkEdge.

    DateTrigger(run_date=timezone.now()) 单次任务模式：跑完即结束，不周期重复
    （per context contract Claude Discretion，避免 IntervalTrigger 浪费资源）。

    work item 修复（implementation REVIEW）：重试机制澄清——每次 scheduler 启动都通过
    ``replace_existing=True`` **重建** DateTrigger，等价于幂等性 retry；
    ``DjangoJobStore`` 仅承担 misfire window 期间崩溃恢复（trigger 还没 fire
    scheduler 就 crash → 下次启动 jobstore 仍有该 job + 新 DateTrigger → 直接
    继续）。**不是**因为 DjangoJobStore 持久化"保留 job_state"自动重试——若
    删除 ``replace_existing=True``，下次启动不会再触发（旧 DateTrigger 已过期）。

    与 ``cleanup_orchestration_checkpoints_job`` 同 ``call_command`` 模式（不走
    ``run_async_task`` 包装——``rebuild_chunk_edges`` 命令内部已 ``asyncio.run``）；
    单 repo dispatch 失败由命令自身吞掉 + ``stderr`` 提示 + 跳过 last_built_at 更新
    （implementation contract 容错语义），不会冒泡到本 wrapper。

    work item 修复（implementation REVIEW）：``CommandError`` / ``ImproperlyConfigured``
    等启动级错误（参数互斥、settings 缺失等）需 re-raise 让 APScheduler 标记
    ``DjangoJobExecution.status = "Error"`` 暴露到运维监控；只有 runtime 异常
    （单 repo dispatch 失败上抛、call_command 内部 bug 等）走 swallow + log
    路径。同时 contract 让命令在 failed_repos>0 时 sys.exit(1)，本 wrapper 把
    ``SystemExit(1)`` 也转为日志可见的 job_failed 但不打断 scheduler 主循环。
    """
    from django.core.exceptions import ImproperlyConfigured
    from django.core.management import call_command
    from django.core.management.base import CommandError

    log = logger.bind(job="backfill_chunk_edges")
    log.info("job_start")

    try:
        call_command("rebuild_chunk_edges", all=True)
        log.info("job_complete")
    except (CommandError, ImproperlyConfigured) as e:
        log.exception("job_misconfigured", error=str(e))
        raise
    except SystemExit as e:
        log.error(
            "job_failed_exit_code",
            error=str(e),
            exit_code=getattr(e, "code", None),
        )
    except Exception as e:
        log.exception("job_error", error=str(e))


class Command(BaseCommand):
    """APScheduler 长驻进程。

    **部署契约（contract / implementation REVIEW）：scheduler 必须单实例运行。**

    DjangoJobStore 跨进程共享 job 状态，但 ``max_instances=1`` 仅在单 scheduler
    内生效；若多 ``runapscheduler`` 进程并存（容器编排误启两份、灰度滚动重启
    重叠等），所有进程启动时都会 ``add_job(..., replace_existing=True)``，且各
    自从 DjangoJobStore 拉到同一个未跑的 ``backfill_chunk_edges`` job 并独立
    执行 → ``rebuild_chunk_edges --all`` 可能并发跑两次。下游 ``bulk_insert_edges``
    ``ignore_conflicts=True`` 兜底正确性，但 6 builder × N repo × 2 进程的 RAM/CPU
    双倍消耗对老仓库 backfill 有 OOM 风险（context contract 明确"避免多 repo × 6
    builder 同时跑爆 RAM"）。

    **强制：** ``handle()`` 开头用 ``fcntl.flock`` 占据 ``/tmp/friday-scheduler.lock``
    advisory lock；第二份 scheduler 启动时立即报错退出。lock fd 故意泄漏到进程
    生命周期结束（OS 自动释放），不显式 close。SIGKILL / 容器 OOM 时 OS 也会
    释放 → 下次启动立即可获取。
    """

    help = "Runs APScheduler for session timeout tasks (single-instance enforced via flock)."

    def handle(self, *args, **options):
        # contract 修复：advisory flock 拒绝并发 scheduler 启动（per implementation REVIEW）
        import fcntl

        lock_path = getattr(
            settings, "APSCHEDULER_LOCK_PATH", "/tmp/friday-scheduler.lock"
        )
        try:
            lock_fd = open(lock_path, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            logger.error(
                "scheduler_already_running",
                lock_path=lock_path,
                error=str(exc),
                hint=(
                    "另一份 runapscheduler 进程已占据该 lock；"
                    "scheduler 必须单实例运行（contract / implementation REVIEW）。"
                    "停掉重复进程或更换 settings.APSCHEDULER_LOCK_PATH。"
                ),
            )
            self.stderr.write(
                f"Scheduler already running (lock held: {lock_path})。"
                f"单实例契约（implementation contract），拒绝重复启动。"
            )
            raise SystemExit(1) from exc
        # lock_fd 故意泄漏到进程生命周期结束（OS 在进程退出时自动释放 flock）
        logger.info("scheduler_lock_acquired", lock_path=lock_path)

        scheduler = BackgroundScheduler(timezone=settings.TIME_ZONE)
        scheduler.add_jobstore(DjangoJobStore(), "default")

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

        # Cleanup orchestration checkpoints daily at 3:30 UTC (implementation contract)
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

        # Cleanup coding session SDK resume data daily at 04:00 (7-day TTL)
        # 选 04:00 错开 03:00/03:30 的 SQLite 清理，避免争写锁。
        scheduler.add_job(
            cleanup_coding_sessions_job,
            trigger=CronTrigger(hour=4, minute=0),
            id="cleanup_coding_sessions",
            name="Cleanup coding session SDK resume data older than 7 days",
            max_instances=1,
            replace_existing=True,
        )
        logger.info(
            "job_registered",
            job="cleanup_coding_sessions",
            schedule="daily at 04:00",
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

        # Poll repository updates every N seconds (implementation contract，间隔由 settings.SYNC_INTERVAL_SECONDS 统一管理)
        scheduler.add_job(
            poll_repository_updates_job,
            trigger=IntervalTrigger(seconds=settings.SYNC_INTERVAL_SECONDS),
            id="poll_repository_updates",
            name="Poll for repository updates via git ls-remote",
            max_instances=1,
            replace_existing=True,
        )
        # Deploy 注意（contract Pitfall 4）：首次部署新代码前，在生产 SQLite 上执行：
        # DELETE FROM django_apscheduler_djangojob WHERE id='poll_repository_updates';
        # 启动新代码后 scheduler 会自动重建，避免旧 job_state 残留旧 trigger。
        logger.info("job_registered", job="poll_repository_updates", schedule=f"every {settings.SYNC_INTERVAL_SECONDS}s")

        # 计算 STALE 仓库 behind_commits 差值，串联 poll_repository_updates（implementation contract）
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

        # implementation ½：scheduler 启动后一次性 backfill ChunkEdge（老仓库
        # v23.0 索引完无 ChunkEdge）。DateTrigger 单次 trigger 跑完即结束；与 v23.0
        # IntervalTrigger poll_repository_updates / calculate_behind_commits 共存。
        #
        # work item 修复（implementation REVIEW）：必须传 timezone-aware datetime；裸
        # ``datetime.now()`` 是 naive，APScheduler 会按 scheduler tz
        # (``Asia/Shanghai``) 解释，但 UTC 容器（生产常见 Docker/K8s 默认 UTC）
        # 实际系统时间已是 UTC，naive 解释成 +08:00 = **早 8 小时**，落入
        # ``misfire_grace_time`` 窗口外被丢弃 → implementation ½ 整个机制
        # 在 UTC 部署下失效。``django.utils.timezone.now()`` 返回 aware datetime
        # (USE_TZ=True，与项目惯例一致)，APScheduler 直接按其携带 tz 解释。
        # 同时显式 ``misfire_grace_time=3600`` 兜底 scheduler 启动慢场景。
        scheduler.add_job(
            backfill_chunk_edges_job,
            trigger=DateTrigger(run_date=timezone.now()),
            id="backfill_chunk_edges",
            name="implementation: one-shot backfill ChunkEdge for legacy repositories",
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
            scheduler.start()
            self.stdout.write(self.style.SUCCESS("Scheduler started. Press Ctrl+C to exit."))

            # Keep the main thread alive
            import time
            while True:
                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("scheduler_shutdown_requested")
            scheduler.shutdown()
            self.stdout.write(self.style.SUCCESS("Scheduler shut down successfully."))
