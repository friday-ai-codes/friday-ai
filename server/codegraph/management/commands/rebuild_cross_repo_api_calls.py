"""Management command: 重建跨仓 API 调用关系（CrossRepoApiCall 表）。

用法：
    python manage.py rebuild_cross_repo_api_calls --all
    python manage.py rebuild_cross_repo_api_calls --repo <UUID>
    python manage.py rebuild_cross_repo_api_calls --all --dry-run
    python manage.py rebuild_cross_repo_api_calls --all --batch-size 1000

per work item, work item
与 implementation backfill_chunk_edges 同模式。
"""

from __future__ import annotations

import time
import uuid as _uuid
from argparse import ArgumentParser

import structlog
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "重建 CrossRepoApiCall 跨仓 join 表（offline join ApiWrapper × Endpoint）"

    def add_arguments(self, parser: ArgumentParser) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--all", action="store_true", help="全量重建（清空表 + 重新 join）")
        group.add_argument("--repo", help="只对指定仓库的 ApiWrapper 做 join（传 UUID 或名称）")
        parser.add_argument("--dry-run", action="store_true", help="只统计 match 数，不写入 DB")
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="bulk_create 批次大小（默认 500）",
        )

    def handle(self, *args: object, **options: object) -> None:
        do_all: bool = bool(options["all"])
        repo_id_or_name: str | None = options.get("repo") and str(options["repo"])  # type: ignore[assignment]
        dry_run: bool = bool(options["dry_run"])

        from codegraph.cross_repo.join_service import (
            build_cross_repo_matches,
            build_endpoint_map,
            write_cross_repo_matches,
        )
        from codegraph.models import ApiWrapper, CrossRepoApiCall, Endpoint

        start_ts = time.monotonic()

        if do_all:
            self.stdout.write(self.style.SUCCESS("\n▶ CrossRepo join — 全量重建\n"))
            endpoints_qs = Endpoint.objects.all()
            wrappers_qs = ApiWrapper.objects.all()
        else:
            from repositories.models import Repository

            repo_name = repo_id_or_name or ""
            try:
                repo = Repository.objects.get(pk=_uuid.UUID(repo_name))
            except (ValueError, Repository.DoesNotExist):
                qs = Repository.objects.filter(name=repo_name)
                if not qs.exists():
                    raise CommandError(f"找不到仓库：{repo_name}（支持 UUID / name）")
                repo = qs.first()  # type: ignore[assignment]

            self.stdout.write(self.style.SUCCESS(f"\n▶ CrossRepo join — 仓库：{repo.name}\n"))
            # 跨仓 join：该仓库的 ApiWrapper × 全量 Endpoint（跨仓语义）
            endpoints_qs = Endpoint.objects.all()
            wrappers_qs = ApiWrapper.objects.filter(repository=repo)

        ep_map = build_endpoint_map(endpoints_qs)
        self.stdout.write(f"  Endpoint 路径数（唯一 key）：{len(ep_map)}")

        records = build_cross_repo_matches(ep_map, wrappers_qs)
        self.stdout.write(f"  match 候选记录数：{len(records)}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\n  [dry-run] 不写入 DB，退出"))
            return

        if do_all:
            deleted_count, _ = CrossRepoApiCall.objects.all().delete()
            self.stdout.write(f"  清空旧记录：{deleted_count} 条")

        written = write_cross_repo_matches(records)
        elapsed = time.monotonic() - start_ts

        self.stdout.write(
            self.style.SUCCESS(
                f"\n  ✓ 写入 {written} 条 CrossRepoApiCall，耗时 {elapsed:.2f}s\n"
            )
        )

        self._update_index_history(written)

        logger.info(
            "rebuild_cross_repo_api_calls_complete",
            mode="all" if do_all else "repo",
            written=written,
            elapsed_s=round(elapsed, 3),
        )

    def _update_index_history(self, match_count: int) -> None:
        """更新最近一条 IndexHistory 的 cross_repo 字段（尽力而为）。"""
        from repositories.models import IndexHistory

        try:
            latest = IndexHistory.objects.order_by("-created_at").first()
            if latest:
                latest.cross_repo_match_count = match_count
                latest.cross_repo_built_at = timezone.now()
                latest.save(update_fields=["cross_repo_match_count", "cross_repo_built_at"])
        except Exception as exc:
            logger.warning("update_index_history_failed", error=str(exc))
