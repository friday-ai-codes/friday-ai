"""OpenAI 协议兼容层 Views。
端点：
 POST /v1/chat/completions — ChatCompletionsView
 GET /v1/models — ModelsView
"""
from __future__ import annotations
import json
import time
from typing import Any
import structlog
from adrf.views import APIView
from django.http import StreamingHttpResponse
from rest_framework.response import Response
from agents.langchain_runner import LangChainAgentRunner, LangChainRunnerConfig
from services.provider_config import ProviderConfigService, ProviderMissingError
from .adapter import OpenAICompatAdapter
from .auth import OptionalBearerTokenAuth
from .error_handlers import openai_error_response
from .request_handler import prepare_messages
from .schemas import ChatCompletionsRequestSerializer
logger = structlog.get_logger(__name__)
async def _build_runner -> LangChainAgentRunner | None:
 """解析系统默认 Provider 凭证，构建 LangChainAgentRunner。
 失败时返回 None，调用方应返回 503。
 """
 result = await ProviderConfigService.aresolve_or_error
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
 """POST /v1/chat/completions — OpenAI 协议兼容入口。"""
 # Pitfall 6：不走 JWT，避免 SynchronousOnlyOperation（async 上下文禁止 lazy-load user）
 authentication_classes: list =
 permission_classes = [OptionalBearerTokenAuth]
 async def post(self, request: Any) -> Any: # type: ignore[override]
 serializer = ChatCompletionsRequestSerializer(data=request.data)
 if not serializer.is_valid:
 return openai_error_response(
 message=str(serializer.errors),
 type_="invalid_request_error",
 code="bad_request",
 http_status=400,
 )
 params = serializer.validated_data
 lc_messages = await prepare_messages(
 messages=params["messages"],
 repository_ids=[str(rid) for rid in params.get("repository_ids") or ],
 project_id=str(params["project_id"]) if params.get("project_id") else None,
 )
 runner = await _build_runner
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
 return StreamingHttpResponse(
 streaming_content=self._stream_chunks(runner, lc_messages, params, model_name),
 content_type="text/event-stream",
 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
 )
 # 非流式：累积所有 chunk 后一次返回（简化实现）
 chunks: list[bytes] =
 async for chunk_bytes in OpenAICompatAdapter.translate_stream(
 runner, lc_messages, model=model_name, include_usage=True
 ):
 chunks.append(chunk_bytes)
 return Response({"object": "chat.completion", "model": model_name, "choices": })
 async def _stream_chunks(
 self,
 runner: LangChainAgentRunner,
 lc_messages: list,
 params: dict,
 model_name: str,
 ):
 """逐 chunk yield OpenAI SSE 格式字节流（含末尾 [DONE] 哨兵）。"""
 include_usage: bool = (params.get("stream_options") or {}).get("include_usage", False)
 try:
 async for chunk_bytes in OpenAICompatAdapter.translate_stream(
 runner, lc_messages, model=model_name, include_usage=include_usage
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
 }, ensure_ascii=False).encode
 + b"\n\n"
 )
 yield b"data: [DONE]\n\n"
class ModelsView(APIView):
 """GET /v1/models — 列出可用模型。"""
 authentication_classes: list =
 permission_classes = [OptionalBearerTokenAuth]
 async def get(self, request: Any) -> Response: # type: ignore[override]
 # 固定返回 friday-default；后续 Phase+ 扩展为动态读取 ProviderCredential
 return Response({
 "object": "list",
 "data": [
 {
 "id": "friday-default",
 "object": "model",
 "created": int(time.time),
 "owned_by": "friday",
 }
 ],
 })
