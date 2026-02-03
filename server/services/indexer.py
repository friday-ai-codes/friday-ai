"""Incremental indexer service for code repositories."""
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
import structlog
from asgiref.sync import sync_to_async
from repositories.models import IndexStatus, Repository
from services.code_parser import CodeChunk, CodeParser, compute_file_hash, scan_directory
from services.embedding import EmbeddingService
from services.qdrant_service import QdrantService
from system.models import SettingKeys, SystemSetting
# Wrap sync Qdrant operations for use in async context
@sync_to_async
def qdrant_create_collection(repository_id: str, vector_size: int) -> bool:
 return QdrantService.create_collection(repository_id, vector_size=vector_size)
@sync_to_async
def qdrant_get_stored_file_hashes(repository_id: str) -> dict[str, str]:
 return QdrantService.get_stored_file_hashes(repository_id)
@sync_to_async
def qdrant_delete_by_file_path(repository_id: str, file_path: str) -> bool:
 return QdrantService.delete_by_file_path(repository_id, file_path)
@sync_to_async
def qdrant_upsert_vectors(repository_id: str, points: list[dict]) -> bool:
 return QdrantService.upsert_vectors(repository_id, points)
@sync_to_async
def update_index_progress(repository_id: str, total: int, processed: int) -> None:
 """Update indexing progress in database."""
 Repository.objects.filter(id=repository_id).update(
 index_total_chunks=total,
 index_processed_chunks=processed,
 )
@sync_to_async
def update_write_progress(repository_id: str, total: int, processed: int) -> None:
 """Update Qdrant write progress in database."""
 Repository.objects.filter(id=repository_id).update(
 index_write_total=total,
 index_write_processed=processed,
 )
logger = structlog.get_logger(__name__)
class DiffAction(Enum):
 """Action to take for a file during incremental sync."""
 ADD = "add"
 UPDATE = "update"
 DELETE = "delete"
 SKIP = "skip"
@dataclass
class FileDiff:
 """Represents a file difference for incremental indexing."""
 file_path: str
 action: DiffAction
 old_hash: str | None = None
 new_hash: str | None = None
class IndexerService:
 """Service for indexing repository code into vector database."""
 def __init__(self, repository_id: str):
 self.repository_id = repository_id
 self.parser = CodeParser
 async def run_full_index(self, repo_path: str) -> dict[str, Any]:
 """Run full indexing for a repository.
 Args:
 repo_path: Path to the cloned repository
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
 @sync_to_async
 def get_embedding_dimension:
 dimension_setting = SystemSetting.objects.filter(
 key=SettingKeys.EMBEDDING_DIMENSION
 ).first
 return int(dimension_setting.value) if dimension_setting else 1024
 vector_size = await get_embedding_dimension
 # Create collection
 await qdrant_create_collection(self.repository_id, vector_size)
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
 }
 # Set total chunks count
 total_chunks = len(all_chunks)
 await update_index_progress(self.repository_id, total_chunks, 0)
 # Progress callback for embedding generation
 async def on_embedding_progress(processed: int, total: int) -> None:
 await update_index_progress(self.repository_id, total, processed)
 # Generate embeddings
 texts_to_embed = [f"{chunk.context_header}\n{chunk.content}" for chunk in all_chunks]
 embeddings = await EmbeddingService.generate_embeddings_batch(
 texts_to_embed, on_progress=on_embedding_progress
 )
 # Prepare points for Qdrant
 points =
 for i, (chunk, embedding) in enumerate(zip(all_chunks, embeddings)):
 if embedding is None:
 continue
 points.append(
 {
 "id": str(uuid.uuid4),
 "vector": embedding,
 "payload": {
 "file_path": chunk.file_path,
 "file_hash": chunk.file_hash,
 "language": chunk.language,
 "node_type": chunk.node_type,
 "start_line": chunk.start_line,
 "end_line": chunk.end_line,
 "content": chunk.content,
 "context_header": chunk.context_header,
 },
 }
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
 )
 return {
 "status": "success",
 "files_processed": len(files),
 "chunks_indexed": len(points),
 }
 except Exception as e:
 logger.error(
 "indexing_failed",
 repository_id=self.repository_id,
 error=str(e),
 )
 raise
 async def run_incremental_index(self, repo_path: str) -> dict[str, Any]:
 """Run incremental indexing for a repository.
 Args:
 repo_path: Path to the cloned repository
 Returns:
 Result dict with status and statistics
 """
 logger.info(
 "starting_incremental_index",
 repository_id=self.repository_id,
 )
 try:
 # Get stored file hashes from Qdrant
 stored_hashes = await qdrant_get_stored_file_hashes(self.repository_id)
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
 f"{chunk.context_header}\n{chunk.content}" for chunk in all_chunks
 ]
 embeddings = await EmbeddingService.generate_embeddings_batch(
 texts_to_embed, on_progress=on_embedding_progress
 )
 # Prepare and upsert points
 points =
 for chunk, embedding in zip(all_chunks, embeddings):
 if embedding is None:
 continue
 points.append(
 {
 "id": str(uuid.uuid4),
 "vector": embedding,
 "payload": {
 "file_path": chunk.file_path,
 "file_hash": chunk.file_hash,
 "language": chunk.language,
 "node_type": chunk.node_type,
 "start_line": chunk.start_line,
 "end_line": chunk.end_line,
 "content": chunk.content,
 "context_header": chunk.context_header,
 },
 }
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
async def clone_and_index_repository(repository_id: str) -> dict[str, Any]:
 """Clone repository and run indexing.
 This is the main entry point for indexing a repository.
 """
 from common.encryption import decrypt_value
 @sync_to_async
 def get_repository_data:
 """Fetch repository and extract all needed data in sync context."""
 repo = Repository.objects.select_related("credential").get(id=repository_id)
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
 @sync_to_async
 def update_repository_status(repo, status, error=None, last_indexed_at=None):
 # Refresh from db to avoid stale state
 repo.refresh_from_db
 repo.index_status = status
 repo.index_error = error
 if last_indexed_at:
 repo.last_indexed_at = last_indexed_at
 update_fields = ["index_status", "index_error"]
 if last_indexed_at:
 update_fields.append("last_indexed_at")
 repo.save(update_fields=update_fields)
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
 import subprocess
 clone_cmd = ["git", "clone", "--depth", "1", "--single-branch"]
 # Add proxy if configured
 if proxy_url:
 clone_cmd.extend(["-c", f"http.proxy={proxy_url}"])
 clone_cmd.extend([git_url, temp_dir])
 result = subprocess.run(
 clone_cmd,
 capture_output=True,
 text=True,
 timeout=300,
 )
 if result.returncode != 0:
 raise Exception(f"Git clone failed: {result.stderr}")
 # Run indexing - pass repository_id instead of repository object
 indexer = IndexerService(repository_id)
 # Check if collection exists (incremental) or not (full)
 stored_hashes = await qdrant_get_stored_file_hashes(repository_id)
 if stored_hashes:
 index_result = await indexer.run_incremental_index(temp_dir)
 else:
 index_result = await indexer.run_full_index(temp_dir)
 # Update repository status
 await update_repository_status(
 repository,
 IndexStatus.INDEXED,
 last_indexed_at=datetime.now,
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
 return {"status": "error", "message": str(e)}
 finally:
 # Clean up temp directory
 if temp_dir and os.path.exists(temp_dir):
 shutil.rmtree(temp_dir, ignore_errors=True)
