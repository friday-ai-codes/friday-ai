"""Django management command to run the APScheduler.
Starts the background scheduler for session timeout tasks:
- check_timeout_reminders: Every hour
- cleanup_expired_sessions: Daily at 3:00 AM
"""
import asyncio
import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from django.conf import settings
from django.core.management.base import BaseCommand
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
