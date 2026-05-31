"""Phase Plan（ / v26.2 Critical 2）：`rebuild_branch_graph` 命令。
存量 base 图谱「被历史 ``run_branch_index`` 写入的 feature 边」污染的评估 + 清污入口
骨架，复用 v24.0 ``rebuild_chunk_edges`` 的命令模式（--repo/--all 互斥 + --dry-run 默
认安全 + 三态 RepoStatus + structlog）。
 python manage.py rebuild_branch_graph --repo <uuid> --dry-run # 单仓污染量评估
 python manage.py rebuild_branch_graph --all --dry-run # 全 INDEXED 仓评估
**诚实限制（Pitfall 5，RESEARCH 关键结论）：** v26.2 迁移后所有存量图谱行
``branch_name=""``（base），**无分支标记**可事后精确还原「哪条边是某 feature 写的」，
故 ``--dry-run`` 给的是**评估区间**而非精确清单：
- **at-risk 仓**：存在 ≥1 条 ``RepositoryBranchIndex(status=INDEXED, is_base_branch=False)``；
- **definite 下界**：base 图谱行 path 命中某 feature overlay ``BranchFileIndex(change_type="added")``
 的文件（该文件 base 树本不存在 → 必然 feature 污染）；
- **ambiguous 上界**：base 行 path 命中 feature overlay ``change_type="modified"`` 文件
 （base/feature 版本均可能命中，计入上界）。
**实跑（非 dry-run）：** 本 phase **仅交付骨架**——实际重建依赖 Phase 的
branch-scoped 写入，故实跑路径为**受控占位**（明确报错 + 非零退出，不静默写库、不
伪装成功）。
引用：ROADMAP Critical 2 / / work-item「清污 command 设计」。
"""
from __future__ import annotations
import uuid
from typing import Any, Literal
import structlog
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import QuerySet
from code_relations.models import ChunkEdge, ChunkRegistry
from codegraph.models import CallEdge, Endpoint, Symbol
from repositories.models import (
 BranchFileIndex,
 BranchIndexStatus,
 IndexStatus,
 Repository,
 RepositoryBranchIndex,
)
logger = structlog.get_logger(__name__)
# 与 rebuild_chunk_edges 对齐的三态：让 summary 区分「无 at-risk 分支跳过」与失败。
RepoStatus = Literal["processed", "skipped_no_work", "failed"]
class Command(BaseCommand):
 """评估存量 base 图谱被 feature 边污染的体量（--dry-run），实跑骨架待 Phase。"""
 help = (
 "评估 / 重建分支隔离图谱（v26.2 ）；"
 "--dry-run 输出 base 图谱污染量区间报告且不写库，实跑骨架依赖 Phase"
 )
 def add_arguments(self, parser: CommandParser) -> None:
 parser.add_argument(
 "--repo",
 type=str,
 default=None,
 help="Repository UUID；与 --all 互斥",
 )
 parser.add_argument(
 "--all",
 action="store_true",
 help="遍历所有 is_deleted=False + index_status=INDEXED 仓库",
 )
 parser.add_argument(
 "--dry-run",
 action="store_true",
 help="仅评估存量 base 图谱污染量，不写库（默认安全模式建议始终带上）",
 )
 def handle(self, *args: Any, **options: Any) -> None:
 repo_filter: str | None = options["repo"]
 all_mode: bool = options["all"]
 dry_run: bool = options["dry_run"]
 if repo_filter and all_mode:
 raise CommandError("--repo 与 --all 互斥，请只传其一")
 if not repo_filter and not all_mode:
 raise CommandError("必须指定 --repo <uuid> 或 --all")
 repos_qs: QuerySet[Repository] = Repository.objects.filter(
 is_deleted=False, index_status=IndexStatus.INDEXED
 )
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
 f"未找到 INDEXED repository_id={repo_filter}"
 f"（不存在 / 已软删 / index_status != INDEXED）"
 )
 self.stdout.write("没有可处理的 INDEXED 仓库")
 return
 # 实跑受控占位：实际重建依赖 Phase branch-scoped 写入，本 phase 不接通。
 # 早返回放在选仓校验之后，让参数错误仍能优先暴露（便于运维定位）。
 if not dry_run:
 raise CommandError(
 "实际重建依赖 Phase branch-scoped 写入，v26.2 Phase 仅交付 "
 "--dry-run 污染量评估 + 命令骨架。请加 --dry-run 运行评估；"
 "实跑路径将在 Phase 接通后填充（当前不静默写库、不伪装成功）。"
 )
 logger.info(
 "rebuild_branch_graph_started",
 repo_count=len(repos),
 dry_run=dry_run,
 mode="all" if all_mode else "single",
 )
 processed_repos = 0
 skipped_no_work_repos = 0
 for repo in repos:
 status = self._assess_repo(repo)
 if status == "processed":
 processed_repos += 1
 else:
 skipped_no_work_repos += 1
 self.stdout.write("")
 self.stdout.write(
 f"Summary: processed_repos={processed_repos} "
 f"skipped_no_work_repos={skipped_no_work_repos} "
 f"dry_run={dry_run}"
 )
 logger.info(
 "rebuild_branch_graph_finished",
 processed_repos=processed_repos,
 skipped_no_work_repos=skipped_no_work_repos,
 dry_run=dry_run,
 )
 def _assess_repo(self, repository: Repository) -> RepoStatus:
 """对单仓做 dry-run 污染量评估（**只读不写库**）。
 Returns:
 ``"processed"``：该仓有 ≥1 个 at-risk feature 分支，已输出污染量区间报告；
 ``"skipped_no_work"``：无 INDEXED 非 base 分支，base 图谱无 feature 污染风险。
 """
 repo_id = str(repository.id)
 # at-risk 分支严格为 INDEXED 且非 base 的 RepositoryBranchIndex。
 at_risk_branches: QuerySet[RepositoryBranchIndex] = (
 RepositoryBranchIndex.objects.filter(
 repository=repository,
 status=BranchIndexStatus.INDEXED,
 is_base_branch=False,
 )
 )
 at_risk_names: list[str] = list(
 at_risk_branches.values_list("branch_name", flat=True)
 )
 if not at_risk_names:
 self.stdout.write(
 f"[SKIP] repo={repository.name} ({repo_id}) "
 f"at_risk_branches=0（无 INDEXED feature 分支）"
 )
 return "skipped_no_work"
 # feature overlay 的变更文件集：added → definite 下界；modified → ambiguous 上界。
 overlay_files: QuerySet[BranchFileIndex] = BranchFileIndex.objects.filter(
 branch_index__in=at_risk_branches
 )
 added_paths: set[str] = set(
 overlay_files.filter(change_type="added").values_list(
 "file_path", flat=True
 )
 )
 modified_paths: set[str] = set(
 overlay_files.filter(change_type="modified").values_list(
 "file_path", flat=True
 )
 )
 # 去重：同一 path 若在 A 分支 added、B 分支 modified，归入 definite（更强的下界信号），
 # 避免同一 base 行被 definite + ambiguous 双计而虚增上界。
 modified_paths -= added_paths
 # 命中统计只看 base 图谱行（branch_name=""），即历史误写进 base 的潜在 feature 边。
 # 注意：当前仅覆盖 Symbol/CallEdge/Endpoint/ChunkRegistry 四表（per RESEARCH 设计），
 # ImportEdge/ApiWrapper 暂不计入，区间为保守低估；Phase 实跑时再补全。
 definite_rows = self._count_base_rows_in_paths(repo_id, added_paths)
 ambiguous_rows = self._count_base_rows_in_paths(repo_id, modified_paths)
 base_symbols = Symbol.objects.filter(
 repository_id=repo_id, branch_name=""
 ).count
 base_chunk_edges = ChunkEdge.objects.filter(
 repository_id=repo_id, branch_name=""
 ).count
 self.stdout.write(
 f"[DRY-RUN] repo={repository.name} ({repo_id}) "
 f"base_symbols={base_symbols} base_chunk_edges={base_chunk_edges} "
 f"definite_feature_rows={definite_rows} ambiguous_rows={ambiguous_rows} "
 f"at_risk_branches={at_risk_names}"
 )
 logger.info(
 "rebuild_branch_graph_dry_run_repo",
 repository_id=repo_id,
 base_symbols=base_symbols,
 base_chunk_edges=base_chunk_edges,
 definite_feature_rows=definite_rows,
 ambiguous_rows=ambiguous_rows,
 at_risk_branches=at_risk_names,
 )
 return "processed"
 @staticmethod
 def _count_base_rows_in_paths(repo_id: str, paths: set[str]) -> int:
 """统计 base 图谱中 path 命中给定文件集的行数（Symbol/CallEdge/Endpoint/ChunkRegistry）。
 只读聚合，绝不写库。无 file_path 列的表映射到语义最近的锚定列
 （CallEdge → caller_file）。空集合直接返回 0，避免无谓查询。
 """
 if not paths:
 return 0
 path_list = list(paths)
 return (
 Symbol.objects.filter(
 repository_id=repo_id, branch_name="", file_path__in=path_list
 ).count
 + CallEdge.objects.filter(
 repository_id=repo_id, branch_name="", caller_file__in=path_list
 ).count
 + Endpoint.objects.filter(
 repository_id=repo_id, branch_name="", file_path__in=path_list
 ).count
 + ChunkRegistry.objects.filter(
 repository_id=repo_id, branch_name="", file_path__in=path_list
 ).count
 )
