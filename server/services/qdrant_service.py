"""Qdrant vector database client service."""
from typing import Any
import structlog
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse
from system.models import SettingKeys, SystemSetting
logger = structlog.get_logger(__name__)
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
 logger.info("qdrant_client_init", url=url, proxy_env=proxy_vars)
 cls._client = QdrantClient(
 url=url,
 api_key=config.get("api_key"),
 )
 return cls._client
 @classmethod
 def reset_client(cls) -> None:
 """Reset client (useful when config changes)."""
 if cls._client is not None:
 cls._client.close
 cls._client = None
 @classmethod
 def health_check(cls) -> dict[str, Any]:
 """Check Qdrant service health."""
 try:
 # Reset client to use latest config
 cls.reset_client
 client = cls.get_client
 # Get cluster info to verify connection
 info = client.get_collections
 return {
 "status": "healthy",
 "collections_count": len(info.collections),
 }
 except Exception as e:
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
 try:
 client = QdrantClient(url=url or "http://localhost:6333", api_key=api_key or None)
 info = client.get_collections
 client.close
 return {"status": "healthy", "collections_count": len(info.collections)}
 except Exception as e:
 logger.error("qdrant_health_check_with_config_failed", error=str(e))
 return {"status": "unhealthy", "error": str(e)}
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
 logger.info(
 "collection_config_mismatch",
 collection_name=collection_name,
 existing_size=existing_size,
 new_size=vector_size,
 existing_hybrid=existing_hybrid,
 new_hybrid=hybrid,
 )
 client.delete_collection(collection_name=collection_name)
 logger.info("collection_deleted_for_recreate", collection_name=collection_name)
 else:
 logger.info("collection_already_exists", collection_name=collection_name)
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
 logger.info("collection_created_hybrid", collection_name=collection_name)
 else:
 client.create_collection(
 collection_name=collection_name,
 vectors_config=models.VectorParams(
 size=vector_size,
 distance=models.Distance.COSINE,
 ),
 )
 logger.info("collection_created", collection_name=collection_name)
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
 logger.info("collection_deleted", collection_name=collection_name)
 return True
 except UnexpectedResponse as e:
 logger.error("delete_collection_failed", error=str(e))
 return False
 @classmethod
 def get_stored_file_hashes(cls, repository_id: str) -> dict[str, str]:
 """Get all stored file paths and their hashes from collection."""
 client = cls.get_client
 collection_name = cls.get_collection_name(repository_id)
 file_hashes: dict[str, str] = {}
 try:
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
 except UnexpectedResponse:
 # Collection might not exist
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
 client = cls.get_client
 collection_name = cls.get_collection_name(repository_id)
 try:
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
 except UnexpectedResponse as e:
 logger.error("get_collection_stats_failed", error=str(e))
 return {"exists": False, "points_count": 0, "language_distribution": {}}
 @classmethod
 def check_collection_health(cls, repository_id: str) -> dict[str, Any]:
 """校验仓库索引集合的健康状态。"""
 client = cls.get_client
 collection_name = cls.get_collection_name(repository_id)
 try:
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
 except UnexpectedResponse as e:
 logger.error("check_collection_health_failed", error=str(e))
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
 client = cls.get_client
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
 client.upsert(
 collection_name=collection_name,
 points=qdrant_points,
 )
 return True
 except UnexpectedResponse as e:
 logger.error("upsert_vectors_failed", error=str(e))
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
 logger.info("overlay_collection_created", collection_name=collection_name)
 return True
 except UnexpectedResponse as e:
 logger.error("create_collection_by_name_failed", error=str(e))
 return False
 @classmethod
 def delete_collection_by_name(cls, collection_name: str) -> bool:
 """按名称删除 collection（用于清理 overlay branch collection）。"""
 client = cls.get_client
 try:
 client.delete_collection(collection_name=collection_name)
 logger.info("overlay_collection_deleted", collection_name=collection_name)
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
 client = cls.get_client
 try:
 qdrant_points = [
 models.PointStruct(
 id=p["id"],
 vector=p["vector"],
 payload=p["payload"],
 )
 for p in points
 ]
 client.upsert(
 collection_name=collection_name,
 points=qdrant_points,
 )
 return True
 except UnexpectedResponse as e:
 logger.error("upsert_vectors_by_name_failed", error=str(e))
 return False
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
