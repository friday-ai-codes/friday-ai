"""Chat API views."""
import asyncio
import time
from typing import Any
import structlog
from django.core.cache import cache
from django.http import StreamingHttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from adrf.views import APIView
from agents.core.events import ERROR, AgentEvent
from agents.llm.base import create_provider
from agents.llm.providers import (
 CredentialType,
 PROVIDER_REGISTRY,
 ProviderType,
)
from .authentication import ChatKeyAuthentication
from .conversation_service import ConversationService
from .models import Conversation
from .permissions import ChatAuthPermission
from .serializers import (
 ChatCompletionRequestSerializer,
 ChatCompletionResponseSerializer,
 ConversationDetailSerializer,
 ConversationListSerializer,
 ConversationMessageSerializer,
 CreateConversationSerializer,
 HealthCheckResponseSerializer,
 ModelsRequestSerializer,
 ModelsResponseSerializer,
 ProviderSerializer,
 SendMessageResponseSerializer,
 SendMessageSerializer,
)
from .services import ChatMessage, ChatServiceError, aget_chat_service, aget_setting_value
from .streaming import format_keepalive, format_sse
from projects.models import Project
logger = structlog.get_logger(__name__)
class ModelsView(APIView):
 """API view for getting available models."""
 authentication_classes = [JWTAuthentication, ChatKeyAuthentication]
 permission_classes = [ChatAuthPermission]
 @extend_schema(
 summary="获取可用模型列表",
 description="获取 LLM 提供商的可用模型列表，支持系统配置或项目配置",
 parameters=[
 {
 "name": "source",
 "in": "query",
 "description": "配置来源: system 或 project",
 "required": False,
 "schema": {"type": "string", "enum": ["system", "project"], "default": "system"},
 },
 {
 "name": "project_id",
 "in": "query",
 "description": "项目 ID（当 source=project 时）",
 "required": False,
 "schema": {"type": "integer"},
 },
 {
 "name": "api_key",
 "in": "query",
 "description": "临时 API Key（用于测试未保存的配置）",
 "required": False,
 "schema": {"type": "string"},
 },
 {
 "name": "base_url",
 "in": "query",
 "description": "临时 Base URL（用于测试未保存的配置）",
 "required": False,
 "schema": {"type": "string"},
 },
 ],
 responses={
 200: ModelsResponseSerializer,
 400: {"description": "请求参数错误"},
 500: {"description": "服务错误"},
 },
 tags=["Chat"],
 )
 async def get(self, request):
 """Get available models."""
 serializer = ModelsRequestSerializer(data=request.query_params)
 if not serializer.is_valid:
 return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
 data = serializer.validated_data
 source = data.get("source", "system")
 project_id = data.get("project_id")
 api_key = data.get("api_key")
 base_url = data.get("base_url")
 try:
 service = await aget_chat_service(
 source=source,
 project_id=project_id,
 api_key=api_key or None,
 base_url=base_url or None,
 )
 models = await service.get_models
 response_data = {
 "models": [{"id": m.id, "name": m.name, "created": m.created} for m in models]
 }
 return Response(response_data)
 except ChatServiceError as e:
 logger.warning("Failed to get models", error=str(e))
 return Response(
 {"error": str(e)},
 status=status.HTTP_400_BAD_REQUEST,
 )
 except Exception as e:
 logger.error("Unexpected error getting models", error=str(e))
 return Response(
 {"error": f"获取模型列表失败: {str(e)}"},
 status=status.HTTP_500_INTERNAL_SERVER_ERROR,
 )
class ChatCompletionsView(APIView):
 """API view for chat completions."""
 permission_classes = [IsAuthenticated]
 @extend_schema(
 summary="发送对话请求",
 description="向 LLM 发送对话请求并获取响应",
 request=ChatCompletionRequestSerializer,
 responses={
 200: ChatCompletionResponseSerializer,
 400: {"description": "请求参数错误"},
 500: {"description": "服务错误"},
 },
 tags=["Chat"],
 )
 async def post(self, request):
 """Send chat completion request."""
 serializer = ChatCompletionRequestSerializer(data=request.data)
 if not serializer.is_valid:
 return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
 data = serializer.validated_data
 source = data.get("source", "system")
 project_id = data.get("project_id")
 api_key = data.get("api_key")
 base_url = data.get("base_url")
 model = data["model"]
 messages_data = data["messages"]
 max_tokens = data.get("max_tokens", 4096)
 try:
 service = await aget_chat_service(
 source=source,
 project_id=project_id,
 api_key=api_key or None,
 base_url=base_url or None,
 )
 # Convert message dicts to ChatMessage objects
 messages = [ChatMessage(role=m["role"], content=m["content"]) for m in messages_data]
 result = await service.chat_completion(
 messages=messages,
 model=model,
 max_tokens=max_tokens,
 )
 response_data = {
 "content": result.content,
 "model": result.model,
 "usage": result.usage,
 }
 return Response(response_data)
 except ChatServiceError as e:
 logger.warning("Chat completion failed", error=str(e))
 return Response(
 {"error": str(e)},
 status=status.HTTP_400_BAD_REQUEST,
 )
 except Exception as e:
 logger.error("Unexpected error in chat completion", error=str(e))
 return Response(
 {"error": f"对话请求失败: {str(e)}"},
 status=status.HTTP_500_INTERNAL_SERVER_ERROR,
 )
# ============================================================================
# Conversation Views (Phase)
# ============================================================================
class ConversationListView(APIView):
 """对话列表 + 创建。"""
 authentication_classes = [JWTAuthentication, ChatKeyAuthentication]
 permission_classes = [ChatAuthPermission]
 @extend_schema(
 summary="获取对话列表",
 description="返回未删除的对话列表，按 updated_at 降序排列",
 responses={200: ConversationListSerializer(many=True)},
 tags=["Conversations"],
 )
 async def get(self, request):
 """获取对话列表。"""
 conversations = await ConversationService.list_conversations
 serializer = ConversationListSerializer(conversations, many=True)
 return Response(serializer.data)
 @extend_schema(
 summary="创建对话",
 description="创建新对话并绑定到指定项目",
 request=CreateConversationSerializer,
 responses={
 201: ConversationListSerializer,
 400: {"description": "请求参数错误"},
 },
 tags=["Conversations"],
 )
 async def post(self, request):
 """创建新对话。"""
 serializer = CreateConversationSerializer(data=request.data)
 if not serializer.is_valid:
 return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
 data = serializer.validated_data
 project_id = str(data["project_id"])
 title = data.get("title", "新对话")
 model = data.get("model", "")
 # 验证 project 存在
 try:
 await Project.objects.aget(id=project_id)
 except Project.DoesNotExist:
 return Response(
 {"error": f"项目不存在: {project_id}"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 conversation = await ConversationService.create_conversation(
 project_id=project_id,
 title=title,
 model=model,
 )
 response_serializer = ConversationListSerializer(conversation)
 return Response(response_serializer.data, status=status.HTTP_201_CREATED)
class ConversationDetailView(APIView):
 """对话详情 + 删除。"""
 authentication_classes = [JWTAuthentication, ChatKeyAuthentication]
 permission_classes = [ChatAuthPermission]
 @extend_schema(
 summary="获取对话详情",
 description="返回对话详情及历史消息列表",
 responses={
 200: ConversationDetailSerializer,
 404: {"description": "对话不存在"},
 },
 tags=["Conversations"],
 )
 async def get(self, request, conversation_id):
 """获取对话详情含消息。"""
 try:
 result = await ConversationService.get_conversation_with_messages(
 str(conversation_id),
 )
 except Conversation.DoesNotExist:
 return Response(
 {"error": "对话不存在"},
 status=status.HTTP_404_NOT_FOUND,
 )
 conversation = result["conversation"]
 messages = result["messages"]
 response_data = {
 "id": str(conversation.id),
 "project_id": str(conversation.project_id),
 "title": conversation.title,
 "created_at": conversation.created_at,
 "updated_at": conversation.updated_at,
 "messages": ConversationMessageSerializer(messages, many=True).data,
 }
 return Response(response_data)
 @extend_schema(
 summary="删除对话",
 description="软删除对话（标记 is_deleted=True）",
 responses={
 204: None,
 404: {"description": "对话不存在"},
 },
 tags=["Conversations"],
 )
 async def delete(self, request, conversation_id):
 """软删除对话。"""
 try:
 await ConversationService.delete_conversation(str(conversation_id))
 except Conversation.DoesNotExist:
 return Response(
 {"error": "对话不存在"},
 status=status.HTTP_404_NOT_FOUND,
 )
 return Response(status=status.HTTP_204_NO_CONTENT)
class SendMessageView(APIView):
 """发送消息。"""
 authentication_classes = [JWTAuthentication, ChatKeyAuthentication]
 permission_classes = [ChatAuthPermission]
 @extend_schema(
 summary="发送消息",
 description="发送消息并获得 AI 回复（同步模式）",
 request=SendMessageSerializer,
 responses={
 200: SendMessageResponseSerializer,
 400: {"description": "请求参数错误"},
 404: {"description": "对话不存在"},
 },
 tags=["Conversations"],
 )
 async def post(self, request, conversation_id):
 """发送消息获取 AI 回复。"""
 serializer = SendMessageSerializer(data=request.data)
 if not serializer.is_valid:
 return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
 content = serializer.validated_data["content"]
 role = serializer.validated_data.get("role", "developer")
 try:
 result = await ConversationService.send_message(
 conversation_id=str(conversation_id),
 content=content,
 role=role,
 )
 except Conversation.DoesNotExist:
 return Response(
 {"error": "对话不存在"},
 status=status.HTTP_404_NOT_FOUND,
 )
 message = result["message"]
 response_data = {
 "message": ConversationMessageSerializer(message).data,
 "tool_calls": result.get("tool_calls", ),
 "usage": result.get("usage"),
 }
 return Response(response_data)
class ChatStreamView(APIView):
 """SSE 流式消息端点。
 通过 Server-Sent Events 返回 AI 回复的实时流，
 每个事件包含结构化 JSON，类型包括 text_delta / tool_use_start /
 tool_use_result / message_complete / title_generated / error。
 """
 authentication_classes = [JWTAuthentication, ChatKeyAuthentication]
 permission_classes = [ChatAuthPermission]
 @extend_schema(
 summary="流式发送消息",
 description="发送消息并通过 SSE 流式返回 AI 回复（text/event-stream）",
 request=SendMessageSerializer,
 responses={
 200: {"description": "SSE 事件流（text/event-stream）"},
 400: {"description": "请求参数错误"},
 404: {"description": "对话不存在"},
 },
 tags=["Conversations"],
 )
 async def post(self, request, conversation_id): # type: ignore[override]
 """发送消息并以 SSE 流式返回 AI 回复。"""
 serializer = SendMessageSerializer(data=request.data)
 if not serializer.is_valid:
 return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
 content = serializer.validated_data["content"]
 role = serializer.validated_data.get("role", "developer")
 # 验证对话存在
 try:
 await Conversation.objects.aget(
 id=conversation_id,
 is_deleted=False,
 )
 except Conversation.DoesNotExist:
 return Response(
 {"error": "对话不存在"},
 status=status.HTTP_404_NOT_FOUND,
 )
 response = StreamingHttpResponse(
 streaming_content=self._stream_events(
 str(conversation_id), content, role,
 ),
 content_type="text/event-stream",
 )
 response["Cache-Control"] = "no-cache"
 response["X-Accel-Buffering"] = "no"
 return response
 async def _stream_events(
 self,
 conversation_id: str,
 content: str,
 role: str,
 ):
 """生成 SSE 事件流。"""
 import uuid as uuid_mod
 message_id = str(uuid_mod.uuid4)
 try:
 async for event in ConversationService.send_message_stream(
 conversation_id=conversation_id,
 content=content,
 role=role,
 ):
 if event.type == "keepalive":
 yield format_keepalive
 else:
 yield format_sse(event, message_id=message_id)
 except Conversation.DoesNotExist:
 yield format_sse(
 AgentEvent(type=ERROR, data={"message": "对话不存在"}),
 message_id=message_id,
 )
 except ValueError as e:
 yield format_sse(
 AgentEvent(type=ERROR, data={"message": str(e)}),
 message_id=message_id,
 )
 except Exception:
 logger.exception("sse_stream_error", conversation_id=conversation_id)
 yield format_sse(
 AgentEvent(type=ERROR, data={"message": "服务内部错误"}),
 message_id=message_id,
 )
# ============================================================================
# Provider API Views (Phase)
# ============================================================================
# Provider icon 映射表（ProviderType → iconify 标识符）
PROVIDER_ICONS: dict[ProviderType, str] = {
 ProviderType.ANTHROPIC: "simple-icons--anthropic",
 ProviderType.OPENAI_RESPONSES: "simple-icons--openai",
 ProviderType.OPENAI_CODEX_RESPONSES: "simple-icons--openai",
 ProviderType.OPENAI_COMPLETIONS: "simple-icons--openai",
 ProviderType.GOOGLE_VERTEX: "simple-icons--googlecloud",
 ProviderType.GOOGLE_GEMINI_CLI: "simple-icons--googlegemini",
 ProviderType.GOOGLE_ANTIGRAVITY: "simple-icons--google",
}
# env_key（PROVIDER_REGISTRY）→ SettingKey 映射
_ENV_TO_SETTING: dict[str, str] = {
 "ANTHROPIC_API_KEY": "anthropic_api_key",
 "OPENAI_API_KEY": "openai_api_key",
 "GEMINI_API_KEY": "google_api_key",
 "GOOGLE_API_KEY": "google_api_key",
 "GOOGLE_CLOUD_PROJECT": "google_service_account_json",
}
# 模型列表缓存 TTL（秒）
_MODEL_CACHE_TTL = 300 # 5 分钟
def _validate_provider_type(provider_type_str: str) -> ProviderType | None:
 """验证并转换 provider_type 字符串为枚举值。"""
 try:
 return ProviderType(provider_type_str)
 except ValueError:
 return None
async def _get_credential_setting_key(provider_type: ProviderType) -> str | None:
 """获取 Provider 对应的凭据 SettingKey。"""
 metadata = PROVIDER_REGISTRY[provider_type]
 env_key = metadata["env_key"]
 if metadata["credential_type"] == CredentialType.SERVICE_ACCOUNT_JSON:
 return "google_service_account_json"
 return _ENV_TO_SETTING.get(env_key)
async def _has_credential(provider_type: ProviderType) -> bool:
 """检查 Provider 是否已配置凭据。"""
 setting_key = await _get_credential_setting_key(provider_type)
 if not setting_key:
 return False
 value = await aget_setting_value(setting_key)
 return bool(value)
async def _get_provider_models(
 provider_type: ProviderType,
 api_key: str,
 base_url: str,
) -> list[Any]:
 """获取 Provider 的模型列表（通过上游 API 调用）。"""
 provider = create_provider(
 provider_type=provider_type,
 api_key=api_key,
 base_url=base_url,
 )
 # LLMProvider (agents.llm.base) 没有 get_models 方法
 # 对于支持的 Provider，使用 chat 协议层的 ChatService
 service = await aget_chat_service(source="system")
 return await service.get_models
class ProviderListView(APIView):
 """Provider 列表 API。"""
 authentication_classes = [JWTAuthentication, ChatKeyAuthentication]
 permission_classes = [ChatAuthPermission]
 @extend_schema(
 summary="获取 Provider 列表",
 description="返回所有可用 Provider 及其凭据配置状态",
 responses={200: ProviderSerializer(many=True)},
 tags=["Providers"],
 )
 async def get(self, request: Any) -> Response:
 """返回所有 Provider 列表。"""
 providers =
 for pt, metadata in PROVIDER_REGISTRY.items:
 has_cred = await _has_credential(pt)
 providers.append({
 "id": str(pt),
 "name": metadata["display_name"],
 "icon": PROVIDER_ICONS.get(pt, "simple-icons--bot"),
 "credential_type": str(metadata["credential_type"]),
 "has_credential": has_cred,
 })
 return Response(providers)
class ProviderModelsView(APIView):
 """Provider 模型列表 API（带缓存）。"""
 authentication_classes = [JWTAuthentication, ChatKeyAuthentication]
 permission_classes = [ChatAuthPermission]
 @extend_schema(
 summary="获取 Provider 的模型列表",
 description="返回指定 Provider 可用的模型列表，结果缓存 5 分钟",
 responses={
 200: {"description": "模型列表"},
 400: {"description": "无效的 Provider 类型"},
 },
 tags=["Providers"],
 )
 async def get(self, request: Any, provider_type: str) -> Response:
 """获取指定 Provider 的模型列表。"""
 pt = _validate_provider_type(provider_type)
 if pt is None:
 return Response(
 {"error": f"无效的 Provider 类型: {provider_type}"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 检查缓存
 cache_key = f"provider_models:{provider_type}"
 cached = cache.get(cache_key)
 if cached is not None:
 return Response(cached)
 try:
 models = await _get_provider_models(pt, "", "")
 data = {
 "models": [
 {"id": m.id, "name": m.name, "created": m.created}
 for m in models
 ]
 }
 cache.set(cache_key, data, _MODEL_CACHE_TTL)
 return Response(data)
 except Exception as e:
 logger.warning("获取模型列表失败", provider_type=provider_type, error=str(e))
 return Response(
 {"error": f"获取模型列表失败: {e!s}"},
 status=status.HTTP_400_BAD_REQUEST,
 )
class ProviderHealthView(APIView):
 """Provider 健康检查 API。"""
 authentication_classes = [JWTAuthentication, ChatKeyAuthentication]
 permission_classes = [ChatAuthPermission]
 # 健康检查超时（秒）— CONTEXT.md 锁定 10 秒
 _HEALTH_TIMEOUT = 10.0
 @extend_schema(
 summary="检查 Provider 健康状态",
 description="通过微型 completion 探测验证 Provider 可用性，超时 10 秒",
 responses={
 200: HealthCheckResponseSerializer,
 400: {"description": "无效的 Provider 类型"},
 },
 tags=["Providers"],
 )
 async def post(self, request: Any, provider_type: str) -> Response:
 """执行 Provider 健康检查。"""
 pt = _validate_provider_type(provider_type)
 if pt is None:
 return Response(
 {"error": f"无效的 Provider 类型: {provider_type}"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 获取凭据
 setting_key = await _get_credential_setting_key(pt)
 if not setting_key:
 return Response({
 "provider_type": provider_type,
 "status": "unavailable",
 "latency_ms": 0,
 "error": "Provider 凭据配置未映射",
 })
 credential = await aget_setting_value(setting_key)
 if not credential:
 return Response({
 "provider_type": provider_type,
 "status": "unavailable",
 "latency_ms": 0,
 "error": "凭据未配置",
 })
 # 获取 base_url
 metadata = PROVIDER_REGISTRY[pt]
 base_url = metadata["default_base_url"]
 # 微型 completion 探测
 start = time.perf_counter
 try:
 provider = create_provider(
 provider_type=pt,
 api_key=credential,
 base_url=base_url,
 )
 await asyncio.wait_for(
 provider.chat(
 messages=[{"role": "user", "content": "Hi"}],
 max_tokens=1,
 ),
 timeout=self._HEALTH_TIMEOUT,
 )
 elapsed_ms = int((time.perf_counter - start) * 1000)
 # 成功后自动刷新模型缓存
 cache.delete(f"provider_models:{provider_type}")
 return Response({
 "provider_type": provider_type,
 "status": "available",
 "latency_ms": elapsed_ms,
 "error": None,
 })
 except TimeoutError:
 elapsed_ms = int((time.perf_counter - start) * 1000)
 return Response({
 "provider_type": provider_type,
 "status": "unavailable",
 "latency_ms": elapsed_ms,
 "error": "请求超时（10秒）",
 })
 except NotImplementedError as e:
 elapsed_ms = int((time.perf_counter - start) * 1000)
 return Response({
 "provider_type": provider_type,
 "status": "unavailable",
 "latency_ms": elapsed_ms,
 "error": str(e),
 })
 except Exception as e:
 elapsed_ms = int((time.perf_counter - start) * 1000)
 logger.warning(
 "health_check_failed",
 provider_type=provider_type,
 error=str(e),
 )
 return Response({
 "provider_type": provider_type,
 "status": "unavailable",
 "latency_ms": elapsed_ms,
 "error": str(e),
 })
