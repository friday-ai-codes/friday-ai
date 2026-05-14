"""Qdrant vector database client service."""
import asyncio
from collections.abc import Callable
from typing import Any, TypeVar
import httpx
import structlog
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from system.models import SettingKeys, SystemSetting
logger = structlog.get_logger(__name__)
T = TypeVar("T")
class QdrantService:
 """Service for interacting with Qdrant vector database."""
 _client: QdrantClient | None = None
 @classmethod
 def _get_config_sync(cls) -> dict[str, Any]:
 """Get Qdrant configuration from system settings (sync, for client init)."""
 config = {}
 url_setting = SystemSetting.objects.filter(key=SettingKeys.QDRANT_URL).first
 config["url"] = url_setting.value if url_setting else "http://localhost:6333"
 api_key_setting = SystemSetting.objects.filter(key=SettingKeys.QDRANT_API_KEY).first
 if api_key_setting and api_key_setting.value:
 from common.encryption import decrypt_value
 config["api_key"] = decrypt_value(api_key_setting.value)
 return config
 @classmethod
 async def get_config(cls) -> dict[str, Any]:
 """Get Qdrant configuration from system settings (async)."""
 config = {}
 url_setting = await SystemSetting.objects.filter(key=SettingKeys.QDRANT_URL).afirst
 config["url"] = url_setting.value if url_setting else "http://localhost:6333"
 api_key_setting = await SystemSetting.objects.filter(
 key=SettingKeys.QDRANT_API_KEY
 ).afirst
 if api_key_setting and api_key_setting.value:
 from common.encryption import decrypt_value
 config["api_key"] = decrypt_value(api_key_setting.value)
 return config
 @classmethod
 def get_client(cls) -> QdrantClient:
 """Get or create Qdrant client."""
 if cls._client is None:
 import os
 config = cls._get_config_sync
 url = config.get("url", "http://localhost:6333")
 proxy_vars = {k: v for k, v in os.environ.items if "proxy" in k.lower}
 logger.debug("qdrant_client_init", url=url, proxy_env=proxy_vars)
 cls._client = QdrantClient(
 url=url,
 api_key=config.get("api_key"),
 # 禁止 httpx 自动加载系统/环境代理（macOS 系统代理、HTTP(S)_PROXY 等）。
 # Qdrant 通常部署在内网 / Tailscale，走代理会被反代成 502。
 trust_env=False,
 # 关闭启动时的版本兼容探测，避免走系统代理失败时产生噪音警告。
 check_compatibility=False,
 # qdrant-client SDK 默认 timeout=5s，对大 batch upsert 太短：
 # 100 个点 + hybrid sparse + dense 512+ 维 → 单次写入轻易超 5s，
 # 触发 httpx.ReadTimeout / socket.timeout → indexer 顶层 catch
 # → index_status=FAILED & error="timed out"，灾难性后果。
 # 设 60s 给冷启动 & 偶发抖动留余量。
 timeout=60,
 )
 return cls._client
 @classmethod
 def reset_client(cls) -> None:
 """Reset client (useful when config changes)."""
 if cls._client is not None:
 try:
 cls._client.close
 except Exception as exc:
 logger.warning("qdrant_client_close_failed", error=str(exc))
 finally:
 cls._client = None
 @staticmethod
 def _is_bad_file_descriptor(exc: OSError) -> bool:
 return getattr(exc, "errno", None) == 9 or "Bad file descriptor" in str(exc)
 @classmethod
 def _classify_failure(cls, exc: BaseException) -> str:
 text = str(exc).lower
 if isinstance(exc, OSError) and cls._is_bad_file_descriptor(exc):
 return "bad_file_descriptor"
 if "timed out" in text or "timeout" in text:
 return "timeout"
 if isinstance(exc, ConnectionError):
 return "connection_error"
 if isinstance(exc, OSError) and getattr(exc, "errno", None) in {
 54, # ECONNRESET
 32, # EPIPE
 104, # ECONNRESET on Linux
 61, # ECONNREFUSED
 111, # ECONNREFUSED on Linux
 }:
 return "connection_error"
 if isinstance(exc, httpx.HTTPError):
 return "http_error"
 if isinstance(exc, UnexpectedResponse):
 return "unexpected_response"
 if isinstance(exc, ResponseHandlingException):
 return "response_handling_error"
 return "unknown"
 @classmethod
 def _call_with_bad_fd_retry(
 cls,
 operation: str,
 fn: Callable[[QdrantClient], T],
 ) -> T:
 """执行一次 Qdrant 操作；坏 fd 时重建 client 并重试一次。"""
 try:
 return fn(cls.get_client)
 except OSError as exc:
 if not cls._is_bad_file_descriptor(exc):
 raise
 logger.warning(
 "qdrant_bad_fd_retry",
 operation=operation,
 reason="bad_file_descriptor",
 error=str(exc),
 )
 cls.reset_client
 return fn(cls.get_client)
 @classmethod
 def health_check(cls) -> dict[str, Any]:
 """Check Qdrant service health.
 关键不变量：**绝不能在 health 路径上 reset 已缓存的 client**。
 历史事故：定期健康检查触发 reset_client → 关掉了正在 upsert 的
 httpx 连接池 → 在飞中的 PUT /points 已被 Qdrant 200 返回，但 Python
 端连接已死 → httpx 等满 60s 抛 ResponseHandlingException("timed out")，
 最终在 indexer 顶层显示成"写入向量库失败或超时"。
 正确做法：复用缓存 client；只有在 get_collections 抛连接级错误时
 才尝试 reset + 重建一次。配置变更通过 SystemSetting post_save
 signal 显式调用 reset_client，而不是靠 health_check 兜底。
 """
 try:
 client = cls.get_client
 info = client.get_collections
 return {
 "status": "healthy",
 "collections_count": len(info.collections),
 }
 except Exception as e:
 reason = cls._classify_failure(e)
 logger.warning(
 "qdrant_health_check_first_attempt_failed",
 reason=reason,
 error=str(e),
 error_type=type(e).__name__,
 )
 # 仅在连接级错误时 reset+重试，避免对正在 upsert 的 client 误伤
 if reason in {
 "bad_file_descriptor",
 "connection_error",
 "timeout",
 "http_error",
 "response_handling_error",
 }:
 cls.reset_client
 try:
 client = cls.get_client
 info = client.get_collections
 return {
 "status": "healthy",
 "collections_count": len(info.collections),
 }
 except Exception as retry_exc:
 logger.error(
 "qdrant_health_check_failed",
 reason=cls._classify_failure(retry_exc),
 error=str(retry_exc),
 error_type=type(retry_exc).__name__,
 )
 return {
 "status": "unhealthy",
 "error": str(retry_exc),
 }
 logger.error("qdrant_health_check_failed", error=str(e))
 return {
 "status": "unhealthy",
 "error": str(e),
 }
 @staticmethod
 def health_check_with_config(
 url: str | None = None, api_key: str | None = None
 ) -> dict[str, Any]:
 """Check Qdrant health with provided config (before saving)."""
 target_url = url or "http://localhost:6333"
 try:
 client = QdrantClient(
 url=target_url,
 api_key=api_key or None,
 trust_env=False,
 check_compatibility=False,
 )
 info = client.get_collections
 client.close
 return {
 "status": "healthy",
 "message": "Qdrant 连接成功",
 "collections_count": len(info.collections),
 }
 except Exception as e:
 reason = QdrantService._classify_failure(e)
 logger.error(
 "qdrant_health_check_with_config_failed",
 url=target_url,
 reason=reason,
 error=str(e),
 error_type=type(e).__name__,
 )
 return {
 "status": "unhealthy",
 "message": f"{type(e).__name__}: {e}",
 "error": str(e),
 "reason": reason,
 }
 @classmethod
 def get_collection_name(cls, repository_id: str) -> str:
 """Generate collection name for a repository."""
 return f"code_index_{repository_id}"
 @classmethod
 def create_collection(
 cls,
 repository_id: str,
 vector_size: int = 1024,
 hybrid: bool = False,
 ) -> bool:
 """Create a collection for repository code index.
 Args:
 repository_id: Repository ID
 vector_size: Dense vector dimension
 hybrid: 是否启用混合检索（同时存储 dense + sparse vectors）
 """
 client = cls.get_client
 collection_name = cls.get_collection_name(repository_id)
 try:
 # Check if collection exists
 collections = client.get_collections
 existing_names = [c.name for c in collections.collections]
 if collection_name in existing_names:
 # 检测现有 collection 是否需要重建（维度变化或 hybrid 模式变化）
 collection_info = client.get_collection(collection_name)
 vectors_config = collection_info.config.params.vectors
 # 判断现有 collection 类型
 if isinstance(vectors_config, dict):
 # Named vectors 模式（hybrid）
 existing_hybrid = True
 existing_size = vectors_config.get(
 "dense", models.VectorParams(size=0, distance=models.Distance.COSINE)
 ).size
 else:
 # 单向量模式（非 hybrid）
 existing_hybrid = False
 existing_size = vectors_config.size # type: ignore[union-attr]
 need_recreate = existing_size != vector_size or existing_hybrid != hybrid
 if need_recreate:
 logger.debug(
 "collection_config_mismatch",
 collection_name=collection_name,
 existing_size=existing_size,
 new_size=vector_size,
 existing_hybrid=existing_hybrid,
 new_hybrid=hybrid,
 )
 client.delete_collection(collection_name=collection_name)
 logger.debug("collection_deleted_for_recreate", collection_name=collection_name)
 else:
 logger.debug("collection_already_exists", collection_name=collection_name)
 return True
 # Create collection
 if hybrid:
 client.create_collection(
 collection_name=collection_name,
 vectors_config={
 "dense": models.VectorParams(
 size=vector_size,
 distance=models.Distance.COSINE,
 ),
 },
 sparse_vectors_config={
 "sparse": models.SparseVectorParams,
 },
 )
 logger.debug("collection_created_hybrid", collection_name=collection_name)
 else:
 client.create_collection(
 collection_name=collection_name,
 vectors_config=models.VectorParams(
 size=vector_size,
 distance=models.Distance.COSINE,
 ),
 )
 logger.debug("collection_created", collection_name=collection_name)
 # Create payload index for filtering
 client.create_payload_index(
 collection_name=collection_name,
 field_name="file_path",
 field_schema=models.PayloadSchemaType.KEYWORD,
 )
 client.create_payload_index(
 collection_name=collection_name,
 field_name="file_hash",
 field_schema=models.PayloadSchemaType.KEYWORD,
 )
 client.create_payload_index(
 collection_name=collection_name,
 field_name="language",
 field_schema=models.PayloadSchemaType.KEYWORD,
 )
 return True
 except UnexpectedResponse as e:
 logger.error("create_collection_failed", error=str(e))
 return False
 @classmethod
 def create_branch_payload_index(cls, collection_name: str) -> bool:
 """为指定 collection 创建 branch_name keyword payload index。"""
 client = cls.get_client
 try:
 client.create_payload_index(
 collection_name=collection_name,
 field_name="branch_name",
 field_schema=models.PayloadSchemaType.KEYWORD,
 )
 return True
 except UnexpectedResponse:
 logger.warning(
 "branch_payload_index_may_exist",
 collection_name=collection_name,
 )
 return False
 @classmethod
 def create_snapshot(cls, repository_id: str) -> str | None:
 """Create a snapshot for repository's collection. Returns snapshot filename."""
 client = cls.get_client
 collection_name = cls.get_collection_name(repository_id)
 try:
 result = client.create_snapshot(collection_name=collection_name)
 return result.name if result else None
 except UnexpectedResponse as e:
 logger.error("create_snapshot_failed", error=str(e))
 return None
 @classmethod
 def delete_collection(cls, repository_id: str) -> bool:
 """Delete a collection for repository."""
 client = cls.get_client
 collection_name = cls.get_collection_name(repository_id)
 try:
 client.delete_collection(collection_name=collection_name)
 logger.debug("collection_deleted", collection_name=collection_name)
 return True
 except UnexpectedResponse as e:
 logger.error("delete_collection_failed", error=str(e))
 return False
 @classmethod
 def get_stored_file_hashes(cls, repository_id: str) -> dict[str, str]:
 """Get all stored file paths and their hashes from collection."""
 collection_name = cls.get_collection_name(repository_id)
 try:
 def _read_hashes(client: QdrantClient) -> dict[str, str]:
 file_hashes: dict[str, str] = {}
 # Scroll through all points to get file_path and file_hash
 offset = None
 while True:
 result = client.scroll(
 collection_name=collection_name,
 scroll_filter=None,
 limit=1000,
 offset=offset,
 with_payload=["file_path", "file_hash"],
 with_vectors=False,
 )
 points, next_offset = result
 for point in points:
 if point.payload:
 file_path = point.payload.get("file_path")
 file_hash = point.payload.get("file_hash")
 if file_path and file_hash:
 file_hashes[file_path] = file_hash
 if next_offset is None:
 break
 offset = next_offset
 return file_hashes
 return cls._call_with_bad_fd_retry("get_stored_file_hashes", _read_hashes)
 except UnexpectedResponse:
 # Collection might not exist
 return {}
 except OSError as e:
 logger.error("get_stored_file_hashes_os_failed", error=str(e))
 return {}
 @classmethod
 def update_file_path(cls, repository_id: str, old_path: str, new_path: str) -> bool:
 """更新指定文件的路径元数据（用于 rename 不重新索引）。"""
 client = cls.get_client
 collection_name = cls.get_collection_name(repository_id)
 try:
 client.set_payload(
 collection_name=collection_name,
 payload={"file_path": new_path},
 points=models.Filter(
 must=[
 models.FieldCondition(
 key="file_path",
 match=models.MatchValue(value=old_path),
 )
 ]
 ),
 )
 return True
 except UnexpectedResponse as e:
 logger.error(
 "update_file_path_failed", error=str(e), old_path=old_path, new_path=new_path
 )
 return False
 @classmethod
 def get_collection_stats(cls, repository_id: str) -> dict[str, Any]:
 """获取仓库索引集合的统计信息（chunk 数、语言分布）。"""
 collection_name = cls.get_collection_name(repository_id)
 try:
 def _collect(client: QdrantClient) -> dict[str, Any]:
 # 检查 collection 是否存在
 collections = client.get_collections
 existing_names = [c.name for c in collections.collections]
 if collection_name not in existing_names:
 return {"exists": False, "points_count": 0, "language_distribution": {}}
 # 精确计数
 count_result = client.count(collection_name=collection_name, exact=True)
 points_count = count_result.count
 # 遍历所有 points 统计语言分布
 language_counts: dict[str, int] = {}
 indexed_files: set[str] = set
 offset = None
 while True:
 points, next_offset = client.scroll(
 collection_name=collection_name,
 scroll_filter=None,
 limit=1000,
 offset=offset,
 with_payload=["language", "file_path"],
 with_vectors=False,
 )
 for point in points:
 if point.payload:
 lang = point.payload.get("language", "unknown")
 language_counts[lang] = language_counts.get(lang, 0) + 1
 fp = point.payload.get("file_path")
 if fp:
 indexed_files.add(fp)
 if next_offset is None:
 break
 offset = next_offset
 return {
 "exists": True,
 "points_count": points_count,
 "language_distribution": language_counts,
 "indexed_files_count": len(indexed_files),
 }
 return cls._call_with_bad_fd_retry("get_collection_stats", _collect)
 except UnexpectedResponse as e:
 logger.error("get_collection_stats_failed", error=str(e))
 return {"exists": False, "points_count": 0, "language_distribution": {}}
 except OSError as e:
 logger.error("get_collection_stats_os_failed", error=str(e))
 return {"exists": False, "points_count": 0, "language_distribution": {}}
 @classmethod
 def check_collection_health(cls, repository_id: str) -> dict[str, Any]:
 """校验仓库索引集合的健康状态。"""
 collection_name = cls.get_collection_name(repository_id)
 try:
 def _check(client: QdrantClient) -> dict[str, Any]:
 collections = client.get_collections
 existing_names = [c.name for c in collections.collections]
 if collection_name not in existing_names:
 return {
 "status": "unhealthy",
 "collection_exists": False,
 "points_count": 0,
 }
 count_result = client.count(collection_name=collection_name, exact=True)
 return {
 "status": "healthy",
 "collection_exists": True,
 "points_count": count_result.count,
 }
 return cls._call_with_bad_fd_retry("check_collection_health", _check)
 except UnexpectedResponse as e:
 logger.error("check_collection_health_failed", error=str(e))
 return {
 "status": "unhealthy",
 "collection_exists": False,
 "points_count": 0,
 "error": str(e),
 }
 except OSError as e:
 logger.error("check_collection_health_os_failed", error=str(e))
 return {
 "status": "unhealthy",
 "collection_exists": False,
 "points_count": 0,
 "error": str(e),
 }
 @classmethod
 def delete_by_file_path(cls, repository_id: str, file_path: str) -> bool:
 """Delete all vectors for a specific file path."""
 client = cls.get_client
 collection_name = cls.get_collection_name(repository_id)
 try:
 client.delete(
 collection_name=collection_name,
 points_selector=models.FilterSelector(
 filter=models.Filter(
 must=[
 models.FieldCondition(
 key="file_path",
 match=models.MatchValue(value=file_path),
 )
 ]
 )
 ),
 )
 return True
 except UnexpectedResponse as e:
 logger.error("delete_by_file_path_failed", error=str(e), file_path=file_path)
 return False
 @classmethod
 def upsert_vectors(
 cls,
 repository_id: str,
 points: list[dict[str, Any]],
 ) -> bool:
 """Upsert vectors to collection.
 Args:
 repository_id: Repository ID
 points: List of points with id, vector, and payload
 """
 collection_name = cls.get_collection_name(repository_id)
 try:
 qdrant_points = [
 models.PointStruct(
 id=p["id"],
 vector=p["vector"],
 payload=p["payload"],
 )
 for p in points
 ]
 def _upsert(client: QdrantClient) -> bool:
 logger.debug(
 "upsert_vectors_start",
 collection_name=collection_name,
 points_count=len(qdrant_points),
 )
 client.upsert(
 collection_name=collection_name,
 points=qdrant_points,
 )
 logger.debug(
 "upsert_vectors_complete",
 collection_name=collection_name,
 points_count=len(qdrant_points),
 )
 return True
 return cls._call_with_bad_fd_retry(
 "upsert_vectors",
 _upsert,
 )
 except UnexpectedResponse as e:
 logger.error(
 "upsert_vectors_failed",
 collection_name=collection_name,
 points_count=len(points),
 reason=cls._classify_failure(e),
 error=str(e),
 error_type=type(e).__name__,
 )
 return False
 except ResponseHandlingException as e:
 logger.error(
 "upsert_vectors_response_handling_failed",
 collection_name=collection_name,
 points_count=len(points),
 reason=cls._classify_failure(e),
 error=str(e), error_type=type(e).__name__,
 )
 return False
 except httpx.HTTPError as e:
 # 网络层异常（timeout / connect refused / read error）：
 # 不让单次 batch 抖动炸掉整次索引（这是 indexer 'timed out' 失败的元凶）。
 # 调用方需要感知失败并跳过 FileIndex 锚点写入，避免数据丢失被静默吞掉。
 logger.error(
 "upsert_vectors_network_failed",
 collection_name=collection_name,
 points_count=len(points),
 reason=cls._classify_failure(e),
 error=str(e), error_type=type(e).__name__,
 )
 return False
 except OSError as e:
 logger.error(
 "upsert_vectors_os_failed",
 collection_name=collection_name,
 points_count=len(points),
 reason=cls._classify_failure(e),
 error=str(e), error_type=type(e).__name__,
 )
 return False
 @classmethod
 def search(
 cls,
 repository_id: str,
 query_vector: list[float],
 top_k: int = 30,
 filters: dict[str, Any] | None = None,
 ) -> list[dict[str, Any]]:
 """Search for similar vectors.
 Args:
 repository_id: Repository ID
 query_vector: Query embedding vector
 top_k: Number of results to return
 filters: Optional filters (language, file_pattern)
 Returns:
 List of search results with score and payload
 """
 client = cls.get_client
 collection_name = cls.get_collection_name(repository_id)
 # Build filter conditions
 filter_conditions =
 if filters:
 if "language" in filters:
 filter_conditions.append(
 models.FieldCondition(
 key="language",
 match=models.MatchValue(value=filters["language"]),
 )
 )
 query_filter = None
 if filter_conditions:
 query_filter = models.Filter(must=filter_conditions)
 try:
 results = client.query_points(
 collection_name=collection_name,
 query=query_vector,
 query_filter=query_filter,
 limit=top_k,
 with_payload=True,
 )
 return [
 {
 "id": str(r.id),
 "score": r.score,
 "payload": r.payload,
 }
 for r in results.points
 ]
 except UnexpectedResponse as e:
 logger.error("search_failed", error=str(e))
 return
 @classmethod
 def create_collection_by_name(
 cls,
 collection_name: str,
 vector_size: int = 1024,
 hybrid: bool = False,
 ) -> bool:
 """创建指定名称的 collection（用于 overlay branch collection）。
 与 create_collection 逻辑一致但接受 collection_name 而非 repository_id。
 """
 client = cls.get_client
 try:
 collections = client.get_collections
 existing_names = [c.name for c in collections.collections]
 if collection_name in existing_names:
 logger.info("collection_already_exists", collection_name=collection_name)
 return True
 if hybrid:
 client.create_collection(
 collection_name=collection_name,
 vectors_config={
 "dense": models.VectorParams(
 size=vector_size,
 distance=models.Distance.COSINE,
 ),
 },
 sparse_vectors_config={
 "sparse": models.SparseVectorParams,
 },
 )
 else:
 client.create_collection(
 collection_name=collection_name,
 vectors_config=models.VectorParams(
 size=vector_size,
 distance=models.Distance.COSINE,
 ),
 )
 for field in ("file_path", "file_hash", "language", "branch_name"):
 client.create_payload_index(
 collection_name=collection_name,
 field_name=field,
 field_schema=models.PayloadSchemaType.KEYWORD,
 )
 logger.debug("overlay_collection_created", collection_name=collection_name)
 return True
 except UnexpectedResponse as e:
 logger.error("create_collection_by_name_failed", error=str(e))
 return False
 @classmethod
 def ensure_repo_summaries_collection(cls, vector_size: int = 1024) -> bool:
 """确保 repo_summaries collection 存在（hybrid 模式，幂等）。"""
 return cls.create_collection_by_name("repo_summaries", vector_size=vector_size, hybrid=True)
 @classmethod
 def delete_collection_by_name(cls, collection_name: str) -> bool:
 """按名称删除 collection（用于清理 overlay branch collection）。"""
 client = cls.get_client
 try:
 client.delete_collection(collection_name=collection_name)
 logger.debug("overlay_collection_deleted", collection_name=collection_name)
 return True
 except UnexpectedResponse as e:
 logger.error("delete_collection_by_name_failed", error=str(e))
 return False
 @classmethod
 def upsert_vectors_by_name(
 cls,
 collection_name: str,
 points: list[dict[str, Any]],
 ) -> bool:
 """向指定名称的 collection upsert points。"""
 try:
 qdrant_points = [
 models.PointStruct(
 id=p["id"],
 vector=p["vector"],
 payload=p["payload"],
 )
 for p in points
 ]
 def _upsert(client: QdrantClient) -> bool:
 logger.debug(
 "upsert_vectors_by_name_start",
 collection_name=collection_name,
 points_count=len(qdrant_points),
 )
 client.upsert(
 collection_name=collection_name,
 points=qdrant_points,
 )
 logger.debug(
 "upsert_vectors_by_name_complete",
 collection_name=collection_name,
 points_count=len(qdrant_points),
 )
 return True
 return cls._call_with_bad_fd_retry(
 "upsert_vectors_by_name",
 _upsert,
 )
 except UnexpectedResponse as e:
 logger.error(
 "upsert_vectors_by_name_failed",
 collection_name=collection_name,
 points_count=len(points),
 reason=cls._classify_failure(e),
 error=str(e),
 error_type=type(e).__name__,
 )
 return False
 except ResponseHandlingException as e:
 logger.error(
 "upsert_vectors_by_name_response_handling_failed",
 points_count=len(points),
 reason=cls._classify_failure(e),
 error=str(e), error_type=type(e).__name__,
 collection_name=collection_name,
 )
 return False
 except httpx.HTTPError as e:
 logger.error(
 "upsert_vectors_by_name_network_failed",
 points_count=len(points),
 reason=cls._classify_failure(e),
 error=str(e), error_type=type(e).__name__,
 collection_name=collection_name,
 )
 return False
 except OSError as e:
 logger.error(
 "upsert_vectors_by_name_os_failed",
 points_count=len(points),
 reason=cls._classify_failure(e),
 error=str(e), error_type=type(e).__name__,
 collection_name=collection_name,
 )
 return False
 @classmethod
 def _build_filter(cls, filters: dict[str, Any] | None) -> models.Filter | None:
 """构建 Qdrant 查询过滤条件。"""
 filter_conditions =
 if filters:
 if "language" in filters:
 filter_conditions.append(
 models.FieldCondition(
 key="language",
 match=models.MatchValue(value=filters["language"]),
 )
 )
 if filter_conditions:
 return models.Filter(must=filter_conditions)
 return None
 @classmethod
 def search_by_name(
 cls,
 collection_name: str,
 query_vector: list[float],
 top_k: int = 30,
 filters: dict[str, Any] | None = None,
 ) -> list[dict[str, Any]]:
 """按 collection 名称搜索（用于 overlay / 任意已知 collection）。
 与 search 逻辑相同但直接接受 collection_name。
 collection 不存在时返回空列表。
 """
 client = cls.get_client
 query_filter = cls._build_filter(filters)
 try:
 results = client.query_points(
 collection_name=collection_name,
 query=query_vector,
 query_filter=query_filter,
 limit=top_k,
 with_payload=True,
 )
 return [
 {
 "id": str(r.id),
 "score": r.score,
 "payload": r.payload,
 }
 for r in results.points
 ]
 except UnexpectedResponse as e:
 logger.warning("search_by_name_failed", collection_name=collection_name, error=str(e))
 return
 @classmethod
 def hybrid_search_by_name(
 cls,
 collection_name: str,
 query_dense: list[float],
 query_sparse: dict[str, Any],
 top_k: int = 30,
 filters: dict[str, Any] | None = None,
 ) -> list[dict[str, Any]]:
 """按 collection 名称混合检索（dense + sparse RRF 融合）。
 与 hybrid_search 逻辑相同但直接接受 collection_name。
 collection 不存在时返回空列表。
 """
 client = cls.get_client
 query_filter = cls._build_filter(filters)
 try:
 sparse_vector = models.SparseVector(
 indices=query_sparse["indices"],
 values=query_sparse["values"],
 )
 results = client.query_points(
 collection_name=collection_name,
 prefetch=[
 models.Prefetch(
 query=query_dense,
 using="dense",
 limit=top_k,
 filter=query_filter,
 ),
 models.Prefetch(
 query=sparse_vector,
 using="sparse",
 limit=top_k,
 filter=query_filter,
 ),
 ],
 query=models.FusionQuery(fusion=models.Fusion.RRF),
 limit=top_k,
 with_payload=True,
 )
 return [
 {
 "id": str(r.id),
 "score": r.score,
 "payload": r.payload,
 }
 for r in results.points
 ]
 except UnexpectedResponse as e:
 logger.warning(
 "hybrid_search_by_name_failed",
 collection_name=collection_name,
 error=str(e),
 )
 return
 @classmethod
 def hybrid_search(
 cls,
 repository_id: str,
 query_dense: list[float],
 query_sparse: dict[str, Any],
 top_k: int = 30,
 filters: dict[str, Any] | None = None,
 ) -> list[dict[str, Any]]:
 """混合检索：利用 Qdrant prefetch 机制融合 dense + sparse 结果。
 Args:
 repository_id: Repository ID
 query_dense: Dense query vector
 query_sparse: Sparse query vector {"indices": [...], "values": [...]}
 top_k: Number of results to return
 filters: Optional filters
 Returns:
 List of search results with score and payload
 """
 client = cls.get_client
 collection_name = cls.get_collection_name(repository_id)
 # Build filter
 filter_conditions =
 if filters:
 if "language" in filters:
 filter_conditions.append(
 models.FieldCondition(
 key="language",
 match=models.MatchValue(value=filters["language"]),
 )
 )
 query_filter = None
 if filter_conditions:
 query_filter = models.Filter(must=filter_conditions)
 try:
 sparse_vector = models.SparseVector(
 indices=query_sparse["indices"],
 values=query_sparse["values"],
 )
 results = client.query_points(
 collection_name=collection_name,
 prefetch=[
 models.Prefetch(
 query=query_dense,
 using="dense",
 limit=top_k,
 filter=query_filter,
 ),
 models.Prefetch(
 query=sparse_vector,
 using="sparse",
 limit=top_k,
 filter=query_filter,
 ),
 ],
 query=models.FusionQuery(fusion=models.Fusion.RRF),
 limit=top_k,
 with_payload=True,
 )
 return [
 {
 "id": str(r.id),
 "score": r.score,
 "payload": r.payload,
 }
 for r in results.points
 ]
 except UnexpectedResponse as e:
 logger.error("hybrid_search_failed", error=str(e))
 return
 @classmethod
 async def batch_set_payload(
 cls,
 repository_id: str,
 updates: list[tuple[str, dict[str, Any]]],
 *,
 batch_size: int = 500,
 timeout: float = 30.0,
 ) -> None:
 """批量为 Qdrant points 设置 payload（per Phase / ）。
 Pitfall 2 防御核心 API：禁止循环单 set_payload；唯一写入路径是
 client.batch_update_points + SetPayloadOperation。
 Args:
 repository_id: 推导 collection_name（QdrantService.get_collection_name）
 updates: list of (point_id, payload_dict)。SetPayloadOperation 仅 set
 自身 key，既有 payload 其他字段保留（不是 overwrite 语义）
 batch_size: 单次 batch_update_points 提交的 SetPayloadOperation 数量上限
 timeout: 单次 batch wall-clock 上限（秒）；asyncio.wait_for 超时 catch
 + structlog error 不重抛（与 upsert_vectors 同语义，让 indexer 主路
 径继续）
 异常对称 upsert_vectors：UnexpectedResponse / ResponseHandlingException /
 httpx.HTTPError / OSError / TimeoutError 全 catch 并 structlog error 不重抛。
 """
 if not updates:
 return
 collection_name = cls.get_collection_name(repository_id)
 total = len(updates)
 batches = [updates[i: i + batch_size] for i in range(0, total, batch_size)]
 for batch_idx, batch in enumerate(batches):
 ops = [
 models.SetPayloadOperation(
 set_payload=models.SetPayload(
 payload=payload,
 points=[point_id],
 ),
 )
 for point_id, payload in batch
 ]
 def _do_batch(client: QdrantClient, _ops: list[Any] = ops) -> None:
 client.batch_update_points(
 collection_name=collection_name,
 update_operations=_ops,
 wait=False,
 )
 try:
 await asyncio.wait_for(
 asyncio.to_thread(
 cls._call_with_bad_fd_retry, "batch_set_payload", _do_batch
 ),
 timeout=timeout,
 )
 except TimeoutError:
 logger.error(
 "batch_set_payload_timeout",
 collection_name=collection_name,
 batch_index=batch_idx,
 batch_size=len(batch),
 timeout_seconds=timeout,
 )
 except UnexpectedResponse as e:
 logger.error(
 "batch_set_payload_failed",
 collection_name=collection_name,
 batch_index=batch_idx,
 batch_size=len(batch),
 reason=cls._classify_failure(e),
 error=str(e),
 )
 except ResponseHandlingException as e:
 logger.error(
 "batch_set_payload_response_handling_failed",
 collection_name=collection_name,
 batch_index=batch_idx,
 reason=cls._classify_failure(e),
 error=str(e),
 )
 except httpx.HTTPError as e:
 logger.error(
 "batch_set_payload_network_failed",
 collection_name=collection_name,
 batch_index=batch_idx,
 reason=cls._classify_failure(e),
 error=str(e),
 )
 except OSError as e:
 logger.error(
 "batch_set_payload_os_failed",
 collection_name=collection_name,
 batch_index=batch_idx,
 reason=cls._classify_failure(e),
 error=str(e),
 )
 logger.info(
 "batch_set_payload_complete",
 collection_name=collection_name,
 total_updates=total,
 batches=len(batches),
 )
