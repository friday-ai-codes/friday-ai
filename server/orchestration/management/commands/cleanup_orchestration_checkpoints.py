"""清理 N 天前已完成/错误的编排 checkpoint（implementation contract）。

implementation contract：防 SQLite orchestration_checkpoints.db 无限膨胀。

清理规则：
- Django ORM：`OrchestrationRun.status IN (COMPLETED, ERROR)` 且 `updated_at < now - N days`
- SQLite：对每个 thread_id 调 `AsyncSqliteSaver.adelete_thread(tid)`（官方 API）

**严格**状态过滤（Security Domain security mitigation-01）：只删 COMPLETED / ERROR，
不含 RUNNING / WAITING / INTERRUPTED / PENDING，避免误删活跃运行。

用法：
    python manage.py cleanup_orchestration_checkpoints --days=7
    python manage.py cleanup_orchestration_checkpoints --dry-run
    python manage.py cleanup_orchestration_checkpoints --days=14 --batch-size=300
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import structlog
from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from orchestration.checkpointer import get_checkpointer
from orchestration.models import OrchestrationRun

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "清理 N 天前已完成/错误的编排 checkpoint（默认 7 天；implementation contract）"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="保留天数阈值（updated_at < now-N 的记录被清理）",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="仅打印预计删除条数，不真删",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="单批 thread_id 数量（SQLite IN 变量上限 999，默认 500 留余量）",
        )

    def handle(self, *args: object, **options: Any) -> None:
        days = int(options["days"])
        dry_run = bool(options["dry_run"])
        batch_size = int(options["batch_size"])

        cutoff = timezone.now() - timedelta(days=days)
        qs = OrchestrationRun.objects.filter(
            status__in=[
                OrchestrationRun.Status.COMPLETED,
                OrchestrationRun.Status.ERROR,
            ],
            updated_at__lt=cutoff,
        )
        run_count = qs.count()
        thread_ids = list(qs.values_list("thread_id", flat=True).distinct())

        if dry_run:
            msg = f"[dry-run] would delete {run_count} runs / {len(thread_ids)} threads"
            self.stdout.write(msg)
            logger.info(
                "cleanup_orchestration_checkpoints_dry_run",
                deleted_runs=run_count,
                deleted_thread_count=len(thread_ids),
                days=days,
            )
            return

        # 分批删除 ORM 行（避免一次性大 transaction + 绕开 SQLite IN 变量上限）
        deleted_runs_total = 0
        for i in range(0, len(thread_ids), batch_size):
            batch_ids = thread_ids[i : i + batch_size]
            batch_qs = OrchestrationRun.objects.filter(
                status__in=[
                    OrchestrationRun.Status.COMPLETED,
                    OrchestrationRun.Status.ERROR,
                ],
                updated_at__lt=cutoff,
                thread_id__in=batch_ids,
            )
            deleted, _ = batch_qs.delete()
            deleted_runs_total += deleted

        # 删除 SQLite checkpoints（官方 API adelete_thread — RESEARCH Pitfall B：
        # aprune / adelete_for_runs 是 NotImplementedError 占位，不可用）
        deleted_ckpt = asyncio.run(self._delete_checkpoints(thread_ids))

        logger.info(
            "cleanup_orchestration_checkpoints_completed",
            deleted_runs=deleted_runs_total,
            deleted_thread_count=deleted_ckpt,
            days=days,
            dry_run=False,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"已清理 {deleted_runs_total} runs / {deleted_ckpt} threads"
                f"（cutoff={cutoff.isoformat()}）"
            )
        )

    async def _delete_checkpoints(self, thread_ids: list[str]) -> int:
        """对每个 thread_id 调 adelete_thread（官方 2 表 DELETE + commit）。

        单 thread 失败记 warning 后继续下一个 thread，防单点故障阻塞整批
        （security mitigation-08 Availability mitigation）。
        """
        saver = await get_checkpointer()
        count = 0
        for tid in thread_ids:
            try:
                await saver.adelete_thread(tid)
                count += 1
            except Exception as exc:
                logger.warning(
                    "cleanup_orchestration_checkpoint_delete_thread_failed",
                    thread_id=tid,
                    error=str(exc),
                )
        return count
