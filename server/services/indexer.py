"""Incremental indexer service for code repositories."""
import asyncio
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any
import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone
from repositories.models import (
 BranchFileIndex,
 BranchIndexStatus,
 FileIndex,
 IndexStatus,
 Repository,
 RepositoryBranchIndex,
)
from services.branch_utils import (
 MAX_OVERLAY_COLLECTIONS_PER_REPO,
 BranchOverlayLimitExceeded,
 get_overlay_collection_name,
)
from services.code_parser import CodeChunk, CodeParser, compute_file_hash, scan_directory
from services.embedding import EmbeddingService
from services.qdrant_service import QdrantService
from system.models import SettingKeys, SystemSetting
# KEEP: Qdrant SDK 使用同步 httpx 客户端，async 化属于独立重构项（Out of Scope）
# Wrap sync Qdrant operations for use in async context
@sync_to_async
def qdrant_create_collection(repository_id: str, vector_size: int, hybrid: bool = False) -> bool:
 return QdrantService.create_collection(repository_id, vector_size=vector_size, hybrid=hybrid)
@sync_to_async
def qdrant_create_branch_payload_index(collection_name: str) -> bool:
 return QdrantService.create_branch_payload_index(collection_name)
@sync_to_async # KEEP: Qdrant SDK 同步限制
def qdrant_get_stored_file_hashes(repository_id: str) -> dict[str, str]:
 return QdrantService.get_stored_file_hashes(repository_id)
@sync_to_async # KEEP: Qdrant SDK 同步限制
def qdrant_delete_by_file_path(repository_id: str, file_path: str) -> bool:
 return QdrantService.delete_by_file_path(repository_id, file_path)
@sync_to_async # KEEP: Qdrant SDK 同步限制
def qdrant_upsert_vectors(repository_id: str, points: list[dict]) -> bool:
 return QdrantService.upsert_vectors(repository_id, points)
@sync_to_async # KEEP: Qdrant SDK 同步限制
def qdrant_update_file_path(repository_id: str, old_path: str, new_path: str) -> bool:
 return QdrantService.update_file_path(repository_id, old_path, new_path)
@sync_to_async # KEEP: Qdrant SDK 同步限制
def qdrant_create_collection_by_name(collection_name: str, vector_size: int, hybrid: bool = False) -> bool:
 return QdrantService.create_collection_by_name(collection_name, vector_size, hybrid=hybrid)
@sync_to_async # KEEP: Qdrant SDK 同步限制
def qdrant_upsert_vectors_by_name(collection_name: str, points: list[dict]) -> bool:
 return QdrantService.upsert_vectors_by_name(collection_name, points)
async def update_index_progress(repository_id: str, total: int, processed: int) -> None:
 """Update indexing progress in database."""
 await Repository.objects.filter(id=repository_id).aupdate(
 index_total_chunks=total,
 index_processed_chunks=processed,
 )
async def update_write_progress(repository_id: str, total: int, processed: int) -> None:
 """Update Qdrant write progress in database."""
 await Repository.objects.filter(id=repository_id).aupdate(
 index_write_total=total,
 index_write_processed=processed,
 )
logger = structlog.get_logger(__name__)
def _build_embedding_text(chunk: CodeChunk) -> str:
 """构建用于 embedding 的增强文本，包含上下文信息。"""
 parts = [chunk.context_header]
 if chunk.imports:
 parts.append(f"Imports: {chunk.imports[:300]}")
 if chunk.module_docstring:
 parts.append(f"Module: {chunk.module_docstring[:200]}")
 if chunk.sibling_signatures:
 parts.append(f"Siblings: {chunk.sibling_signatures[:200]}")
 parts.append(chunk.content)
 return "\n".join(parts)
class GitDiffError(Exception):
 """git diff 操作失败时抛出。"""
class DiffAction(Enum):
 """Action to take for a file during incremental sync."""
 ADD = "add"
 UPDATE = "update"
 DELETE = "delete"
 SKIP = "skip"
 RENAME = "rename"
@dataclass
class FileDiff:
 """Represents a file difference for incremental indexing."""
 file_path: str
 action: DiffAction
 old_hash: str | None = None
 new_hash: str | None = None
 old_path: str | None = None
async def _get_head_sha(repo_path: str) -> str:
 """获取仓库当前 HEAD 的 commit SHA。"""
 proc = await asyncio.create_subprocess_exec(
 "git", "rev-parse", "HEAD",
 cwd=repo_path,
 stdout=asyncio.subprocess.PIPE,
 stderr=asyncio.subprocess.PIPE,
 )
 stdout, _ = await asyncio.wait_for(proc.communicate, timeout=10.0)
 if proc.returncode != 0:
 raise GitDiffError("git rev-parse HEAD failed")
 return stdout.decode.strip
async def _is_shallow_clone(repo_path: str) -> bool:
 """检查仓库是否为 shallow clone。"""
 proc = await asyncio.create_subprocess_exec(
 "git", "rev-parse", "--is-shallow-repository",
 cwd=repo_path,
 stdout=asyncio.subprocess.PIPE,
 stderr=asyncio.subprocess.PIPE,
 )
 stdout, _ = await asyncio.wait_for(proc.communicate, timeout=10.0)
 return stdout.decode.strip == "true"
async def _fetch_commit(repo_path: str, sha: str, proxy_url: str | None = None) -> bool:
 """尝试 fetch 指定 commit 到浅克隆仓库。失败返回 False。"""
 cmd: list[str] = ["git"]
 if proxy_url:
 cmd.extend(["-c", f"http.proxy={proxy_url}"])
 cmd.extend(["fetch", "--depth=1", "origin", sha])
 proc = await asyncio.create_subprocess_exec(
 *cmd, cwd=repo_path,
 stdout=asyncio.subprocess.PIPE,
 stderr=asyncio.subprocess.PIPE,
 )
 try:
 await asyncio.wait_for(proc.communicate, timeout=60.0)
 except asyncio.TimeoutError:
 proc.kill
 await proc.communicate
 return False
 return proc.returncode == 0
async def _get_merge_base(repo_path: str, base_ref: str, feature_ref: str) -> str:
 """计算两个分支的 merge-base SHA。"""
 proc = await asyncio.create_subprocess_exec(
 "git", "merge-base", base_ref, feature_ref,
 cwd=repo_path,
 stdout=asyncio.subprocess.PIPE,
 stderr=asyncio.subprocess.PIPE,
 )
 stdout, stderr = await asyncio.wait_for(proc.communicate, timeout=30.0)
 if proc.returncode != 0:
 raise GitDiffError(f"git merge-base failed: {stderr.decode}")
 return stdout.decode.strip
async def _fetch_branch(repo_path: str, branch_name: str, proxy_url: str | None = None) -> bool:
 """Fetch 单个分支引用到本地（不检出）。"""
 cmd: list[str] = ["git"]
 if proxy_url:
 cmd.extend(["-c", f"http.proxy={proxy_url}"])
 cmd.extend(["fetch", "--depth=1", "origin", f"{branch_name}:refs/remotes/origin/{branch_name}"])
 proc = await asyncio.create_subprocess_exec(
 *cmd, cwd=repo_path,
 stdout=asyncio.subprocess.PIPE,
 stderr=asyncio.subprocess.PIPE,
 )
 try:
 await asyncio.wait_for(proc.communicate, timeout=60.0)
 except asyncio.TimeoutError:
 proc.kill
 await proc.communicate
 return False
 return proc.returncode == 0
async def _deepen_for_merge_base(
 repo_path: str, base_ref: str, feature_ref: str, proxy_url: str | None = None,
) -> str:
 """渐进加深 shallow clone 以获取可靠的 merge-base。
 尝试 deepen=50 → deepen=200 → unshallow，最多 3 次。
 失败时回退到 base branch tip-to-tip diff。
 """
 for depth in [50, 200, None]:
 cmd: list[str] = ["git"]
 if proxy_url:
 cmd.extend(["-c", f"http.proxy={proxy_url}"])
 if depth:
 cmd.extend(["fetch", f"--deepen={depth}", "origin"])
 else:
 cmd.extend(["fetch", "--unshallow", "origin"])
 proc = await asyncio.create_subprocess_exec(
 *cmd, cwd=repo_path,
 stdout=asyncio.subprocess.PIPE,
 stderr=asyncio.subprocess.PIPE,
 )
 try:
 await asyncio.wait_for(proc.communicate, timeout=120.0)
 except asyncio.TimeoutError:
 proc.kill
 await proc.communicate
 continue
 try:
 return await _get_merge_base(repo_path, base_ref, feature_ref)
 except GitDiffError:
 continue
 # 全部失败，回退到 base branch 的 tip SHA（tip-to-tip diff）
 logger.warning("merge_base_fallback_to_tip", base=base_ref, feature=feature_ref)
 proc = await asyncio.create_subprocess_exec(
 "git", "rev-parse", f"refs/remotes/origin/{base_ref}",
 cwd=repo_path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
 )
 stdout, _ = await asyncio.wait_for(proc.communicate, timeout=10.0)
 if proc.returncode == 0:
 return stdout.decode.strip
 raise GitDiffError(f"无法获取 merge-base 也无法解析 {base_ref} 的 HEAD")
def _parse_git_diff_output(output: str) -> list[FileDiff]:
 """解析 git diff --name-status --find-renames 输出为 FileDiff 列表。"""
 diffs: list[FileDiff] =
 for line in output.strip.split("\n"):
 if not line.strip:
 continue
 parts = line.split("\t")
 status_code = parts[0]
 if status_code == "A":
 diffs.append(FileDiff(parts[1], DiffAction.ADD))
 elif status_code == "M":
 diffs.append(FileDiff(parts[1], DiffAction.UPDATE))
 elif status_code == "D":
 diffs.append(FileDiff(parts[1], DiffAction.DELETE))
 elif status_code.startswith("R"):
 old_path, new_path = parts[1], parts[2]
 similarity = int(status_code[1:]) if len(status_code) > 1 else 100
 if similarity == 100:
 diffs.append(FileDiff(new_path, DiffAction.RENAME, old_path=old_path))
 else:
 # 内容变更的 rename：拆为 DELETE + ADD
 diffs.append(FileDiff(old_path, DiffAction.DELETE))
 diffs.append(FileDiff(new_path, DiffAction.ADD))
 return diffs
def _build_summary_text(files_added: int, files_modified: int, files_deleted: int) -> str:
 """生成人可读的差异摘要文本。"""
 parts: list[str] =
 if files_added:
 parts.append(f"新增 {files_added} 文件")
 if files_modified:
 parts.append(f"修改 {files_modified} 文件")
 if files_deleted:
 parts.append(f"删除 {files_deleted} 文件")
 if not parts:
 return "无变更"
 return f"本次增量：{'、'.join(parts)}"
class IndexerService:
 """Service for indexing repository code into vector database."""
 def __init__(self, repository_id: str):
 self.repository_id = repository_id
 self.parser = CodeParser
 # Phase: 图谱抽取与写入服务（双轨架构 - per ）
 self._graph_extractor = None # 延迟初始化
 self._graph_writer = None
 def _init_graph_services(self):
 """延迟初始化图谱抽取与写入服务（避免循环导入）。"""
 if self._graph_extractor is None:
 from codegraph.services.orchestrator import GraphExtractor
 from codegraph.services.graph_writer import GraphWriter
 self._graph_extractor = GraphExtractor
 self._graph_writer = GraphWriter
 async def run_full_index(
 self, repo_path: str, *, branch_name: str | None = None,
 ) -> dict[str, Any]:
 """Run full indexing for a repository.
 Args:
 repo_path: Path to the cloned repository
 branch_name: 分支名称，非空时在 payload 中注入分支元数据
 Returns:
 Result dict with status and statistics
 """
 logger.info(
 "starting_full_index",
 repository_id=self.repository_id,
 repo_path=repo_path,
 )
 try:
 # Get embedding dimension from settings
 dimension_setting = await SystemSetting.objects.filter(
 key=SettingKeys.EMBEDDING_DIMENSION
 ).afirst
 vector_size = int(dimension_setting.value) if dimension_setting else 1024
 # 检查是否启用 hybrid search
 hybrid_enabled = await self._is_hybrid_enabled
 # Create collection
 await qdrant_create_collection(self.repository_id, vector_size, hybrid=hybrid_enabled)
 if branch_name:
 await qdrant_create_branch_payload_index(
 QdrantService.get_collection_name(self.repository_id)
 )
 # Scan files
 files = scan_directory(repo_path)
 logger.info("files_scanned", count=len(files))
 # Parse all files
 all_chunks: list[CodeChunk] =
 for file_path in files:
 chunks = self.parser.parse_file(file_path, base_path=repo_path)
 all_chunks.extend(chunks)
 logger.info("chunks_parsed", count=len(all_chunks))
 if not all_chunks:
 await update_index_progress(self.repository_id, 0, 0)
 return {
 "status": "success",
 "files_processed": len(files),
 "chunks_indexed": 0,
 "added": len(files), # 全量索引所有文件视为新增
 }
 # Set total chunks count
 total_chunks = len(all_chunks)
 await update_index_progress(self.repository_id, total_chunks, 0)
 # Progress callback for embedding generation
 async def on_embedding_progress(processed: int, total: int) -> None:
 await update_index_progress(self.repository_id, total, processed)
 # Generate embeddings
 texts_to_embed = [_build_embedding_text(chunk) for chunk in all_chunks]
 embeddings = await EmbeddingService.generate_embeddings_batch(
 texts_to_embed, on_progress=on_embedding_progress
 )
 # 生成 sparse vectors（如果启用 hybrid）
 sparse_vectors: list[dict] | None = None
 if hybrid_enabled:
 sparse_vectors = await sync_to_async(self._generate_sparse_vectors)(texts_to_embed)
 # Prepare points for Qdrant
 points = self._build_points(
 all_chunks, embeddings, sparse_vectors, hybrid_enabled,
 branch_name=branch_name, is_base_branch=branch_name is not None,
 )
 # Upsert to Qdrant in batches
 batch_size = 100
 total_points = len(points)
 await update_write_progress(self.repository_id, total_points, 0)
 for i in range(0, total_points, batch_size):
 batch = points[i: i + batch_size]
 await qdrant_upsert_vectors(self.repository_id, batch)
 await update_write_progress(self.repository_id, total_points, min(i + batch_size, total_points))
 logger.info(
 "indexing_complete",
 repository_id=self.repository_id,
 chunks_indexed=len(points),
 hybrid=hybrid_enabled,
 )
 # 全量索引后同步 FileIndex 记录：先清空旧记录，再批量创建
 await FileIndex.objects.filter(repository_id=self.repository_id).adelete
 file_hashes: dict[str, str] = {}
 for chunk in all_chunks:
 if chunk.file_path not in file_hashes:
 file_hashes[chunk.file_path] = chunk.file_hash
 file_index_objects = [
 FileIndex(
 repository_id=self.repository_id,
 file_path=fp,
 file_hash=fh,
 )
 for fp, fh in file_hashes.items
 ]
 if file_index_objects:
 await FileIndex.objects.abulk_create(
 file_index_objects,
 update_conflicts=True,
 update_fields=["file_hash"],
 unique_fields=["repository", "file_path"],
 )
 # 创建/更新 RepositoryBranchIndex 记录并传播 stale
 if branch_name:
 await self._update_branch_index_record(
 repo_path=repo_path,
 branch_name=branch_name,
 is_base_branch=True,
 points_count=len(points),
 )
 # Phase: 图谱轨写入 —— 在向量轨完成之后异步执行
 # per: 图谱失败不阻塞，异常在 _extract_and_write_graph 内部被捕获
 await self._extract_and_write_graph(
 repo_path=repo_path,
 file_paths=files,
 repository_id=self.repository_id,
 )
 # Phase (per ): 异步构建仓库摘要索引，失败不回滚索引
 try:
 from codegraph.services.repo_summary_builder import RepoSummaryBuilder
 await RepoSummaryBuilder.build(repository_id=self.repository_id)
 except Exception:
 logger.warning(
 "repo_summary_build_failed",
 repository_id=self.repository_id,
 exc_info=True,
 )
 return {
 "status": "success",
 "files_processed": len(files),
 "chunks_indexed": len(points),
 "added": len(files), # 全量索引所有文件视为新增
 }
 except Exception as e:
 logger.error(
 "indexing_failed",
 repository_id=self.repository_id,
 error=str(e),
 )
 raise
 async def _update_branch_index_record(
 self,
 *,
 repo_path: str,
 branch_name: str,
 is_base_branch: bool,
 points_count: int,
 ) -> None:
 """创建/更新 RepositoryBranchIndex 记录，base 分支索引后触发 overlay stale 传播。"""
 head_sha = await _get_head_sha(repo_path)
 await RepositoryBranchIndex.objects.aupdate_or_create(
 repository_id=self.repository_id,
 branch_name=branch_name,
 defaults={
 "is_base_branch": is_base_branch,
 "head_sha": head_sha,
 "last_indexed_commit_sha": head_sha,
 "last_indexed_at": timezone.now,
 "is_stale": False,
 "status": BranchIndexStatus.INDEXED,
 "effective_chunks_count": points_count,
 "collection_name": QdrantService.get_collection_name(self.repository_id),
 },
 )
 if is_base_branch:
 stale_count = await RepositoryBranchIndex.objects.filter(
 repository_id=self.repository_id,
 is_base_branch=False,
 ).aupdate(is_stale=True)
 if stale_count:
 logger.info(
 "overlays_marked_stale",
 repository_id=self.repository_id,
 count=stale_count,
 )
 async def run_branch_index(
 self, repo_path: str, branch_name: str, repository: Repository,
 ) -> dict[str, Any]:
 """功能分支 overlay 索引：merge-base + diff → overlay collection。
 无差异时标记 inherited_from_base，不创建 overlay。
 Args:
 repo_path: 克隆仓库路径
 branch_name: 功能分支名称
 repository: 仓库 ORM 实例
 Returns:
 Result dict with status/stats
 Raises:
 BranchOverlayLimitExceeded: overlay 数量超过硬上限
 GitDiffError: git 操作失败
 """
 base_branch = repository.base_branch or repository.default_branch
 # overlay 硬上限检查
 overlay_count = await RepositoryBranchIndex.objects.filter(
 repository=repository, is_base_branch=False,
 ).exclude(status=BranchIndexStatus.INHERITED).acount
 if overlay_count >= MAX_OVERLAY_COLLECTIONS_PER_REPO:
 raise BranchOverlayLimitExceeded(
 f"仓库 {repository.name} 已有 {overlay_count} 个 overlay collection，"
 f"超过上限 {MAX_OVERLAY_COLLECTIONS_PER_REPO}"
 )
 # fetch feature branch
 await _fetch_branch(repo_path, branch_name, repository.proxy_url)
 # 获取 merge-base
 is_shallow = await _is_shallow_clone(repo_path)
 feature_ref = f"origin/{branch_name}"
 if is_shallow:
 merge_base_sha = await _deepen_for_merge_base(
 repo_path, base_branch, feature_ref, repository.proxy_url,
 )
 else:
 merge_base_sha = await _get_merge_base(repo_path, base_branch, feature_ref)
 # 获取 feature HEAD SHA
 proc = await asyncio.create_subprocess_exec(
 "git", "rev-parse", feature_ref,
 cwd=repo_path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
 )
 stdout, _ = await asyncio.wait_for(proc.communicate, timeout=10.0)
 if proc.returncode != 0:
 raise GitDiffError(f"无法解析 {feature_ref} 的 HEAD")
 feature_head = stdout.decode.strip
 # git diff
 diff_proc = await asyncio.create_subprocess_exec(
 "git", "diff", "--name-status", "--find-renames", merge_base_sha, feature_head,
 cwd=repo_path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
 )
 diff_stdout, diff_stderr = await asyncio.wait_for(diff_proc.communicate, timeout=30.0)
 if diff_proc.returncode != 0:
 raise GitDiffError(f"git diff failed: {diff_stderr.decode}")
 diffs = _parse_git_diff_output(diff_stdout.decode)
 # 无差异 → inherited_from_base
 if not diffs:
 await RepositoryBranchIndex.objects.aupdate_or_create(
 repository=repository, branch_name=branch_name,
 defaults={
 "status": BranchIndexStatus.INHERITED,
 "merge_base_sha": merge_base_sha,
 "is_base_branch": False,
 "is_stale": False,
 "head_sha": feature_head,
 },
 )
 logger.info("branch_inherited_from_base", branch=branch_name, repository=repository.name)
 return {"status": "inherited", "diff_files": 0}
 # 有差异 → 创建/确保 overlay collection
 collection_name = get_overlay_collection_name(str(repository.id), branch_name)
 dimension_setting = await SystemSetting.objects.filter(
 key=SettingKeys.EMBEDDING_DIMENSION,
 ).afirst
 vector_size = int(dimension_setting.value) if dimension_setting else 1024
 hybrid_enabled = await self._is_hybrid_enabled
 await qdrant_create_collection_by_name(collection_name, vector_size, hybrid=hybrid_enabled)
 await sync_to_async(QdrantService.create_branch_payload_index)(collection_name)
 # checkout feature branch 文件
 checkout_proc = await asyncio.create_subprocess_exec(
 "git", "checkout", feature_ref, "--", ".",
 cwd=repo_path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
 )
 await asyncio.wait_for(checkout_proc.communicate, timeout=60.0)
 # 仅索引 ADD / UPDATE 文件
 files_to_index = [d for d in diffs if d.action in (DiffAction.ADD, DiffAction.UPDATE)]
 points: list[dict] =
 if files_to_index:
 all_chunks: list[CodeChunk] =
 for diff in files_to_index:
 full_path = os.path.join(repo_path, diff.file_path)
 if os.path.exists(full_path):
 chunks = self.parser.parse_file(full_path, base_path=repo_path)
 all_chunks.extend(chunks)
 if all_chunks:
 texts_to_embed = [_build_embedding_text(chunk) for chunk in all_chunks]
 embeddings = await EmbeddingService.generate_embeddings_batch(texts_to_embed)
 sparse_vectors: list[dict] | None = None
 if hybrid_enabled:
 sparse_vectors = await sync_to_async(self._generate_sparse_vectors)(texts_to_embed)
 points = self._build_points(
 all_chunks, embeddings, sparse_vectors, hybrid_enabled,
 branch_name=branch_name, is_base_branch=False,
 )
 # upsert to overlay collection
 batch_size = 100
 for i in range(0, len(points), batch_size):
 batch = points[i: i + batch_size]
 await qdrant_upsert_vectors_by_name(collection_name, batch)
 # 记录 BranchFileIndex
 branch_index, _ = await RepositoryBranchIndex.objects.aupdate_or_create(
 repository=repository, branch_name=branch_name,
 defaults={
 "is_base_branch": False,
 "head_sha": feature_head,
 "merge_base_sha": merge_base_sha,
 "last_indexed_commit_sha": feature_head,
 "last_indexed_at": timezone.now,
 "is_stale": False,
 "status": BranchIndexStatus.INDEXED,
 "effective_chunks_count": len(points),
 "collection_name": collection_name,
 },
 )
 await BranchFileIndex.objects.filter(branch_index=branch_index).adelete
 file_index_objs = [
 BranchFileIndex(
 branch_index=branch_index,
 file_path=d.file_path,
 change_type=d.action.value,
 )
 for d in diffs
 ]
 if file_index_objs:
 await BranchFileIndex.objects.abulk_create(file_index_objs)
 logger.info(
 "branch_overlay_index_complete",
 branch=branch_name,
 repository=repository.name,
 diff_files=len(diffs),
 indexed_files=len(files_to_index),
 chunks=len(points),
 )
 # Phase: 图谱轨写入
 if files_to_index:
 graph_files = [d.file_path for d in files_to_index]
 await self._extract_and_write_graph(
 repo_path=repo_path,
 file_paths=graph_files,
 repository_id=self.repository_id,
 )
 return {
 "status": "indexed",
 "diff_files": len(diffs),
 "indexed_files": len(files_to_index),
 "chunks_indexed": len(points),
 }
 async def _ensure_collection(self) -> None:
 """确保 Qdrant collection 存在，不存在则创建。"""
 dimension_setting = await SystemSetting.objects.filter(
 key=SettingKeys.EMBEDDING_DIMENSION
 ).afirst
 vector_size = int(dimension_setting.value) if dimension_setting else 1024
 hybrid_enabled = await self._is_hybrid_enabled
 await qdrant_create_collection(self.repository_id, vector_size, hybrid=hybrid_enabled)
 async def run_git_diff_index(
 self,
 repo_path: str,
 from_sha: str,
 to_sha: str,
 *,
 branch_name: str | None = None,
 is_base_branch: bool = False,
 ) -> dict[str, Any]:
 """基于 git diff 的增量索引。
 Args:
 repo_path: 克隆仓库路径
 from_sha: 上次索引的 commit SHA
 to_sha: 当前 HEAD SHA
 branch_name: 分支名称，非空时在 payload 中注入分支元数据
 is_base_branch: 是否为 base 分支
 Returns:
 Result dict with status and statistics
 Raises:
 GitDiffError: git diff 命令执行失败
 """
 logger.info(
 "starting_git_diff_index",
 repository_id=self.repository_id,
 from_sha=from_sha,
 to_sha=to_sha,
 )
 await self._ensure_collection
 # 执行 git diff
 proc = await asyncio.create_subprocess_exec(
 "git", "diff", "--name-status", "--find-renames", from_sha, to_sha,
 cwd=repo_path,
 stdout=asyncio.subprocess.PIPE,
 stderr=asyncio.subprocess.PIPE,
 )
 stdout, stderr = await asyncio.wait_for(proc.communicate, timeout=30.0)
 if proc.returncode != 0:
 raise GitDiffError(f"git diff failed: {stderr.decode}")
 diffs = _parse_git_diff_output(stdout.decode)
 if not diffs:
 logger.info("no_changes_detected", repository_id=self.repository_id)
 return {"status": "success", "added": 0, "updated": 0, "deleted": 0, "renamed": 0}
 stats: dict[str, int] = {"added": 0, "updated": 0, "deleted": 0, "renamed": 0}
 # 处理删除
 for diff in diffs:
 if diff.action == DiffAction.DELETE:
 await qdrant_delete_by_file_path(self.repository_id, diff.file_path)
 await FileIndex.objects.filter(
 repository_id=self.repository_id, file_path=diff.file_path
 ).adelete
 stats["deleted"] += 1
 # 处理 rename（仅元数据更新）
 for diff in diffs:
 if diff.action == DiffAction.RENAME and diff.old_path:
 await qdrant_update_file_path(
 self.repository_id, diff.old_path, diff.file_path
 )
 stats["renamed"] += 1
 # 处理新增和修改
 files_to_index = [
 d for d in diffs if d.action in (DiffAction.ADD, DiffAction.UPDATE)
 ]
 if files_to_index:
 for diff in files_to_index:
 if diff.action == DiffAction.UPDATE:
 await qdrant_delete_by_file_path(self.repository_id, diff.file_path)
 stats["updated"] += 1
 else:
 stats["added"] += 1
 all_chunks: list[CodeChunk] =
 for diff in files_to_index:
 full_path = os.path.join(repo_path, diff.file_path)
 if os.path.exists(full_path):
 chunks = self.parser.parse_file(full_path, base_path=repo_path)
 all_chunks.extend(chunks)
 if all_chunks:
 total_chunks = len(all_chunks)
 await update_index_progress(self.repository_id, total_chunks, 0)
 async def on_embedding_progress(processed: int, total: int) -> None:
 await update_index_progress(self.repository_id, total, processed)
 texts_to_embed = [
 _build_embedding_text(chunk) for chunk in all_chunks
 ]
 embeddings = await EmbeddingService.generate_embeddings_batch(
 texts_to_embed, on_progress=on_embedding_progress
 )
 # 生成 sparse vectors（如果启用 hybrid）
 hybrid_enabled = await self._is_hybrid_enabled
 sparse_vectors: list[dict] | None = None
 if hybrid_enabled:
 sparse_vectors = await sync_to_async(self._generate_sparse_vectors)(texts_to_embed)
 points = self._build_points(
 all_chunks, embeddings, sparse_vectors, hybrid_enabled,
 branch_name=branch_name, is_base_branch=is_base_branch,
 )
 batch_size = 100
 total_points = len(points)
 await update_write_progress(self.repository_id, total_points, 0)
 for i in range(0, total_points, batch_size):
 batch = points[i: i + batch_size]
 await qdrant_upsert_vectors(self.repository_id, batch)
 await update_write_progress(
 self.repository_id,
 total_points,
 min(i + batch_size, total_points),
 )
 logger.info(
 "git_diff_indexing_complete",
 repository_id=self.repository_id,
 stats=stats,
 )
 # 同步 FileIndex 记录：新增/修改的文件更新 hash
 for diff in files_to_index:
 full_path = os.path.join(repo_path, diff.file_path)
 if os.path.exists(full_path):
 new_hash = compute_file_hash(full_path)
 await FileIndex.objects.aupdate_or_create(
 repository_id=self.repository_id,
 file_path=diff.file_path,
 defaults={"file_hash": new_hash},
 )
 # 更新 RepositoryBranchIndex 记录
 if branch_name:
 total_points = sum(stats.get(k, 0) for k in ("added", "updated"))
 await self._update_branch_index_record(
 repo_path=repo_path,
 branch_name=branch_name,
 is_base_branch=is_base_branch,
 points_count=total_points,
 )
 # Phase: 图谱轨写入
 graph_files = [d.file_path for d in files_to_index]
 if graph_files:
 await self._extract_and_write_graph(
 repo_path=repo_path,
 file_paths=graph_files,
 repository_id=self.repository_id,
 )
 return {"status": "success", **stats}
 async def run_incremental_index(
 self,
 repo_path: str,
 *,
 branch_name: str | None = None,
 is_base_branch: bool = False,
 ) -> dict[str, Any]:
 """Run incremental indexing for a repository.
 Args:
 repo_path: Path to the cloned repository
 branch_name: 分支名称，非空时在 payload 中注入分支元数据
 is_base_branch: 是否为基础分支
 Returns:
 Result dict with status and statistics
 """
 logger.info(
 "starting_incremental_index",
 repository_id=self.repository_id,
 )
 try:
 await self._ensure_collection
 # DB 级文件去重——从 FileIndex 查询已索引文件的 hash，替代 Qdrant hash 比较
 stored_records = {
 fp: fh
 async for fp, fh in FileIndex.objects.filter(
 repository_id=self.repository_id
 ).values_list("file_path", "file_hash")
 }
 stored_hashes: dict[str, str] = stored_records
 # Scan local files and compute hashes
 files = scan_directory(repo_path)
 local_hashes: dict[str, str] = {}
 for file_path in files:
 relative_path = os.path.relpath(file_path, repo_path)
 local_hashes[relative_path] = compute_file_hash(file_path)
 # Compute diff
 diffs = self._compute_diff(stored_hashes, local_hashes)
 stats = {"added": 0, "updated": 0, "deleted": 0, "skipped": 0}
 # Process deletions
 for diff in diffs:
 if diff.action == DiffAction.DELETE:
 await qdrant_delete_by_file_path(self.repository_id, diff.file_path)
 stats["deleted"] += 1
 elif diff.action == DiffAction.SKIP:
 stats["skipped"] += 1
 # Process additions and updates
 files_to_index = [
 diff for diff in diffs if diff.action in (DiffAction.ADD, DiffAction.UPDATE)
 ]
 if files_to_index:
 # For updates, delete old vectors first
 for diff in files_to_index:
 if diff.action == DiffAction.UPDATE:
 await qdrant_delete_by_file_path(self.repository_id, diff.file_path)
 stats["updated"] += 1
 else:
 stats["added"] += 1
 # Parse and index new/updated files
 all_chunks: list[CodeChunk] =
 for diff in files_to_index:
 full_path = os.path.join(repo_path, diff.file_path)
 chunks = self.parser.parse_file(full_path, base_path=repo_path)
 all_chunks.extend(chunks)
 if all_chunks:
 # Set total chunks count
 total_chunks = len(all_chunks)
 await update_index_progress(self.repository_id, total_chunks, 0)
 # Progress callback for embedding generation
 async def on_embedding_progress(processed: int, total: int) -> None:
 await update_index_progress(self.repository_id, total, processed)
 # Generate embeddings
 texts_to_embed = [
 _build_embedding_text(chunk) for chunk in all_chunks
 ]
 embeddings = await EmbeddingService.generate_embeddings_batch(
 texts_to_embed, on_progress=on_embedding_progress
 )
 # 生成 sparse vectors（如果启用 hybrid）
 hybrid_enabled = await self._is_hybrid_enabled
 sparse_vectors: list[dict] | None = None
 if hybrid_enabled:
 sparse_vectors = await sync_to_async(self._generate_sparse_vectors)(texts_to_embed)
 points = self._build_points(
 all_chunks, embeddings, sparse_vectors, hybrid_enabled,
 branch_name=branch_name, is_base_branch=is_base_branch,
 )
 batch_size = 100
 total_points = len(points)
 await update_write_progress(self.repository_id, total_points, 0)
 for i in range(0, total_points, batch_size):
 batch = points[i: i + batch_size]
 await qdrant_upsert_vectors(self.repository_id, batch)
 await update_write_progress(self.repository_id, total_points, min(i + batch_size, total_points))
 logger.info(
 "incremental_indexing_complete",
 repository_id=self.repository_id,
 stats=stats,
 )
 # 同步 FileIndex 记录
 # 删除已移除的文件记录
 for diff in diffs:
 if diff.action == DiffAction.DELETE:
 await FileIndex.objects.filter(
 repository_id=self.repository_id, file_path=diff.file_path
 ).adelete
 # 新增/修改文件更新记录
 for diff in diffs:
 if diff.action in (DiffAction.ADD, DiffAction.UPDATE):
 new_hash = local_hashes.get(diff.file_path, "")
 if new_hash:
 await FileIndex.objects.aupdate_or_create(
 repository_id=self.repository_id,
 file_path=diff.file_path,
 defaults={"file_hash": new_hash},
 )
 # Phase: 图谱轨写入
 if files_to_index:
 graph_files = [d.file_path for d in files_to_index]
 await self._extract_and_write_graph(
 repo_path=repo_path,
 file_paths=graph_files,
 repository_id=self.repository_id,
 )
 # Phase (per ): 异步构建仓库摘要索引，失败不回滚索引
 try:
 from codegraph.services.repo_summary_builder import RepoSummaryBuilder
 await RepoSummaryBuilder.build(repository_id=self.repository_id)
 except Exception:
 logger.warning(
 "repo_summary_build_failed",
 repository_id=self.repository_id,
 exc_info=True,
 )
 # （方案 A）： — 返回变更文件路径列表，供调用方持久化到 IndexHistory
 added_file_paths = [d.file_path for d in diffs if d.action == DiffAction.ADD]
 modified_file_paths = [d.file_path for d in diffs if d.action == DiffAction.UPDATE]
 deleted_file_paths = [d.file_path for d in diffs if d.action == DiffAction.DELETE]
 return {
 "status": "success",
 **stats,
 "added_files": added_file_paths,
 "modified_files": modified_file_paths,
 "deleted_files": deleted_file_paths,
 }
 except Exception as e:
 logger.error(
 "incremental_indexing_failed",
 repository_id=self.repository_id,
 error=str(e),
 )
 raise
 def _compute_diff(
 self,
 stored_hashes: dict[str, str],
 local_hashes: dict[str, str],
 ) -> list[FileDiff]:
 """Compute diff between stored and local files."""
 diffs =
 # Check local files against stored
 for file_path, local_hash in local_hashes.items:
 if file_path not in stored_hashes:
 diffs.append(FileDiff(file_path, DiffAction.ADD, new_hash=local_hash))
 elif stored_hashes[file_path] != local_hash:
 diffs.append(
 FileDiff(
 file_path,
 DiffAction.UPDATE,
 old_hash=stored_hashes[file_path],
 new_hash=local_hash,
 )
 )
 else:
 diffs.append(FileDiff(file_path, DiffAction.SKIP))
 # Check for deleted files
 for file_path in stored_hashes:
 if file_path not in local_hashes:
 diffs.append(
 FileDiff(file_path, DiffAction.DELETE, old_hash=stored_hashes[file_path])
 )
 return diffs
 @staticmethod
 async def _is_hybrid_enabled -> bool:
 """检查是否启用 hybrid search。"""
 setting = await SystemSetting.objects.filter(
 key=SettingKeys.HYBRID_SEARCH_ENABLED
 ).afirst
 return bool(setting and setting.value == "true")
 @staticmethod
 def _generate_sparse_vectors(texts: list[str]) -> list[dict]:
 """生成 BM25 稀疏向量（同步方法，需要 sync_to_async 调用）。"""
 from services.sparse_encoder import SparseEncoderService
 return SparseEncoderService.encode_batch(texts)
 async def _extract_and_write_graph(
 self, repo_path: str, file_paths: list[str], repository_id: str,
 ) -> dict[str, Any]:
 """对指定文件列表执行图谱抽取并写入 Django ORM（双轨架构图谱轨）。
 该方法在向量轨写入（Qdrant upsert）完成后调用，对每个 tree-sitter
 支持的文件进行 AST 解析 + 四维抽取 + 批量入库。
 per: 图谱抽取失败不阻塞向量轨。单个文件失败仅记 warning。
 per: 复用 CodeParser 的 tree-sitter parser 获取能力（同一棵 AST）。
 Args:
 repo_path: 克隆仓库的本地路径
 file_paths: 需要抽取图谱的文件路径列表（相对路径）
 repository_id: 仓库 UUID 字符串
 Returns:
 dict: {"files_processed": N, "files_failed": N, "symbols": N, ...}
 """
 import os
 from django.conf import settings
 from codegraph.extractors.base import FileContext
 from services.code_parser import CodeParser as _CodeParser, TREESITTER_LANGUAGES
 # Feature flag 门控（per NYQUIST 维度 8: 配置可控）
 if not getattr(settings, "ENABLE_CODEGRAPH", False):
 logger.debug("codegraph_disabled_by_feature_flag")
 return {"files_processed": 0, "files_failed": 0, "reason": "disabled"}
 # 延迟初始化图谱服务
 self._init_graph_services
 stats: dict[str, Any] = {
 "files_processed": 0,
 "files_failed": 0,
 "total_symbols": 0,
 "total_imports": 0,
 "total_calls": 0,
 "total_endpoints": 0,
 }
 # 创建独立的 CodeParser 实例用于图谱抽取（复用其 tree-sitter parser）
 # 不污染 self.parser 的状态
 graph_parser = _CodeParser
 for file_path in file_paths:
 full_path = os.path.join(repo_path, file_path)
 if not os.path.exists(full_path) or not os.path.isfile(full_path):
 continue
 # 确定语言
 language = self._detect_language_from_path(file_path)
 if not language or language not in TREESITTER_LANGUAGES:
 # 非 tree-sitter 支持的语言，跳过图谱抽取
 continue
 # 文件大小过滤（per RESEARCH.md §H.2: MAX_FILE_BYTES = 5MB）
 file_size = os.path.getsize(full_path)
 MAX_FILE_BYTES = 5 * 1024 * 1024 # 5MB
 if file_size > MAX_FILE_BYTES:
 logger.warning(
 "graph_extraction_skipped_file_too_large",
 file_path=file_path,
 size_bytes=file_size,
 )
 continue
 # 读取源文件内容
 try:
 with open(full_path, "r", encoding="utf-8", errors="replace") as f:
 source = f.read
 except Exception as e:
 logger.warning(
 "graph_extraction_read_failed",
 file_path=file_path,
 error=str(e),
 )
 stats["files_failed"] += 1
 continue
 # 跳过空文件和纯二进制文件（已在上层 filtered，此处兜底）
 if not source.strip:
 continue
 # AST 解析 + 四维抽取 + 写入（per: 单文件失败不阻塞）
 try:
 # 获取 tree-sitter parser
 parser = graph_parser._get_tree_sitter_parser(language)
 if parser is None:
 continue
 tree = parser.parse(bytes(source, "utf-8"))
 # 构建 FileContext
 module_path = file_path.replace("/", ".").replace(".py", "")
 ctx = FileContext(
 file_path=file_path,
 language=language,
 repository_id=repository_id,
 module_path=module_path,
 )
 # 四维抽取
 bundle = self._graph_extractor.extract_all(tree, source, ctx)
 # 批量入库
 result = await self._graph_writer.write_bundle(repository_id, bundle)
 stats["files_processed"] += 1
 stats["total_symbols"] += result.get("symbols", 0)
 stats["total_imports"] += result.get("imports", 0)
 stats["total_calls"] += result.get("calls", 0)
 stats["total_endpoints"] += result.get("endpoints", 0)
 except Exception as e:
 logger.warning(
 "graph_extraction_failed",
 file_path=file_path,
 error=str(e),
 )
 stats["files_failed"] += 1
 # 不重新抛出 —— 图谱失败不影响向量轨
 if stats["files_processed"] > 0:
 logger.info(
 "graph_extraction_batch_complete",
 repository_id=repository_id,
 processed=stats["files_processed"],
 failed=stats["files_failed"],
 symbols=stats["total_symbols"],
 imports=stats["total_imports"],
 calls=stats["total_calls"],
 endpoints=stats["total_endpoints"],
 )
 return stats
 @staticmethod
 def _detect_language_from_path(file_path: str) -> str | None:
 """从文件扩展名检测编程语言（CodeParser 的简化版）。"""
 ext = file_path.rsplit(".", 1)[-1].lower if "." in file_path else ""
 _EXT_LANG_MAP = {
 "py": "python",
 "js": "javascript",
 "ts": "typescript",
 "tsx": "typescript",
 "go": "go",
 "css": "css",
 "html": "html",
 "json": "json",
 }
 return _EXT_LANG_MAP.get(ext)
 @staticmethod
 def _build_points(
 chunks: list[CodeChunk],
 embeddings: list[list[float] | None],
 sparse_vectors: list[dict] | None,
 hybrid: bool,
 *,
 branch_name: str | None = None,
 is_base_branch: bool = False,
 ) -> list[dict]:
 """构建 Qdrant points，支持 hybrid 和非 hybrid 模式。"""
 points: list[dict] =
 for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
 if embedding is None:
 continue
 payload: dict[str, Any] = {
 "file_path": chunk.file_path,
 "file_hash": chunk.file_hash,
 "language": chunk.language,
 "node_type": chunk.node_type,
 "start_line": chunk.start_line,
 "end_line": chunk.end_line,
 "content": chunk.content,
 "context_header": chunk.context_header,
 }
 if branch_name is not None:
 payload["branch_name"] = branch_name
 payload["is_base_branch"] = is_base_branch
 if hybrid and sparse_vectors and i < len(sparse_vectors):
 from qdrant_client.http.models import SparseVector
 sparse = sparse_vectors[i]
 vector: Any = {
 "dense": embedding,
 "sparse": SparseVector(
 indices=sparse["indices"],
 values=sparse["values"],
 ),
 }
 else:
 vector = embedding
 points.append({
 "id": str(uuid.uuid4),
 "vector": vector,
 "payload": payload,
 })
 return points
async def clone_and_index_repository(
 repository_id: str,
 *,
 history_id: str | None = None,
 branch: str | None = None,
) -> dict[str, Any]:
 """Clone repository and run indexing.
 This is the main entry point for indexing a repository.
 Args:
 repository_id: 仓库 ID
 history_id: 可选的 IndexHistory 记录 ID，完成时更新状态
 branch: 可选的功能分支名称，非空时走 overlay 索引路径
 """
 from common.encryption import decrypt_value
 async def get_repository_data:
 """Fetch repository and extract all needed data in async context."""
 repo = await Repository.objects.select_related("credential").aget(id=repository_id)
 credential = getattr(repo, "credential", None)
 token = None
 if credential and credential.encrypted_token:
 token = decrypt_value(credential.encrypted_token)
 return {
 "repository": repo,
 "git_url": repo.git_url,
 "proxy_url": repo.proxy_url,
 "token": token,
 }
 async def update_repository_status(repo, status, error=None, last_indexed_at=None):
 await repo.arefresh_from_db
 repo.index_status = status
 repo.index_error = error
 if last_indexed_at:
 repo.last_indexed_at = last_indexed_at
 update_fields = ["index_status", "index_error"]
 if last_indexed_at:
 update_fields.append("last_indexed_at")
 await repo.asave(update_fields=update_fields)
 try:
 repo_data = await get_repository_data
 except Repository.DoesNotExist:
 return {"status": "error", "message": "Repository not found"}
 repository = repo_data["repository"]
 git_url = repo_data["git_url"]
 proxy_url = repo_data["proxy_url"]
 token = repo_data["token"]
 # Update status to indexing
 await update_repository_status(repository, IndexStatus.INDEXING)
 temp_dir = None
 try:
 # Create temp directory
 temp_dir = tempfile.mkdtemp(prefix="friday_index_")
 # Build authenticated URL if needed
 if token:
 if git_url.startswith("https://"):
 # https://github.com/user/repo.git -> https://token@github.com/user/repo.git
 git_url = git_url.replace("https://", f"https://{token}@")
 # Clone using git
 clone_cmd = ["git", "clone", "--depth", "1"]
 if not branch:
 clone_cmd.append("--single-branch")
 # Add proxy if configured
 if proxy_url:
 clone_cmd.extend(["-c", f"http.proxy={proxy_url}"])
 clone_cmd.extend([git_url, temp_dir])
 proc = await asyncio.create_subprocess_exec(
 *clone_cmd,
 stdout=asyncio.subprocess.PIPE,
 stderr=asyncio.subprocess.PIPE,
 )
 try:
 _stdout, stderr = await asyncio.wait_for(proc.communicate, timeout=300.0)
 except asyncio.TimeoutError:
 proc.kill
 await proc.communicate
 raise Exception("Git clone timed out after 300s")
 if proc.returncode != 0:
 raise Exception(f"Git clone failed: {stderr.decode}")
 # Run indexing - pass repository_id instead of repository object
 indexer = IndexerService(repository_id)
 head_sha: str | None = None
 last_sha: str | None = None
 fallback_reason: str | None = None
 if branch:
 # 功能分支 overlay 索引路径
 index_result = await indexer.run_branch_index(temp_dir, branch, repository)
 else:
 # 现有 base branch 索引路径
 base_branch = repository.base_branch or repository.default_branch
 # 获取当前 HEAD SHA
 head_sha = await _get_head_sha(temp_dir)
 # 决定索引路径：git diff > 文件哈希比较 > 全量
 last_sha = repository.last_indexed_commit_sha
 # 先检查 collection 是否有数据；如果为空则必须走全量索引
 stored_hashes = await qdrant_get_stored_file_hashes(repository_id)
 collection_has_data = bool(stored_hashes)
 if last_sha and collection_has_data:
 # 尝试 git diff 增量路径
 fetch_ok = await _fetch_commit(temp_dir, last_sha, proxy_url)
 if fetch_ok:
 try:
 index_result = await indexer.run_git_diff_index(
 temp_dir, last_sha, head_sha,
 branch_name=base_branch, is_base_branch=True,
 )
 except GitDiffError as e:
 logger.warning("git_diff_failed_fallback", error=str(e))
 fallback_reason = f"git diff 失败: {e}"
 is_shallow = await _is_shallow_clone(temp_dir)
 if is_shallow:
 logger.info("shallow_clone_fallback_to_full_index")
 index_result = await indexer.run_full_index(
 temp_dir, branch_name=base_branch,
 )
 else:
 index_result = await indexer.run_incremental_index(
 temp_dir, branch_name=base_branch, is_base_branch=True,
 )
 else:
 logger.warning("fetch_commit_failed_fallback", sha=last_sha)
 fallback_reason = f"git fetch {last_sha} 失败"
 is_shallow = await _is_shallow_clone(temp_dir)
 if is_shallow:
 logger.info("shallow_clone_fallback_to_full_index")
 index_result = await indexer.run_full_index(
 temp_dir, branch_name=base_branch,
 )
 else:
 index_result = await indexer.run_incremental_index(
 temp_dir, branch_name=base_branch, is_base_branch=True,
 )
 elif collection_has_data:
 index_result = await indexer.run_incremental_index(
 temp_dir, branch_name=base_branch, is_base_branch=True,
 )
 else:
 if last_sha:
 logger.info(
 "collection_empty_fallback_to_full_index",
 repository_id=repository_id,
 last_sha=last_sha,
 )
 fallback_reason = "collection 为空，回退到全量索引"
 index_result = await indexer.run_full_index(
 temp_dir, branch_name=base_branch,
 )
 # base 路径：更新 last_indexed_commit_sha
 await Repository.objects.filter(id=repository_id).aupdate(
 last_indexed_commit_sha=head_sha,
 )
 # Update repository status
 from django.utils import timezone
 if not branch:
 await update_repository_status(
 repository,
 IndexStatus.INDEXED,
 last_indexed_at=timezone.now,
 )
 # 更新 IndexHistory 状态为完成
 if history_id:
 from repositories.models import IndexHistory, IndexHistoryStatus
 history_update: dict[str, Any] = {
 "status": IndexHistoryStatus.COMPLETED,
 "finished_at": timezone.now,
 }
 if branch:
 # 分支索引路径：从 index_result 提取分支相关信息
 history_update["summary_text"] = (
 f"分支 {branch}: {index_result.get('status', 'unknown')}"
 f"（diff {index_result.get('diff_files', 0)} 文件）"
 )
 else:
 # base 路径：从 index_result 提取统计信息
 files_added = index_result.get("added", 0)
 files_modified = index_result.get("updated", 0)
 files_deleted = index_result.get("deleted", 0)
 history_update["to_sha"] = head_sha
 history_update["files_added"] = files_added
 history_update["files_modified"] = files_modified
 history_update["files_deleted"] = files_deleted
 history_update["summary_text"] = _build_summary_text(
 files_added, files_modified, files_deleted,
 )
 # （方案 A）： — 持久化变更文件路径列表到 IndexHistory.changed_files
 history_update["changed_files"] = {
 "added": index_result.get("added_files", ),
 "modified": index_result.get("modified_files", ),
 "deleted": index_result.get("deleted_files", ),
 }
 if last_sha:
 history_update["from_sha"] = last_sha
 if fallback_reason:
 history_update["error_message"] = f"[fallback] {fallback_reason}"
 await IndexHistory.objects.filter(id=history_id).aupdate(
 **history_update
 )
 return index_result
 except Exception as e:
 logger.error(
 "clone_and_index_failed",
 repository_id=repository_id,
 error=str(e),
 )
 # Update repository status to failed
 await update_repository_status(repository, IndexStatus.FAILED, error=str(e))
 # 更新 IndexHistory 状态为失败
 if history_id:
 from django.utils import timezone
 from repositories.models import IndexHistory, IndexHistoryStatus
 await IndexHistory.objects.filter(id=history_id).aupdate(
 status=IndexHistoryStatus.FAILED,
 finished_at=timezone.now,
 error_message=str(e)[:2000],
 )
 return {"status": "error", "message": str(e)}
 finally:
 # Clean up temp directory
 if temp_dir and os.path.exists(temp_dir):
 shutil.rmtree(temp_dir, ignore_errors=True)
