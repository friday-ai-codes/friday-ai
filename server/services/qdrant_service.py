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
 def get_config(cls) -> dict[str, Any]:
 """Get Qdrant configuration from system settings."""
 config = {}
 url_setting = SystemSetting.objects.filter(key=SettingKeys.QDRANT_URL).first
 config["url"] = url_setting.value if url_setting else "http://localhost:6333"
 api_key_setting = SystemSetting.objects.filter(key=SettingKeys.QDRANT_API_KEY).first
 if api_key_setting and api_key_setting.value:
 from common.encryption import decrypt_value
 config["api_key"] = decrypt_value(api_key_setting.value)
 return config
 @classmethod
 def get_client(cls) -> QdrantClient:
 """Get or create Qdrant client."""
 if cls._client is None:
 config = cls.get_config
 cls._client = QdrantClient(
 url=config.get("url", "http://localhost:6333"),
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
 @classmethod
 def get_collection_name(cls, repository_id: str) -> str:
 """Generate collection name for a repository."""
 return f"code_index_{repository_id}"
 @classmethod
 def create_collection(
 cls,
 repository_id: str,
 vector_size: int = 1024,
 ) -> bool:
 """Create a collection for repository code index."""
 client = cls.get_client
 collection_name = cls.get_collection_name(repository_id)
 try:
 # Check if collection exists
 collections = client.get_collections
 existing_names = [c.name for c in collections.collections]
 if collection_name in existing_names:
 logger.info("collection_already_exists", collection_name=collection_name)
 return True
 # Create collection with dense vectors
 client.create_collection(
 collection_name=collection_name,
 vectors_config=models.VectorParams(
 size=vector_size,
 distance=models.Distance.COSINE,
 ),
 )
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
 logger.info("collection_created", collection_name=collection_name)
 return True
 except UnexpectedResponse as e:
 logger.error("create_collection_failed", error=str(e))
 return False
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
