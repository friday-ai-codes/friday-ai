"""Embedding API service for generating vector embeddings."""
from typing import Any, Callable
import httpx
import structlog
from asgiref.sync import sync_to_async
from system.models import SettingKeys, SystemSetting
logger = structlog.get_logger(__name__)
class EmbeddingService:
 """Service for generating embeddings via remote API."""
 @classmethod
 def get_config_sync(cls) -> dict[str, Any]:
 """Get embedding configuration from system settings (sync version)."""
 config = {}
 api_url = SystemSetting.objects.filter(key=SettingKeys.EMBEDDING_API_URL).first
 config["api_url"] = api_url.value if api_url else None
 model = SystemSetting.objects.filter(key=SettingKeys.EMBEDDING_MODEL).first
 config["model"] = model.value if model else "BAAI/bge-m3"
 dimension = SystemSetting.objects.filter(key=SettingKeys.EMBEDDING_DIMENSION).first
 config["dimension"] = int(dimension.value) if dimension and dimension.value else 1024
 return config
 @classmethod
 async def get_config(cls) -> dict[str, Any]:
 """Get embedding configuration from system settings (async version)."""
 return await sync_to_async(cls.get_config_sync, thread_sensitive=True)
 @classmethod
 async def generate_embedding(cls, text: str) -> list[float] | None:
 """Generate embedding for a single text.
 Args:
 text: Text to embed
 Returns:
 Embedding vector or None if failed
 """
 config = await cls.get_config
 api_url = config.get("api_url")
 if not api_url:
 logger.error("embedding_api_url_not_configured")
 return None
 try:
 async with httpx.AsyncClient(timeout=60.0) as client:
 # Detect API type and build request accordingly
 model = config.get("model", "BAAI/bge-m3")
 # Check if it's Ollama API (contains /api/embeddings)
 if "/api/embeddings" in api_url:
 # Ollama format
 request_body = {
 "model": model,
 "prompt": text,
 }
 else:
 # OpenAI-compatible format
 request_body = {
 "model": model,
 "input": text,
 }
 response = await client.post(
 api_url,
 json=request_body,
 headers={"Content-Type": "application/json"},
 )
 response.raise_for_status
 data = response.json
 # Handle different API response formats
 if "data" in data and len(data["data"]) > 0:
 # OpenAI-compatible format
 return data["data"][0]["embedding"]
 elif "embedding" in data:
 # Ollama / Simple format
 return data["embedding"]
 elif "embeddings" in data and len(data["embeddings"]) > 0:
 # Batch format
 return data["embeddings"][0]
 else:
 logger.error("unexpected_embedding_response", data=data)
 return None
 except httpx.HTTPError as e:
 logger.error("embedding_api_failed", error=str(e))
 return None
 @classmethod
 async def generate_embeddings_batch(
 cls,
 texts: list[str],
 batch_size: int = 32,
 on_progress: Callable[[int, int], Any] | None = None,
 ) -> list[list[float] | None]:
 """Generate embeddings for multiple texts in batches.
 Args:
 texts: List of texts to embed
 batch_size: Number of texts per batch
 on_progress: Optional callback(processed, total) for progress updates
 Returns:
 List of embedding vectors (None for failed items)
 """
 config = await cls.get_config
 api_url = config.get("api_url")
 if not api_url:
 logger.error("embedding_api_url_not_configured")
 return [None] * len(texts)
 results: list[list[float] | None] =
 total = len(texts)
 # Check if it's Ollama API (doesn't support batch)
 is_ollama = "/api/embeddings" in api_url
 if is_ollama:
 # Ollama: process one at a time
 async with httpx.AsyncClient(timeout=120.0) as client:
 for idx, text in enumerate(texts):
 try:
 response = await client.post(
 api_url,
 json={
 "model": config.get("model", "BAAI/bge-m3"),
 "prompt": text,
 },
 headers={"Content-Type": "application/json"},
 )
 response.raise_for_status
 data = response.json
 if "embedding" in data and data["embedding"]:
 results.append(data["embedding"])
 else:
 logger.error("unexpected_ollama_embedding_response", data=data)
 results.append(None)
 except httpx.HTTPError as e:
 logger.error("ollama_embedding_failed", error=str(e))
 results.append(None)
 # Call progress callback
 if on_progress:
 await on_progress(idx + 1, total)
 else:
 # OpenAI-compatible: batch processing
 processed = 0
 for i in range(0, len(texts), batch_size):
 batch = texts[i: i + batch_size]
 try:
 async with httpx.AsyncClient(timeout=120.0) as client:
 response = await client.post(
 api_url,
 json={
 "model": config.get("model", "BAAI/bge-m3"),
 "input": batch,
 },
 headers={"Content-Type": "application/json"},
 )
 response.raise_for_status
 data = response.json
 # Handle different API response formats
 if "data" in data:
 # OpenAI-compatible format
 batch_embeddings = [item["embedding"] for item in data["data"]]
 elif "embeddings" in data:
 # Batch format
 batch_embeddings = data["embeddings"]
 else:
 logger.error("unexpected_batch_embedding_response", data=data)
 batch_embeddings = [None] * len(batch)
 results.extend(batch_embeddings)
 except httpx.HTTPError as e:
 logger.error("batch_embedding_api_failed", error=str(e), batch_index=i)
 results.extend([None] * len(batch))
 # Call progress callback
 processed += len(batch)
 if on_progress:
 await on_progress(processed, total)
 return results
 @classmethod
 async def test_connection(cls) -> dict[str, Any]:
 """Test embedding API connection."""
 config = await cls.get_config
 api_url = config.get("api_url")
 if not api_url:
 return {
 "status": "error",
 "message": "Embedding API URL not configured",
 }
 try:
 embedding = await cls.generate_embedding("test connection")
 if embedding:
 return {
 "status": "healthy",
 "dimension": len(embedding),
 "model": config.get("model"),
 }
 else:
 return {
 "status": "error",
 "message": "Failed to generate test embedding",
 }
 except Exception as e:
 return {
 "status": "error",
 "message": str(e),
 }
 @classmethod
 async def test_connection_with_config(cls, api_url: str, model: str) -> dict[str, Any]:
 """Test embedding API connection with provided config (before saving)."""
 try:
 embedding = await cls._generate_embedding_with_config(api_url, model, "test connection")
 if embedding:
 return {
 "status": "healthy",
 "dimension": len(embedding),
 "model": model,
 }
 else:
 return {
 "status": "error",
 "message": "Failed to generate test embedding",
 }
 except Exception as e:
 return {
 "status": "error",
 "message": str(e),
 }
 @classmethod
 async def _generate_embedding_with_config(cls, api_url: str, model: str, text: str) -> list[float] | None:
 """Generate embedding using provided config instead of saved settings."""
 try:
 async with httpx.AsyncClient(timeout=60.0) as client:
 # Check if it's Ollama API (contains /api/embeddings)
 if "/api/embeddings" in api_url:
 # Ollama format
 request_body = {
 "model": model,
 "prompt": text,
 }
 else:
 # OpenAI-compatible format
 request_body = {
 "model": model,
 "input": text,
 }
 response = await client.post(
 api_url,
 json=request_body,
 headers={"Content-Type": "application/json"},
 )
 response.raise_for_status
 data = response.json
 # Handle different API response formats
 if "data" in data and len(data["data"]) > 0:
 return data["data"][0]["embedding"]
 elif "embedding" in data:
 return data["embedding"]
 elif "embeddings" in data and len(data["embeddings"]) > 0:
 return data["embeddings"][0]
 else:
 logger.error("unexpected_embedding_response", data=data)
 return None
 except httpx.HTTPError as e:
 logger.error("embedding_api_failed", error=str(e))
 return None
