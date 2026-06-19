"""一次性迁移命令：把存量在途 index/graph ResumableTask 转入 durable 队列（MIGRATE-02）。

升级到 durable 队列后，存量 PENDING/RUNNING 的 index/graph `resumable_tasks` 仍登记在
真相源里。本命令把它们按 deterministic key（``index:{target_id}`` / ``graph:{target_id}``）
``DurableTaskService.defer`` 成 durable job，并把旧行标 ``MIGRATED`` + 记 ``legacy_durable_job_id``：

- **不双跑**：旧行标 MIGRATED 后被 ``recoverable_target_ids`` 天然排除，recovery/reconcile
  不再驱动；durable 侧 deterministic key 命中既有 job 去重。
- **幂等可重入**：只扫 PENDING/RUNNING（MIGRATED/CANCELLED/COMPLETED 天然排除），重跑不
  重复处理已迁移行；deterministic key 令重复 defer 不产生第二个在途 job。
- **SQLite 安全降级**：非 durable 后端（SQLite/in-process）下不静默把行"迁移"成进程内任务
  （重启即丢），给出清晰中文提示后只统计不 defer、不报错崩溃。

用法::

    python manage.py migrate_resumable_to_durable            # 真实迁移（需 Postgres + durable）
    python manage.py migrate_resumable_to_durable --dry-run  # 仅统计扫描集，不写库、不 defer
"""

from __future__ import annotations

from typing import Any

from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "一次性把存量在途 index/graph ResumableTask 迁移至 durable 队列（标 MIGRATED 记 legacy id）"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="仅打印将迁移的扫描集，不 defer、不改写旧行状态",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from durable.queues import QUEUE_GRAPH, QUEUE_INDEX
        from durable.service import DurableTaskService, use_procrastinate_backend
        from resumable.models import (
            ResumableTask,
            ResumableTaskKind,
            ResumableTaskStatus,
        )

        dry_run: bool = bool(options.get("dry_run"))

        # kind → (durable 任务名, 队列, deterministic key 前缀)
        kind_routes = {
            ResumableTaskKind.INDEX: ("durable_index", QUEUE_INDEX, "index"),
            ResumableTaskKind.GRAPH: ("durable_graph", QUEUE_GRAPH, "graph"),
        }

        # 判后端：非 durable（SQLite/in-process）下迁移意义有限——迁出的任务为进程内、
        # 重启即丢，绝不静默"迁移"。给出明确中文提示后只统计不 defer（dry-run 语义）。
        backend_durable = use_procrastinate_backend()
        if not backend_durable:
            self.stdout.write(
                self.style.WARNING(
                    "当前为非 durable 后端（SQLite/in-process），存量行迁移意义有限："
                    "迁移出的任务为进程内、重启即丢。已跳过 defer 与状态改写。"
                    "如需真实迁移请在 Postgres + DURABLE_TASK_BACKEND=procrastinate 下重跑。"
                )
            )

        candidates = list(
            ResumableTask.objects.filter(
                kind__in=[ResumableTaskKind.INDEX, ResumableTaskKind.GRAPH],
                status__in=[ResumableTaskStatus.PENDING, ResumableTaskStatus.RUNNING],
            )
        )

        scanned = len(candidates)
        migrated = 0
        skipped = 0

        for task in candidates:
            route = kind_routes.get(task.kind)
            if route is None:
                # 理论不可达（已按 kind__in 过滤），保险跳过。
                skipped += 1
                continue
            task_name, queue, key_prefix = route
            key = f"{key_prefix}:{task.target_id}"

            # 非 durable 后端 / dry-run：只统计扫描集，不 defer、不改写。
            if not backend_durable or dry_run:
                skipped += 1
                continue

            # 按显式键白名单从旧 payload 重建 durable payload——绝不透传整个 task.payload
            # （旧 resumable payload 可能含 coro_factory/name 等额外键，整传会令
            # run_index/run_graph(**payload) 抛 TypeError: unexpected keyword argument）。
            payload = task.payload or {}
            durable_payload = {
                "repository_id": payload.get("repository_id") or task.target_id,
                "history_id": payload.get("history_id"),
                "branch": payload.get("branch"),
                "trigger": payload.get("trigger") or "manual",
            }

            job_id = async_to_sync(DurableTaskService.defer)(
                task_name,
                durable_payload,
                queue=queue,
                idempotency_key=key,
            )

            # 条件 update（status 再校验）防并发重复处理：仅在仍为在途态时标 MIGRATED。
            updated = ResumableTask.objects.filter(
                id=task.id,
                status__in=[ResumableTaskStatus.PENDING, ResumableTaskStatus.RUNNING],
            ).update(
                status=ResumableTaskStatus.MIGRATED,
                legacy_durable_job_id=str(job_id),
            )
            if updated:
                migrated += 1
            else:
                skipped += 1

        backend_label = "durable" if backend_durable else "in-process"
        self.stdout.write(
            self.style.SUCCESS(
                "migrate_resumable_to_durable 完成："
                f"scanned={scanned} migrated={migrated} skipped={skipped} "
                f"dry_run={dry_run} backend={backend_label}"
            )
        )
