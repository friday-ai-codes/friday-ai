"""Management command: 全量 backfill 跨仓 API_CALLS 类型 ChunkEdge。

用法：
    python manage.py rebuild_cross_repo_edges --all
    python manage.py rebuild_cross_repo_edges --repo <UUID>
    python manage.py rebuild_cross_repo_edges --all --dry-run
    python manage.py rebuild_cross_repo_edges --all --batch-size 1000

per work item
与 implementation rebuild_chunk_edges + implementation rebuild_cross_repo_api_calls 同模式。
"""

from __future__ import annotations

import time
import uuid as _uuid
from argparse import ArgumentParser

import structlog
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "重建跨仓 API_CALLS 类型 ChunkEdge（CrossRepoApiCall → ChunkEdge backfill）"

    def add_arguments(self, parser: ArgumentParser) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--all", action="store_true", help="全量重建（清空 API_CALLS 边 + 重建）")
        group.add_argument("--repo", help="只对指定仓库的 ApiCallSite 做重建（传 UUID）")
        parser.add_argument("--dry-run", action="store_true", help="只统计，不写入 DB")
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="bulk_create 批次大小（默认 500）",
        )

    def handle(self, *args: object, **options: object) -> None:
        # work item 守卫：ENABLE_CROSS_REPO_ENRICHMENT=False 时打印警告并退出
        enable_cross: bool = bool(
            getattr(settings, "ENABLE_CROSS_REPO_ENRICHMENT", True)
        )
        if not enable_cross:
            self.stderr.write(
                self.style.WARNING(
                    "⚠ ENABLE_CROSS_REPO_ENRICHMENT=False — 跨仓 enrichment 已关闭，跳过重建。\n"
                    "如需重建请先设置 ENABLE_CROSS_REPO_ENRICHMENT=True。"
                )
            )
            return

        do_all: bool = bool(options["all"])
        repo_id_str: str | None = str(options["repo"]) if options.get("repo") else None
        dry_run: bool = bool(options["dry_run"])
        batch_size: int = int(options["batch_size"])  # type: ignore[call-overload]

        from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
        from codegraph.models import CrossRepoApiCall

        t0 = time.perf_counter()
        logger.info(
            "cross_repo_edges_backfill_started",
            do_all=do_all,
            repo_id=repo_id_str,
            dry_run=dry_run,
        )

        # 1. 清空旧 API_CALLS 边（--all 模式）
        if do_all and not dry_run:
            deleted_count, _ = ChunkEdge.objects.filter(
                edge_type=EdgeType.API_CALLS
            ).delete()
            self.stdout.write(f"已清空 {deleted_count} 条旧 API_CALLS 边")

        # 2. 构建 CrossRepoApiCall 查询集
        qs = CrossRepoApiCall.objects.select_related(
            "call_site__api_wrapper",
            "endpoint",
        )
        if repo_id_str:
            try:
                repo_uuid = _uuid.UUID(repo_id_str)
            except ValueError as exc:
                raise CommandError(
                    f"--repo 格式非法 UUID: {repo_id_str!r}"
                ) from exc
            qs = qs.filter(call_site__repository_id=repo_uuid)

        cross_calls = list(qs)
        if not cross_calls:
            self.stdout.write("无 CrossRepoApiCall 记录，跳过。")
            return

        # 3. 批量查 ChunkRegistry：file_path → (chunk_id_str, repo_id_uuid)
        import uuid as _uuid_mod

        all_files: set[str] = set()
        for cc in cross_calls:
            all_files.add(cc.call_site.caller_file)
            all_files.add(cc.endpoint.file_path)

        file_to_chunk: dict[str, tuple[str, _uuid_mod.UUID]] = {}
        for reg in ChunkRegistry.objects.filter(file_path__in=all_files).only(
            "chunk_id", "file_path", "repository_id"
        ):
            fp = reg.file_path
            if fp not in file_to_chunk:
                file_to_chunk[fp] = (str(reg.chunk_id), reg.repository_id)

        # 4. 构建 ChunkEdge 列表
        edges_to_create: list[ChunkEdge] = []
        skipped = 0
        for cc in cross_calls:
            src_info = file_to_chunk.get(cc.call_site.caller_file)
            tgt_info = file_to_chunk.get(cc.endpoint.file_path)
            if not src_info or not tgt_info:
                skipped += 1
                continue

            src_chunk_id_str, src_repo_id = src_info  # type: ignore[assignment]
            tgt_chunk_id_str, tgt_repo_id = tgt_info  # type: ignore[assignment]

            fn_sym = ""
            if cc.call_site.api_wrapper_id:
                fn_sym = cc.call_site.api_wrapper.function_symbol

            meta = {
                "function_symbol": fn_sym,
                "caller_file": cc.call_site.caller_file,
                "line_number": cc.call_site.line_number,
                "http_method": cc.endpoint.http_method,
                "url_path": cc.endpoint.url_path,
                "match_confidence": float(cc.match_confidence),
                "direction": "calls",
            }

            edge = ChunkEdge(
                source_chunk_id=src_chunk_id_str,
                target_chunk_id=tgt_chunk_id_str,
                edge_type=EdgeType.API_CALLS,
                weight=float(cc.match_confidence),
                metadata=meta,
                repository_id=src_repo_id,
                target_repository_id=tgt_repo_id,
            )
            edges_to_create.append(edge)

        # 5. bulk_create
        created = 0
        if not dry_run:
            from django.db import transaction

            for i in range(0, len(edges_to_create), batch_size):
                batch = edges_to_create[i : i + batch_size]
                with transaction.atomic():
                    result_batch = ChunkEdge.objects.bulk_create(
                        batch, ignore_conflicts=True
                    )
                    created += len(result_batch)
        else:
            created = len(edges_to_create)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "cross_repo_edges_backfill_completed",
            total_cross_calls=len(cross_calls),
            created=created,
            skipped=skipped,
            dry_run=dry_run,
            elapsed_ms=elapsed_ms,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"✅ rebuild_cross_repo_edges 完成：{created} 条 API_CALLS 边{'（dry-run）' if dry_run else ''}写入，"
                f"{skipped} 条跳过（ChunkRegistry 缺失），耗时 {elapsed_ms}ms"
            )
        )
