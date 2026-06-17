"""OpenAI 协议兼容层 Views（contract/contract/contract）。

端点：
  POST /v1/chat/completions  — ChatCompletionsView
  GET  /v1/models            — ModelsView
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import structlog
from adrf.views import APIView
from django.http import StreamingHttpResponse
from rest_framework.response import Response

from agents.langchain_runner import LangChainAgentRunner, LangChainRunnerConfig
from services.provider_config import ProviderConfigService, ProviderMissingError

from .adapter import OpenAICompatAdapter
from .anthropic_adapter import aggregate_message
from .auth import OptionalBearerTokenAuth
from .error_handlers import anthropic_error_response, openai_error_response
from .progress import retrieval_to_progress
from .request_handler import anthropic_to_openai_messages, prepare_messages_with_meta
from .schemas import AnthropicMessagesRequestSerializer, ChatCompletionsRequestSerializer

logger = structlog.get_logger(__name__)


async def _build_runner() -> LangChainAgentRunner | None:
    """解析系统默认 Provider 凭证，构建 LangChainAgentRunner。

    失败时返回 None，调用方应返回 503。
    """
    result = await ProviderConfigService.aresolve_or_error()
    if isinstance(result, ProviderMissingError):
        logger.warning("compat_provider_missing", code=result.code, action=result.recommended_action)
        return None
    resolved = result
    model = (resolved.extra or {}).get("default_model", "") or ""
    runner_config = LangChainRunnerConfig(
        resolved=resolved,
        model=model,
    )
    return LangChainAgentRunner(runner_config)


class ChatCompletionsView(APIView):
    """POST /v1/chat/completions — OpenAI 协议兼容入口（contract、contract、contract）。"""

    # Pitfall 6：不走 JWT，避免 SynchronousOnlyOperation（async 上下文禁止 lazy-load user）
    authentication_classes: list = []
    permission_classes = [OptionalBearerTokenAuth]

    async def post(self, request: Any) -> Any:  # type: ignore[override]
        serializer = ChatCompletionsRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return openai_error_response(
                message=str(serializer.errors),
                type_="invalid_request_error",
                code="bad_request",
                http_status=400,
            )
        params = serializer.validated_data

        # Plan 02：统一经 prepare_messages_with_meta 取 (lc_messages, 检索结果)。
        # 两路径共用同一 lc_messages（非流式 content 零回归命门）；retr 仅供流式派生
        # prelude progress，非流式忽略（不合成检索 progress、不污染 message.content）。
        lc_messages, retr = await prepare_messages_with_meta(
            messages=params["messages"],
            repository_ids=[str(rid) for rid in params.get("repository_ids") or []],
            project_id=str(params["project_id"]) if params.get("project_id") else None,
        )

        runner = await _build_runner()
        if runner is None:
            return openai_error_response(
                message="LLM 提供商凭证未配置，请在系统设置添加 Provider Credential",
                type_="server_error",
                code="provider_not_configured",
                http_status=503,
            )

        # Q-02 方案 (a)：固定 friday-default，忽略客户端传入 model 字段
        model_name = "friday-default"

        if params.get("stream"):
            # 命中 RAG（retr 非 None）时派生 prelude progress（正文前以 reasoning_content 透出）。
            prelude_texts = retrieval_to_progress(retr)
            return StreamingHttpResponse(
                streaming_content=self._stream_chunks(
                    runner, lc_messages, params, model_name, prelude_texts
                ),
                content_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        # 非流式：解析 SSE chunk 聚合为完整 ChatCompletion 响应（work item 修复）
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        finish_reason: str = "stop"
        usage: dict | None = None

        async for chunk_bytes in OpenAICompatAdapter.translate_stream(
            runner, lc_messages, model=model_name, include_usage=True
        ):
            line = chunk_bytes.decode().removeprefix("data: ").strip()
            if not line or line == "[DONE]":
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            for choice in obj.get("choices") or []:
                delta = choice.get("delta", {})
                if delta.get("content"):
                    text_parts.append(delta["content"])
                if delta.get("reasoning_content"):
                    reasoning_parts.append(delta["reasoning_content"])
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
            if obj.get("usage"):
                usage = obj["usage"]

        message: dict = {"role": "assistant", "content": "".join(text_parts)}
        if reasoning_parts:
            message["reasoning_content"] = "".join(reasoning_parts)

        return Response({
            "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }],
            "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    async def _stream_chunks(
        self,
        runner: LangChainAgentRunner,
        lc_messages: list,
        params: dict,
        model_name: str,
        prelude_texts: list[str] | None = None,
    ):
        """逐 chunk yield OpenAI SSE 格式字节流（含末尾 [DONE] 哨兵）（work item）。

        Plan 02：``prelude_texts`` 非空时（命中 RAG），adapter 在正文前以
        ``reasoning_content`` 透出检索 progress；None/空则与现状逐字等价。
        """
        include_usage: bool = (params.get("stream_options") or {}).get("include_usage", False)
        try:
            async for chunk_bytes in OpenAICompatAdapter.translate_stream(
                runner, lc_messages, model=model_name, include_usage=include_usage,
                prelude_texts=prelude_texts,
            ):
                yield chunk_bytes
            yield b"data: [DONE]\n\n"
        except Exception as exc:
            logger.exception("compat_stream_error", error=str(exc))
            yield (
                b"data: "
                + json.dumps({
                    "error": {
                        "message": "内部错误",
                        "type": "server_error",
                        "code": "internal_error",
                    }
                }, ensure_ascii=False).encode()
                + b"\n\n"
            )
            yield b"data: [DONE]\n\n"


class MessagesView(APIView):
    """POST /v1/messages — Anthropic Messages 兼容入口（57-01，本 plan 仅非流式）。

    复用 Phase 56 内核：``anthropic_to_openai_messages`` 规整 → ``prepare_messages_with_meta``
    检索注入 → ``aggregate_message`` 聚合为 Anthropic Messages 形状。流式分支留 Plan 02。
    """

    # Pitfall 6 / P-9：不走 JWT，避免 async 上下文 lazy-load user 的 SynchronousOnlyOperation
    authentication_classes: list = []
    permission_classes = [OptionalBearerTokenAuth]

    async def post(self, request: Any) -> Any:  # type: ignore[override]
        serializer = AnthropicMessagesRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return anthropic_error_response(
                message=str(serializer.errors),
                type_="invalid_request_error",
                http_status=400,
            )
        params = serializer.validated_data

        # 规整 Anthropic 形状 → OpenAI [{role, content}]，再完全委托既有检索内核。
        # retr 非流式忽略（不合成 trace、不污染 content，P-8）。
        oai_messages = anthropic_to_openai_messages(params.get("system"), params["messages"])
        lc_messages, _retr = await prepare_messages_with_meta(
            messages=oai_messages,
            repository_ids=[str(rid) for rid in params.get("repository_ids") or []],
            project_id=str(params["project_id"]) if params.get("project_id") else None,
        )

        runner = await _build_runner()
        if runner is None:
            return anthropic_error_response(
                message="LLM 提供商凭证未配置，请在系统设置添加 Provider Credential",
                type_="api_error",
                http_status=503,
            )

        # Q-02 方案 (a)：固定 friday-default，忽略客户端传入 model 字段
        model_name = "friday-default"

        # TODO(Plan 02 57-02)：流式 SSE 接线 + thinking block prelude。本 plan stream=True
        # 暂走非流式聚合（功能可用，Plan 02 替换为真正的 Anthropic SSE 双行帧流）。
        try:
            message = await aggregate_message(runner, lc_messages, model=model_name)
        except RuntimeError as exc:
            return anthropic_error_response(
                message=str(exc),
                type_="api_error",
                http_status=500,
            )
        return Response(message)


class ModelsView(APIView):
    """GET /v1/models — 列出可用模型（contract）。"""

    authentication_classes: list = []
    permission_classes = [OptionalBearerTokenAuth]

    async def get(self, request: Any) -> Response:  # type: ignore[override]
        # 固定返回 friday-default；后续 implementation+ 扩展为动态读取 ProviderCredential
        return Response({
            "object": "list",
            "data": [
                {
                    "id": "friday-default",
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "friday",
                }
            ],
        })
