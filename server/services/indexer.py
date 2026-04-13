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
from repositories.models import FileIndex, IndexStatus, Repository
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
 from repositories.models import BranchIndexStatus, RepositoryBranchIndex
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
 return {
 "status": "success",
 **stats,
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
) -> dict[str, Any]:
 """Clone repository and run indexing.
 This is the main entry point for indexing a repository.
 Args:
 repository_id: 仓库 ID
 history_id: 可选的 IndexHistory 记录 ID，完成时更新状态
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
 clone_cmd = ["git", "clone", "--depth", "1", "--single-branch"]
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
 # 获取当前 HEAD SHA
 head_sha = await _get_head_sha(temp_dir)
 # 决定索引路径：git diff > 文件哈希比较 > 全量
 last_sha = repository.last_indexed_commit_sha
 fallback_reason: str | None = None
 # 先检查 collection 是否有数据；如果为空则必须走全量索引
 stored_hashes = await qdrant_get_stored_file_hashes(repository_id)
 collection_has_data = bool(stored_hashes)
 if last_sha and collection_has_data:
 # 尝试 git diff 增量路径
 fetch_ok = await _fetch_commit(temp_dir, last_sha, proxy_url)
 if fetch_ok:
 try:
 index_result = await indexer.run_git_diff_index(
 temp_dir, last_sha, head_sha
 )
 except GitDiffError as e:
 logger.warning("git_diff_failed_fallback", error=str(e))
 fallback_reason = f"git diff 失败: {e}"
 # shallow clone 环境回退到全量索引，否则用增量索引
 is_shallow = await _is_shallow_clone(temp_dir)
 if is_shallow:
 logger.info("shallow_clone_fallback_to_full_index")
 index_result = await indexer.run_full_index(temp_dir)
 else:
 index_result = await indexer.run_incremental_index(temp_dir)
 else:
 logger.warning("fetch_commit_failed_fallback", sha=last_sha)
 fallback_reason = f"git fetch {last_sha} 失败"
 # fetch 失败同样检查是否 shallow clone
 is_shallow = await _is_shallow_clone(temp_dir)
 if is_shallow:
 logger.info("shallow_clone_fallback_to_full_index")
 index_result = await indexer.run_full_index(temp_dir)
 else:
 index_result = await indexer.run_incremental_index(temp_dir)
 elif collection_has_data:
 # 有数据但无 last_sha，走增量比较
 index_result = await indexer.run_incremental_index(temp_dir)
 else:
 # collection 为空或不存在，走全量索引
 if last_sha:
 logger.info(
 "collection_empty_fallback_to_full_index",
 repository_id=repository_id,
 last_sha=last_sha,
 )
 fallback_reason = "collection 为空，回退到全量索引"
 index_result = await indexer.run_full_index(temp_dir)
 # 更新 last_indexed_commit_sha
 await Repository.objects.filter(id=repository_id).aupdate(
 last_indexed_commit_sha=head_sha,
 )
 # Update repository status
 from django.utils import timezone
 await update_repository_status(
 repository,
 IndexStatus.INDEXED,
 last_indexed_at=timezone.now,
 )
 # 更新 IndexHistory 状态为完成
 if history_id:
 from repositories.models import IndexHistory, IndexHistoryStatus
 # 从 index_result 提取统计信息
 files_added = index_result.get("added", 0)
 files_modified = index_result.get("updated", 0)
 files_deleted = index_result.get("deleted", 0)
 history_update: dict[str, Any] = {
 "status": IndexHistoryStatus.COMPLETED,
 "finished_at": timezone.now,
 "to_sha": head_sha,
 "files_added": files_added,
 "files_modified": files_modified,
 "files_deleted": files_deleted,
 "summary_text": _build_summary_text(
 files_added, files_modified, files_deleted
 ),
 }
 if last_sha:
 history_update["from_sha"] = last_sha
 if fallback_reason:
 # 追加 fallback 信息到 error_message（非失败，仅记录）
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
