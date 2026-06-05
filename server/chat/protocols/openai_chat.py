"""OpenAI Chat Completions 协议实现。

使用 /v1/chat/completions 端点进行对话，/v1/models 获取模型列表。
认证方式：Bearer token (Authorization header)。
"""

from __future__ import annotations

import httpx
import structlog

from chat.protocols.base import ProviderProtocol
from chat.services import ChatCompletionResult, ChatMessage, ChatServiceError, Model

logger = structlog.get_logger(__name__)


class OpenAIChatProtocol(ProviderProtocol):
    """OpenAI Chat Completions 协议 (/v1/chat/completions)。"""

    def _get_headers(self) -> dict[str, str]:
        """构建请求头。"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def send_message(
        self,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int = 4096,
    ) -> ChatCompletionResult:
        """通过 /v1/chat/completions 发送对话请求。"""
        url = f"{self.base_url}/v1/chat/completions"
        logger.info("正在发送对话请求", url=url, model=model)

        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers=self._get_headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

                choices = data.get("choices", [])
                if not choices:
                    raise ChatServiceError("API 返回空响应")

                message = choices[0].get("message", {})
                content = message.get("content", "")

                result = ChatCompletionResult(
                    content=content,
                    model=data.get("model", model),
                    usage=data.get("usage"),
                )

                logger.info(
                    "对话请求成功",
                    model=result.model,
                    usage=result.usage,
                )
                return result

        except httpx.TimeoutException:
            logger.error("对话请求超时")
            raise self._handle_timeout()
        except httpx.HTTPStatusError as e:
            logger.error(
                "对话请求 HTTP 错误",
                status_code=e.response.status_code,
            )
            raise self._handle_http_error(e)
        except httpx.RequestError as e:
            logger.error("对话请求网络错误", error=str(e))
            raise self._handle_request_error(e)
        except ChatServiceError:
            raise
        except Exception as e:
            logger.error("对话请求未知错误", error=str(e))
            raise ChatServiceError(f"对话请求失败: {e!s}")

    async def get_models(self) -> list[Model]:
        """通过 /v1/models 获取可用模型列表。"""
        url = f"{self.base_url}/v1/models"
        logger.info("正在获取模型列表", url=url)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=self._get_headers())
                response.raise_for_status()
                data = response.json()

                models = [
                    Model(
                        id=model_data.get("id", ""),
                        name=model_data.get("id", ""),
                        created=model_data.get("created"),
                    )
                    for model_data in data.get("data", [])
                ]

                logger.info("模型列表获取成功", count=len(models))
                return models

        except httpx.TimeoutException:
            logger.error("获取模型列表请求超时")
            raise self._handle_timeout()
        except httpx.HTTPStatusError as e:
            logger.error("获取模型列表 HTTP 错误", status_code=e.response.status_code)
            raise self._handle_http_error(e)
        except httpx.RequestError as e:
            logger.error("获取模型列表网络错误", error=str(e))
            raise self._handle_request_error(e)
        except Exception as e:
            logger.error("获取模型列表未知错误", error=str(e))
            raise ChatServiceError(f"获取模型列表失败: {e!s}")
