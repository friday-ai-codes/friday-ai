"""Phase Plan：`verify_payload_consistency` 管理命令。
运维侧兜底校验工具：随机采样 ChunkRegistry 行 → 从 Qdrant 拉
`payload.related_chunks` → 校验每个 `neighbor.chunk_id` 仍在 ChunkRegistry
存在 → 输出表格 + 总 orphan / skipped 计数。
`--fix` 模式：把含 orphan 的 source chunk_id 列表透传给 Phase
`enqueue_edge_build` 触发增量重 build，复用 Phase 现成管线。
引用：
- ROADMAP：本命令是 Phase reconcile 链路的兜底校验工具
 （signal handler / cleanup_index 任一异常静默时由本命令 surface orphan + 修复）。
- Phase CONTEXT：命令位置 + BaseCommand 子类 + add_arguments 三参数
 规范。
- Phase CONTEXT：默认 dry-run；`--fix` 显式 opt-in 防误触发
 （T- mitigate）。
**用法：**
 python manage.py verify_payload_consistency --repo <uuid> --sample 100
 python manage.py verify_payload_consistency --repo <uuid> --sample 50 --fix
 python manage.py verify_payload_consistency # 遍历所有未删除仓库（dry-run）
**异常隔离：** 单 chunk 的 Qdrant retrieve / ORM 失败仅 log warning + skipped++
+ 继续采样下一个 chunk；单点错误绝不让整命令崩。
"""
from __future__ import annotations
import asyncio
import uuid
from typing import Any
import structlog
from django.core.management.base import BaseCommand, CommandError, CommandParser
from code_relations import tasks as tasks_module
from code_relations.models import ChunkRegistry
from code_relations.tasks import enqueue_edge_build
from repositories.models import Repository
from services.qdrant_service import QdrantService
logger = structlog.get_logger(__name__)
# `--sample` 上限（per ）：避免运维误传 `--sample 1000000` 在大仓上触发
# Postgres `ORDER BY RANDOM` 全表扫描 + 排序 → 30s+ 不返回。10k 已远超
# 一致性抽检需求；超过此上限抛 CommandError 提醒走分批。
_SAMPLE_UPPER_BOUND = 10_000
class Command(BaseCommand):
 """校验 Qdrant payload.related_chunks 与 ChunkRegistry 一致性。"""
 help = (
 "校验 Qdrant payload.related_chunks 中 chunk_id 在 ChunkRegistry 仍存在；"
 "--fix 触发增量 reconcile（默认 dry-run）"
 )
 def add_arguments(self, parser: CommandParser) -> None:
 parser.add_argument(
 "--repo",
 type=str,
 default=None,
 help="Repository UUID；不传时遍历所有 is_deleted=False 仓库",
 )
 parser.add_argument(
 "--sample",
 type=int,
 default=100,
 help="每仓库随机采样的 chunk 数量上限（default 100）",
 )
 parser.add_argument(
 "--fix",
 action="store_true",
 help="发现 orphan 时调 enqueue_edge_build 触发增量 reconcile（默认 dry-run）",
 )
 def handle(self, *args: Any, **options: Any) -> None:
 repo_filter: str | None = options["repo"]
 sample_size: int = options["sample"]
 fix_mode: bool = options["fix"]
 if sample_size <= 0:
 raise CommandError("--sample 必须为正整数")
 if sample_size > _SAMPLE_UPPER_BOUND:
 raise CommandError(
 f"--sample 超过上限 {_SAMPLE_UPPER_BOUND}（避免大仓 ORDER BY RANDOM "
 f"全表扫描）；如需更大覆盖请分批或新增 --offset 子命令"
 )
 repos_qs = Repository.objects.filter(is_deleted=False)
 if repo_filter:
 try:
 uuid.UUID(repo_filter)
 except (ValueError, TypeError) as exc:
 raise CommandError(f"--repo 不是合法 UUID: {repo_filter}") from exc
 repos_qs = repos_qs.filter(id=repo_filter)
 repos = list(repos_qs)
 if not repos:
 if repo_filter:
 raise CommandError(
 f"未找到 repository_id={repo_filter}（不存在或已被软删除）"
 )
 self.stdout.write("没有可校验的仓库（is_deleted=False 集合为空）")
 return
 for repo in repos:
 self._verify_repo(repo, sample_size, fix_mode)
 def _verify_repo(
 self,
 repository: Repository,
 sample_size: int,
 fix_mode: bool,
 ) -> None:
 """校验单个仓库的 payload 一致性，含可选 --fix 触发 reconcile。"""
 repo_id = str(repository.id)
 self.stdout.write(f"\n=== Repository {repository.name} ({repo_id}) ===")
 sample_chunk_ids: list[uuid.UUID] = list(
 ChunkRegistry.objects.filter(repository_id=repo_id)
 .order_by("?")
 .values_list("chunk_id", flat=True)[:sample_size]
 )
 if not sample_chunk_ids:
 self.stdout.write(" 跳过：该仓库 ChunkRegistry 为空")
 return
 client = QdrantService.get_client
 collection_name = QdrantService.get_collection_name(repo_id)
 total_checked = 0
 total_orphans = 0
 total_skipped = 0
 dirty_source_ids: list[uuid.UUID] =
 self.stdout.write(
 f"{'chunk_id':<38} | {'orphan':>6} | {'total':>5} | orphan_pct"
 )
 self.stdout.write("-" * 78)
 #：单次批量 retrieve 替代循环 N 次单点查询；--sample 100 时
 # HTTP roundtrip 从 100 次降到 1 次，节省 ~98% 网络开销。
 records_by_id: dict[str, Any] = {}
 try:
 records = client.retrieve(
 collection_name=collection_name,
 ids=[str(cid) for cid in sample_chunk_ids],
 with_payload=["related_chunks"],
 )
 for r in records:
 records_by_id[str(r.id)] = r
 except Exception as exc:
 logger.warning(
 "verify_payload_batch_retrieve_failed",
 repo_id=repo_id,
 sample_size=len(sample_chunk_ids),
 error=str(exc),
 error_type=type(exc).__name__,
 )
 # 批量 retrieve 失败：标全部 skipped，不再 fallback per-chunk
 # （per-chunk fallback 在 Qdrant down 时只会 N 次重复失败）
 self.stdout.write(
 f" ⚠️ 批量 retrieve 失败：跳过 {len(sample_chunk_ids)} 个 chunk"
 )
 self.stdout.write("-" * 78)
 self.stdout.write(
 f"Summary: total_chunks_checked=0 "
 f"total_orphans=0 total_skipped={len(sample_chunk_ids)}"
 )
 return
 for chunk_id in sample_chunk_ids:
 record = records_by_id.get(str(chunk_id))
 if record is None:
 # 该 chunk_id 在 Qdrant 中不存在 —— ChunkRegistry 有但 vector 没
 # 上传成功；上层已 log debug 即可，不算 orphan
 logger.debug(
 "verify_payload_no_qdrant_point",
 repo_id=repo_id,
 chunk_id=str(chunk_id),
 )
 continue
 payload: dict[str, Any] = record.payload or {}
 related = payload.get("related_chunks") or
 if not related:
 continue
 neighbor_ids = self._extract_neighbor_ids(related)
 if not neighbor_ids:
 continue
 try:
 existing: set[uuid.UUID] = set(
 ChunkRegistry.objects.filter(chunk_id__in=neighbor_ids).values_list(
 "chunk_id", flat=True
 )
 )
 except Exception as exc:
 logger.warning(
 "verify_payload_orm_failed",
 repo_id=repo_id,
 chunk_id=str(chunk_id),
 error=str(exc),
 error_type=type(exc).__name__,
 )
 total_skipped += 1
 continue
 orphan_count = sum(1 for nid in neighbor_ids if nid not in existing)
 total_count = len(neighbor_ids)
 total_checked += 1
 total_orphans += orphan_count
 pct = (orphan_count / total_count * 100.0) if total_count else 0.0
 if orphan_count > 0:
 dirty_source_ids.append(chunk_id)
 self.stdout.write(
 f"{str(chunk_id):<38} | {orphan_count:>6d} | {total_count:>5d} | {pct:6.2f}%"
 )
 self.stdout.write("-" * 78)
 self.stdout.write(
 f"Summary: total_chunks_checked={total_checked} "
 f"total_orphans={total_orphans} total_skipped={total_skipped}"
 )
 if fix_mode and dirty_source_ids:
 self._trigger_fix(repo_id, dirty_source_ids)
 elif fix_mode:
 self.stdout.write("--fix: 无 dirty source chunks，跳过 reconcile")
 @staticmethod
 def _extract_neighbor_ids(related: list[Any]) -> list[uuid.UUID]:
 """解析 payload.related_chunks 为 neighbor UUID 列表，跳过非法行。
 非法 entry 走 `logger.debug` surface（per ）：payload 格式漂移
 （Phase 新增字段 / 字典化）时静默跳过会让校验"全绿"误导，debug
 log 让排查时能看见。
 """
 neighbor_ids: list[uuid.UUID] =
 for entry in related:
 if not isinstance(entry, list | tuple) or len(entry) < 1:
 logger.debug("verify_payload_malformed_entry", entry=repr(entry))
 continue
 try:
 neighbor_ids.append(uuid.UUID(str(entry[0])))
 except (ValueError, TypeError):
 logger.debug(
 "verify_payload_invalid_neighbor_uuid", entry=repr(entry)
 )
 continue
 return neighbor_ids
 def _trigger_fix(
 self, repo_id: str, dirty_source_ids: list[uuid.UUID]
 ) -> None:
 """调用 enqueue_edge_build 触发增量 reconcile，并 drain 后台任务。
 enqueue_edge_build 内部 `asyncio.create_task` 是 fire-and-forget；
 若直接 `asyncio.run(enqueue)` 后立即关闭 loop，背景 task 会被 cancel
 导致实际 reconcile 未执行。这里包一层 helper：dispatch 后 drain
 `_BACKGROUND_TASKS` 集合，确保 builder + payload_sync 链路真正完成
 再退出命令（per 运维 fix 必须真正生效的语义）。
 """
 try:
 asyncio.run(self._dispatch_and_drain(repo_id, dirty_source_ids))
 self.stdout.write(
 self.style.WARNING(
 f"--fix: Triggered reconcile for {len(dirty_source_ids)} chunks"
 )
 )
 except Exception as exc:
 logger.error(
 "verify_payload_fix_failed",
 repo_id=repo_id,
 dirty_count=len(dirty_source_ids),
 error=str(exc),
 error_type=type(exc).__name__,
 )
 self.stderr.write(f"--fix 失败: {exc}")
 @staticmethod
 async def _dispatch_and_drain(
 repo_id: str, dirty_source_ids: list[uuid.UUID]
 ) -> None:
 """触发 enqueue_edge_build 并 drain 本次新 spawn 的背景 task。
 fix：照 lifecycle.py 的 before/after diff 模式，只 drain 本次
 dispatch 真正 spawn 出来的 task —— 避免误 await 跨 loop / 跨仓库的
 无关 task（多仓批量校验时尤其重要：repo_A 的 fix 启动后，repo_B
 的 dispatch_and_drain snapshot 仍含 repo_A 未完成 task → 串行阻塞）。
 """
 before = set(tasks_module._BACKGROUND_TASKS)
 await enqueue_edge_build(repo_id, dirty_source_ids)
 new_tasks = tasks_module._BACKGROUND_TASKS - before
 if new_tasks:
 await asyncio.gather(*new_tasks, return_exceptions=True)
