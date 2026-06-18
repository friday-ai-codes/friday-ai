"""Embedding API service for generating vector embeddings."""

from typing import Any, Callable

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from system.models import SettingKeys, SystemSetting

logger = structlog.get_logger(__name__)


def _is_rate_limited(exc: BaseException) -> bool:
    """429 / Too Many Requests → 退避重试（embedding 服务限流时等待而非直接失败）。"""
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response is not None
        and exc.response.status_code == 429
    )


@retry(
    retry=retry_if_exception(_is_rate_limited),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(5),
    reraise=True,
)
async def _apost_embedding(
    client: httpx.AsyncClient,
    api_url: str,
    request_body: dict[str, Any],
    headers: dict[str, str],
) -> httpx.Response:
    """POST embedding 请求；遇 429 指数退避重试（允许并发下的限流等待）。"""
    response = await client.post(api_url, json=request_body, headers=headers)
    response.raise_for_status()
    return response


class EmbeddingService:
    """Service for generating embeddings via remote API."""

    @staticmethod
    def _is_multimodal(api_url: str) -> bool:
        return "/embeddings/multimodal" in api_url

    @staticmethod
    def _is_ollama(api_url: str) -> bool:
        return "/api/embeddings" in api_url

    @classmethod
    def _build_request_body(cls, api_url: str, model: str, text: str) -> dict[str, Any]:
        """Build request body according to API type."""
        if cls._is_ollama(api_url):
            return {"model": model, "prompt": text}
        if cls._is_multimodal(api_url):
            return {"model": model, "input": [{"type": "text", "text": text}]}
        return {"model": model, "input": text}

    @classmethod
    def _build_batch_request_body(cls, api_url: str, model: str, texts: list[str]) -> dict[str, Any]:
        """Build batch request body according to API type."""
        if cls._is_multimodal(api_url):
            return {"model": model, "input": [{"type": "text", "text": t} for t in texts]}
        return {"model": model, "input": texts}

    @staticmethod
    def _extract_embedding(data: dict[str, Any]) -> list[float] | None:
        """Extract embedding vector from various response formats."""
        if "data" in data:
            d = data["data"]
            if isinstance(d, list) and len(d) > 0:
                return d[0]["embedding"]
            if isinstance(d, dict) and "embedding" in d:
                return d["embedding"]
        if "embedding" in data:
            return data["embedding"]
        if "embeddings" in data and len(data["embeddings"]) > 0:
            return data["embeddings"][0]
        return None

    @staticmethod
    def _extract_batch_embeddings(data: dict[str, Any]) -> list[list[float]] | None:
        """Extract batch embeddings from various response formats."""
        if "data" in data:
            d = data["data"]
            if isinstance(d, list):
                return [item["embedding"] for item in d]
            if isinstance(d, dict) and "embedding" in d:
                return [d["embedding"]]
        if "embeddings" in data:
            return data["embeddings"]
        return None

    @classmethod
    async def get_config(cls) -> dict[str, Any]:
        """Get embedding configuration from system settings."""
        from common.encryption import decrypt_value

        config: dict[str, Any] = {}

        api_url = await SystemSetting.objects.filter(key=SettingKeys.EMBEDDING_API_URL).afirst()
        config["api_url"] = api_url.value if api_url else None

        api_key_setting = await SystemSetting.objects.filter(key=SettingKeys.EMBEDDING_API_KEY).afirst()
        if api_key_setting and api_key_setting.value:
            if api_key_setting.is_encrypted:
                config["api_key"] = decrypt_value(api_key_setting.value)
            else:
                config["api_key"] = api_key_setting.value
        else:
            config["api_key"] = None

        model = await SystemSetting.objects.filter(key=SettingKeys.EMBEDDING_MODEL).afirst()
        config["model"] = model.value if model else "BAAI/bge-m3"

        dimension = await SystemSetting.objects.filter(key=SettingKeys.EMBEDDING_DIMENSION).afirst()
        config["dimension"] = int(dimension.value) if dimension and dimension.value else 1024

        return config

    @classmethod
    async def generate_embedding(cls, text: str) -> list[float] | None:
        """Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector or None if failed
        """
        config = await cls.get_config()
        api_url = config.get("api_url")

        if not api_url:
            logger.error("embedding_api_url_not_configured")
            return None

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                model = config.get("model", "BAAI/bge-m3")
                api_key = config.get("api_key")

                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                request_body = cls._build_request_body(api_url, model, text)

                response = await _apost_embedding(client, api_url, request_body, headers)
                data = response.json()

                embedding = cls._extract_embedding(data)
                if embedding is not None:
                    return embedding

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
        config = await cls.get_config()
        api_url = config.get("api_url")

        if not api_url:
            logger.error("embedding_api_url_not_configured")
            return [None] * len(texts)

        results: list[list[float] | None] = []
        total = len(texts)
        model = config.get("model", "BAAI/bge-m3")

        headers = {"Content-Type": "application/json"}
        api_key = config.get("api_key")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        one_by_one = cls._is_ollama(api_url) or cls._is_multimodal(api_url)

        if one_by_one:
            async with httpx.AsyncClient(timeout=120.0) as client:
                for idx, text in enumerate(texts):
                    try:
                        request_body = cls._build_request_body(api_url, model, text)
                        response = await _apost_embedding(client, api_url, request_body, headers)
                        data = response.json()

                        embedding = cls._extract_embedding(data)
                        if embedding is not None:
                            results.append(embedding)
                        else:
                            logger.error("unexpected_embedding_response", data=data)
                            results.append(None)

                    except httpx.HTTPError as e:
                        logger.error("embedding_api_failed", error=str(e))
                        results.append(None)

                    if on_progress:
                        await on_progress(idx + 1, total)
        else:
            processed = 0
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]

                try:
                    async with httpx.AsyncClient(timeout=120.0) as client:
                        request_body = cls._build_batch_request_body(api_url, model, batch)
                        response = await _apost_embedding(client, api_url, request_body, headers)
                        data = response.json()

                        batch_embeddings = cls._extract_batch_embeddings(data)
                        if batch_embeddings is not None:
                            results.extend(batch_embeddings)
                        else:
                            logger.error("unexpected_batch_embedding_response", data=data)
                            results.extend([None] * len(batch))

                except httpx.HTTPError as e:
                    logger.error("batch_embedding_api_failed", error=str(e), batch_index=i)
                    results.extend([None] * len(batch))

                processed += len(batch)
                if on_progress:
                    await on_progress(processed, total)

        return results

    @classmethod
    async def test_connection(cls) -> dict[str, Any]:
        """Test embedding API connection."""
        config = await cls.get_config()
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
    async def test_connection_with_config(
        cls, api_url: str, model: str, api_key: str | None = None, expected_dimension: int | None = None
    ) -> dict[str, Any]:
        """Test embedding API connection with provided config (before saving)."""
        try:
            embedding = await cls._generate_embedding_with_config(
                api_url, model, "test connection", api_key
            )
            if embedding is None:
                raise ValueError("未能生成 embedding，请检查 API 配置")
            actual_dim = len(embedding)
            result: dict[str, Any] = {
                "status": "healthy",
                "dimension": actual_dim,
                "model": model,
            }
            if expected_dimension and actual_dim != expected_dimension:
                result["status"] = "warning"
                result["message"] = f"维度不匹配：模型返回 {actual_dim}，配置填写 {expected_dimension}"
            return result
        except Exception as e:
            return {
                "status": "error",
                "message": str(e),
            }

    @classmethod
    async def _generate_embedding_with_config(
        cls, api_url: str, model: str, text: str, api_key: str | None = None
    ) -> list[float] | None:
        """Generate embedding using provided config instead of saved settings."""
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                request_body = cls._build_request_body(api_url, model, text)

                response = await client.post(api_url, json=request_body, headers=headers)
                if response.status_code != 200:
                    body = response.text[:200]
                    msg = f"HTTP {response.status_code}: {body}" if body else f"HTTP {response.status_code}"
                    raise ValueError(msg)

                try:
                    data = response.json()
                except Exception:
                    raise ValueError("响应不是有效的 JSON，请检查 API 地址是否正确（如需添加 /v1/embeddings 后缀）")

                embedding = cls._extract_embedding(data)
                if embedding is not None:
                    return embedding

                logger.error("unexpected_embedding_response", data=data)
                raise ValueError(f"无法解析 embedding 响应: {str(data)[:200]}")

        except httpx.HTTPError as e:
            raise ValueError(f"请求失败: {e}")
