"""Reranker API service for search result re-ranking."""

from typing import Any

import httpx
import structlog

from system.models import SettingKeys, SystemSetting

logger = structlog.get_logger(__name__)


class RerankerService:
    """调用外部 Reranker API 对搜索结果进行精排。"""

    @classmethod
    async def get_config(cls) -> dict[str, Any]:
        """从系统设置读取 reranker 配置。"""
        from common.encryption import decrypt_value

        config: dict[str, Any] = {}

        enabled = await SystemSetting.objects.filter(key=SettingKeys.RERANKER_ENABLED).afirst()
        config["enabled"] = enabled.value == "true" if enabled and enabled.value else False

        api_url = await SystemSetting.objects.filter(key=SettingKeys.RERANKER_API_URL).afirst()
        config["api_url"] = api_url.value if api_url else None

        api_key_setting = await SystemSetting.objects.filter(key=SettingKeys.RERANKER_API_KEY).afirst()
        if api_key_setting and api_key_setting.value:
            if api_key_setting.is_encrypted:
                config["api_key"] = decrypt_value(api_key_setting.value)
            else:
                config["api_key"] = api_key_setting.value
        else:
            config["api_key"] = None

        model = await SystemSetting.objects.filter(key=SettingKeys.RERANKER_MODEL).afirst()
        config["model"] = model.value if model else "BAAI/bge-reranker-v2-m3"

        top_n = await SystemSetting.objects.filter(key=SettingKeys.RERANKER_TOP_N).afirst()
        config["top_n"] = int(top_n.value) if top_n and top_n.value else 10

        return config

    @classmethod
    async def is_enabled(cls) -> bool:
        """检查 reranker 是否已配置并启用。"""
        config = await cls.get_config()
        return bool(config.get("enabled") and config.get("api_url"))

    @classmethod
    async def rerank(
        cls,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """调用 Reranker API 对文档重排序。

        Args:
            query: 用户查询
            documents: 候选文档内容列表
            top_n: 返回 top N 个结果，None 则使用系统配置

        Returns:
            排序后的结果列表 [{"index": int, "relevance_score": float}, ...]
        """
        config = await cls.get_config()
        api_url = config.get("api_url")

        if not api_url:
            logger.error("reranker_api_url_not_configured")
            # fail-open：返回空列表让调用方保留召回原序，绝不用 0 分打乱排序。
            return []

        if not documents:
            return []

        if top_n is None:
            top_n = config.get("top_n", 10)

        model = config.get("model", "BAAI/bge-reranker-v2-m3")
        api_key = config.get("api_key")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Jina/Cohere 兼容格式
                request_body: dict[str, Any] = {
                    "model": model,
                    "query": query,
                    "documents": documents,
                    "top_n": top_n,
                }

                response = await client.post(api_url, json=request_body, headers=headers)
                response.raise_for_status()
                try:
                    data = response.json()
                except ValueError:
                    logger.error(
                        "reranker_non_json_response",
                        content_type=response.headers.get("content-type", ""),
                        body=response.text[:200],
                    )
                    return []

                # 解析响应：支持 Jina/Cohere 格式
                results: list[dict[str, Any]] = []
                if "results" in data:
                    for item in data["results"]:
                        results.append({
                            "index": item.get("index", 0),
                            "relevance_score": item.get("relevance_score", 0.0),
                        })
                elif "data" in data:
                    # OpenAI-compatible 格式
                    for item in data["data"]:
                        results.append({
                            "index": item.get("index", 0),
                            "relevance_score": item.get("relevance_score", item.get("score", 0.0)),
                        })
                else:
                    logger.error("unexpected_reranker_response", data=str(data)[:200])
                    return []

                return results

        except httpx.HTTPError as e:
            logger.error("reranker_api_failed", error=str(e))
            return []

    @classmethod
    async def test_connection(cls) -> dict[str, Any]:
        """使用已保存配置测试 reranker 连接。"""
        config = await cls.get_config()
        api_url = config.get("api_url")

        if not api_url:
            return {"status": "error", "message": "Reranker API URL 未配置"}

        return await cls._test_with_params(
            api_url, config.get("model", "BAAI/bge-reranker-v2-m3"), config.get("api_key")
        )

    @classmethod
    async def test_connection_with_config(
        cls, api_url: str, model: str, api_key: str | None = None
    ) -> dict[str, Any]:
        """使用提供的配置测试连接（保存前测试）。"""
        return await cls._test_with_params(api_url, model, api_key)

    @classmethod
    async def _test_with_params(
        cls, api_url: str, model: str, api_key: str | None = None
    ) -> dict[str, Any]:
        """执行测试 rerank 请求。"""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    api_url,
                    json={
                        "model": model,
                        "query": "test query",
                        "documents": ["test document 1", "test document 2"],
                        "top_n": 2,
                    },
                    headers=headers,
                )
                if response.status_code != 200:
                    body = response.text[:200]
                    return {"status": "error", "message": f"HTTP {response.status_code}: {body}"}

                content_type = response.headers.get("content-type", "")
                try:
                    data = response.json()
                except ValueError:
                    snippet = response.text[:200].replace("\n", " ")
                    hint = ""
                    if "html" in content_type.lower() or snippet.lstrip().startswith("<"):
                        hint = "（返回了 HTML 页面，API 地址可能不对，Rerank 端点通常以 /v1/rerank 结尾）"
                    return {
                        "status": "error",
                        "message": f"响应不是 JSON{hint}。content-type={content_type}；片段: {snippet}",
                    }

                if isinstance(data, dict) and ("results" in data or "data" in data):
                    return {"status": "healthy", "model": model}
                return {"status": "error", "message": f"响应格式不支持: {str(data)[:200]}"}

        except httpx.HTTPError as e:
            return {"status": "error", "message": f"连接失败: {e}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
