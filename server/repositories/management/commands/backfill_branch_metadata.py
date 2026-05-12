"""为现有仓库的 Qdrant collection 补充分支元数据字段。
用法:
 python manage.py backfill_branch_metadata # 处理所有已索引仓库
 python manage.py backfill_branch_metadata --repo-id UUID # 处理指定仓库
 python manage.py backfill_branch_metadata --dry-run # 仅检测
"""
from __future__ import annotations
from typing import Any
import structlog
from django.core.management.base import BaseCommand, CommandParser
from repositories.models import (
 BranchIndexStatus,
 IndexStatus,
 Repository,
 RepositoryBranchIndex,
)
from services.qdrant_service import QdrantService
logger = structlog.get_logger(__name__)
class Command(BaseCommand):
 help = "为现有已索引仓库的 Qdrant collection 补充 branch_name / is_base_branch payload 字段"
 def add_arguments(self, parser: CommandParser) -> None:
 parser.add_argument(
 "--repo-id",
 type=str,
 default=None,
 help="只处理指定仓库 (UUID)",
 )
 parser.add_argument(
 "--dry-run",
 action="store_true",
 help="仅检测，不执行任何更新",
 )
 parser.add_argument(
 "--batch-size",
 type=int,
 default=500,
 help="每批处理的 point 数量 (默认 500)",
 )
 def handle(self, *args: Any, **options: Any) -> None:
 repo_id: str | None = options["repo_id"]
 dry_run: bool = options["dry_run"]
 batch_size: int = options["batch_size"]
 if dry_run:
 self.stdout.write(self.style.WARNING("=== work item 模式 ==="))
 qs = Repository.objects.filter(index_status=IndexStatus.INDEXED, is_deleted=False)
 if repo_id:
 qs = qs.filter(id=repo_id)
 repos = list(qs.exclude(branch_indexes__is_base_branch=True))
 if not repos:
 self.stdout.write("没有需要迁移的仓库")
 return
 self.stdout.write(f"待处理仓库: {len(repos)}")
 success_count = 0
 fail_count = 0
 total_points = 0
 for repo in repos:
 try:
 updated = self._backfill_repository(repo, batch_size, dry_run)
 total_points += updated
 success_count += 1
 self.stdout.write(
 self.style.SUCCESS(f" ✓ {repo.name}: 更新 {updated} 个 points")
 )
 except Exception as exc:
 fail_count += 1
 logger.error(
 "backfill_repository_failed",
 repo_id=str(repo.id),
 repo_name=repo.name,
 error=str(exc),
 )
 self.stdout.write(
 self.style.ERROR(f" ✗ {repo.name}: {exc}")
 )
 self.stdout.write(
 f"\n完成: 成功 {success_count}, 失败 {fail_count}, "
 f"共更新 {total_points} 个 points"
 )
 def _backfill_repository(
 self, repository: Repository, batch_size: int, dry_run: bool
 ) -> int:
 """为单个仓库执行 backfill，返回更新的 point 数量。"""
 client = QdrantService.get_client
 collection_name = QdrantService.get_collection_name(str(repository.id))
 health = QdrantService.check_collection_health(str(repository.id))
 if not health.get("collection_exists"):
 self.stdout.write(f" 跳过 {repository.name}: collection 不存在")
 return 0
 branch_name = repository.default_branch
 updated = 0
 offset = None
 while True:
 points, next_offset = client.scroll(
 collection_name=collection_name,
 limit=batch_size,
 offset=offset,
 with_payload=False,
 with_vectors=False,
 )
 if not points:
 break
 if not dry_run:
 point_ids = [p.id for p in points]
 client.set_payload(
 collection_name=collection_name,
 payload={"branch_name": branch_name, "is_base_branch": True},
 points=point_ids,
 )
 updated += len(points)
 if next_offset is None:
 break
 offset = next_offset
 if not dry_run:
 from qdrant_client.http import models as qdrant_models
 try:
 client.create_payload_index(
 collection_name=collection_name,
 field_name="branch_name",
 field_schema=qdrant_models.PayloadSchemaType.KEYWORD,
 )
 except Exception:
 pass # index 可能已存在
 RepositoryBranchIndex.objects.update_or_create(
 repository=repository,
 branch_name=branch_name,
 defaults={
 "is_base_branch": True,
 "status": BranchIndexStatus.INDEXED,
 "collection_name": collection_name,
 "effective_chunks_count": health.get("points_count", 0),
 "last_indexed_at": repository.last_indexed_at,
 "last_indexed_commit_sha": repository.last_indexed_commit_sha,
 "head_sha": repository.last_indexed_commit_sha,
 },
 )
 return updated
