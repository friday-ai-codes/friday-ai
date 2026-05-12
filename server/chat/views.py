"""Chat API views."""
import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.http import StreamingHttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from agents.core.events import ERROR, KEEPALIVE, AgentEvent
from projects.models import Project
from .authentication import ChatKeyAuthentication, OptionalJWTAuthentication
from .conversation_service import ConversationService
from .models import Conversation
from .permissions import ChatAuthPermission
from .serializers import (
 ChatCompletionRequestSerializer,
 ChatCompletionResponseSerializer,
 CodingSessionSerializer,
 ConversationDetailSerializer,
 ConversationListSerializer,
 ConversationMessageSerializer,
 ConversationPatchSerializer,
 ConversationRuntimeSerializer,
 CreateConversationSerializer,
 ExportToFeishuSerializer,
 ModelsRequestSerializer,
 ModelsResponseSerializer,
 SendMessageSerializer,
 WebPushPublicKeySerializer,
 WebPushSubscriptionSerializer,
 WebPushUnsubscribeSerializer,
)
from .services import ChatMessage, ChatServiceError, aget_chat_service
from .streaming import format_keepalive, format_sse
logger = structlog.get_logger(__name__)
def _append_feishu_export_record(message, record: dict[str, str]) -> None:
 """Persist export history on message metadata for refresh-safe recovery."""
 metadata = message.metadata if isinstance(message.metadata, dict) else {}
 raw_exports = metadata.get("feishu_exports", )
 exports = raw_exports if isinstance(raw_exports, list) else
 document_id = record.get("document_id", "")
 if document_id and any(
 isinstance(item, dict) and item.get("document_id") == document_id
 for item in exports
 ):
 return
 metadata["feishu_exports"] = [*exports, record]
 message.metadata = metadata
class ModelsView(APIView):
 """API view for getting available models."""
 authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
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
 "name": "space_id",
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
 space_id = data.get("space_id")
 api_key = data.get("api_key")
 base_url = data.get("base_url")
 try:
 service = await aget_chat_service(
 source=source,
 space_id=space_id,
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
 # Phase OpenAI compat 兼容性：除默认 Cookie JWT 外，再接受 Bearer JWT 与
 # X-Chat-Key（OpenAI SDK / 外部脚本通常通过 Authorization: Bearer 访问）。
 authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
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
 space_id = data.get("space_id")
 api_key = data.get("api_key")
 base_url = data.get("base_url")
 model = data["model"]
 messages_data = data["messages"]
 max_tokens = data.get("max_tokens", 4096)
 try:
 service = await aget_chat_service(
 source=source,
 space_id=space_id,
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
 authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
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
 space_id = str(data["space_id"])
 title = data.get("title", "新对话")
 model = data.get("model", "")
 # 验证 project 存在
 try:
 await Project.objects.aget(id=space_id)
 except Project.DoesNotExist:
 return Response(
 {"error": f"空间不存在: {space_id}"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 conversation = await ConversationService.create_conversation(
 space_id=space_id,
 title=title,
 model=model,
 )
 response_serializer = ConversationListSerializer(conversation)
 return Response(response_serializer.data, status=status.HTTP_201_CREATED)
class ConversationDetailView(APIView):
 """对话详情 + 删除。"""
 authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
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
 """获取对话详情含消息。
 Phase：响应扩展 resolved_provider 字段 = {provider_type,
 model, source, chain: [4 层]}。
 """
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
 # Phase：四层 Provider 解析 Inspector
 # 预取 FK（async 上下文禁止触发 SynchronousOnlyOperation）
 conversation_prefetched = await Conversation.objects.select_related(
 "project",
 "project__default_provider_credential_id",
 "provider_credential_id",
 ).aget(id=conversation.id)
 from services.provider_config import (
 ProviderConfigService,
 ProviderMissingError,
 ResolvedProviderChain,
 )
 chain_result = await ProviderConfigService.aresolve_with_chain(
 node_config=None,
 conversation=conversation_prefetched,
 project=conversation_prefetched.project,
 )
 resolved_provider_payload: dict | None = None
 if isinstance(chain_result, ResolvedProviderChain):
 resolved_provider_payload = {
 "provider_type": str(chain_result.winning.provider_type),
 "model": (
 (chain_result.winning.extra or {}).get("model", "")
 or (conversation.model or "")
 ),
 "source": chain_result.winning.source,
 "chain": [
 {
 "layer": entry.layer,
 "provider_type": entry.provider_type,
 "model": entry.model,
 "credential_id": (
 str(entry.credential_id) if entry.credential_id else None
 ),
 "active": entry.active,
 }
 for entry in chain_result.chain
 ],
 }
 elif isinstance(chain_result, ProviderMissingError):
 # 全链路缺失 → resolved_provider=null（前端降级渲染）
 resolved_provider_payload = None
 # UAT 第 3 项 hotfix：detail 响应补齐 model + status +
 # provider_credential_id，与 list 字段对齐；conversation_prefetched 已 select_related
 # provider_credential_id（async-safe），直接读 FK 的 _id 列即可。
 response_data = {
 "id": str(conversation.id),
 "space_id": str(conversation.project_id),
 "title": conversation.title,
 "model": conversation.model,
 "status": conversation.status,
 "provider_credential_id": (
 str(conversation_prefetched.provider_credential_id_id)
 if conversation_prefetched.provider_credential_id_id
 else None
 ),
 "created_at": conversation.created_at,
 "updated_at": conversation.updated_at,
 "messages": ConversationMessageSerializer(messages, many=True).data,
 "resolved_provider": resolved_provider_payload,
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
 @extend_schema(
 summary="更新对话（pin 语义）",
 description=(
 "部分更新对话的 provider_credential_id / model / title。"
 "frozen 状态（completed/stopped/error）下拒绝修改 provider_credential_id 和 model，"
 "返回 HTTP 400 + {code: 'conversation_frozen'}（Phase 后端防御）。"
 ),
 request=ConversationPatchSerializer,
 responses={
 200: ConversationDetailSerializer,
 400: {"description": "对话已冻结或字段校验失败"},
 404: {"description": "对话不存在"},
 },
 tags=["Conversations"],
 )
 async def patch(self, request, conversation_id):
 """Phase /：对话 pin 更新 + frozen 校验。"""
 # 1. 对话存在性（Conversation.DoesNotExist → 404）
 try:
 conversation = await Conversation.objects.aget(
 id=conversation_id,
 is_deleted=False,
 )
 except Conversation.DoesNotExist:
 return Response(
 {"error": "对话不存在"},
 status=status.HTTP_404_NOT_FOUND,
 )
 # 2. Frozen 校验（ 双重防御）
 FROZEN_STATUSES = {"completed", "stopped", "error"}
 if conversation.status in FROZEN_STATUSES:
 if any(k in request.data for k in ("provider_credential_id", "model")):
 logger.info(
 "conversation.patch_rejected_frozen",
 conversation_id=str(conversation.id),
 status=conversation.status,
 )
 return Response(
 {
 "code": "conversation_frozen",
 "detail": (
 f"对话状态为 {conversation.status}，"
 "Provider / 模型不可修改"
 ),
 },
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 3. Validation（provider_credential_id FK + is_active 校验）
 serializer = ConversationPatchSerializer(data=request.data)
 try:
 await sync_to_async(serializer.is_valid)(raise_exception=True)
 except Exception:
 logger.info(
 "conversation.patch_validation_failed",
 conversation_id=str(conversation.id),
 )
 raise
 # 4. 应用变更（provider_credential_id 需写 FK 的 _id 列；Django 生成的 DB 列名
 # 为 `<field_name>_id` → 对本字段即 `provider_credential_id_id`，setattr 更稳妥。）
 data = serializer.validated_data
 updated_fields: list[str] =
 if "provider_credential_id" in data:
 # 赋 UUID 到 FK 的 _id 列：Django ORM 约定 `{field}_id` 持久化 FK ID
 setattr(
 conversation,
 "provider_credential_id_id",
 data["provider_credential_id"],
 )
 updated_fields.append("provider_credential_id")
 if "model" in data:
 conversation.model = data["model"]
 updated_fields.append("model")
 if "title" in data:
 conversation.title = data["title"]
 updated_fields.append("title")
 if updated_fields:
 updated_fields.append("updated_at")
 await sync_to_async(conversation.save)(update_fields=updated_fields)
 logger.info(
 "conversation.patch_applied",
 conversation_id=str(conversation.id),
 fields_updated=list(data.keys),
 )
 # 5. 响应（复用 ConversationDetailSerializer）
 # UAT 第 3 项 hotfix：补齐 model + status + provider_credential_id，
 # 让前端 patchConversationCredential 直接拿响应回填本地 conversations，
 # 触发 currentConversation getter 反映新 pin。
 return Response(
 {
 "id": str(conversation.id),
 "space_id": str(conversation.project_id),
 "title": conversation.title,
 "model": conversation.model,
 "status": conversation.status,
 "provider_credential_id": (
 str(conversation.provider_credential_id_id)
 if conversation.provider_credential_id_id
 else None
 ),
 "created_at": conversation.created_at,
 "updated_at": conversation.updated_at,
 "messages":,
 },
 )
class ConversationPreflightView(APIView):
 """Phase：对话凭证前置探测（不发送 user message）。
 用于 ChatMessageArea 在用户进入对话 / 按 Send / 切换 Provider 时提前判定：
 - 若凭证解析成功 → 200 `{status: "ok", resolved: {...}}`，允许正常 Send。
 - 若四层均无凭证 → 400 `{code: "provider_credential_missing", data: {...}}`，
 前端渲染 ProviderCredentialMissingCard（ 按角色分流 CTA）。
 契约：ProviderConfigService.aresolve_or_error 返回 Result 模式；不抛异常。
 本 View 将 ProviderMissingError 平铺到 `data.missing_provider / scope_attempted /
 recommended_action` 三字段（work item §Copywriting 驱动文案）。
 """
 authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
 permission_classes = [ChatAuthPermission]
 @extend_schema(
 summary="对话凭证前置探测",
 description=(
 "解析对话的 Provider 凭证；失败时返回结构化 provider_credential_missing 错误供前端渲染 "
 "ProviderCredentialMissingCard（Phase ）。"
 ),
 responses={
 200: {"description": "凭证可用"},
 400: {"description": "凭证缺失 — code=provider_credential_missing"},
 404: {"description": "对话不存在"},
 },
 tags=["Conversations"],
 )
 async def get(self, request, conversation_id):
 """前置探测凭证可用性。"""
 try:
 # select_related 预取 FK，避免 aresolve_or_error 在 async 上下文访问
 # conversation.provider_credential_id / project.default_provider_credential_id
 # 时触发 SynchronousOnlyOperation
 conversation = await Conversation.objects.select_related(
 "project",
 "project__default_provider_credential_id",
 "provider_credential_id",
 ).aget(
 id=conversation_id,
 is_deleted=False,
 )
 except Conversation.DoesNotExist:
 return Response(
 {"error": "对话不存在"},
 status=status.HTTP_404_NOT_FOUND,
 )
 # [NEW Phase Hotfix — 230 ] Ownership 校验（T- mitigate）
 # 模式与 ConversationMessagesDeleteView.delete 完全一致，仅：
 # min_role: "member" → "viewer"（preflight 是只读探测）
 # event name: "chat.cleanup_denied_cross_project" → "chat.preflight_denied_cross_project"
 # detail: "无权删除其他项目的对话消息" → "无权访问该对话"
 # 放置位置：select_related 预取之后、aresolve_or_error 之前 —— 避免 resolved
 # / missing payload 的 provider_type / credential_id / missing_provider 字段
 # 泄漏给跨项目用户（T- Information Disclosure）。
 from permissions.services import PermissionService
 user = request.user
 if (
 getattr(user, "is_authenticated", False)
 and not getattr(user, "is_superuser", False)
 and conversation.project_id is not None
 ):
 has_access = await sync_to_async(PermissionService.has_project_access)(
 user, conversation.project, "viewer"
 )
 if not has_access:
 logger.warning(
 "chat.preflight_denied_cross_project",
 user_id=str(getattr(user, "id", "")),
 conversation_id=str(conversation.id),
 space_id=str(conversation.project_id),
 )
 return Response(
 {"detail": "无权访问该对话"},
 status=status.HTTP_403_FORBIDDEN,
 )
 # Lazy import 避免 ProviderConfigService 加载开销落入 views 模块导入路径
 from services.provider_config import (
 ProviderConfigService,
 ProviderMissingError,
 )
 result = await ProviderConfigService.aresolve_or_error(
 node_config=None,
 conversation=conversation,
 project=conversation.project,
 )
 if isinstance(result, ProviderMissingError):
 logger.info(
 "conversation.preflight_missing",
 conversation_id=str(conversation.id),
 missing_provider=result.missing_provider,
 scope_attempted=result.source_attempted,
 )
 return Response(
 {
 "code": "provider_credential_missing",
 "data": {
 "missing_provider": result.missing_provider,
 "scope_attempted": result.source_attempted or "system",
 "recommended_action": (
 result.recommended_action
 or f"请在系统或项目设置添加 {result.missing_provider} 凭证"
 ),
 },
 },
 status=status.HTTP_400_BAD_REQUEST,
 )
 # Resolved：平铺 ResolvedProviderConfig 中的公开字段（不含 api_key 明文 T-）
 logger.info(
 "conversation.preflight_ok",
 conversation_id=str(conversation.id),
 source=result.source,
 provider_type=str(result.provider_type),
 )
 return Response(
 {
 "status": "ok",
 "resolved": {
 "provider_type": str(result.provider_type),
 "model": result.extra.get("model", "") or (conversation.model or ""),
 "source": result.source,
 "credential_id": (
 str(result.credential_id) if result.credential_id else None
 ),
 },
 },
 )
class ConversationRuntimeView(APIView):
 """对话运行态查询。"""
 authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
 permission_classes = [ChatAuthPermission]
 @extend_schema(
 summary="获取对话运行态",
 description="返回对话当前是否仍在执行，以及最近的深度分析日志/进度快照",
 responses={200: ConversationRuntimeSerializer},
 tags=["Conversations"],
 )
 async def get(self, request, conversation_id):
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
 runtime = await ConversationService.get_conversation_runtime(str(conversation_id))
 return Response(runtime)
class ConversationMessagesDeleteView(APIView):
 """Phase：对话历史消息批量清理端点。
 路由：``DELETE /api/chat/conversations/{conversation_id}/messages/?before_id=X``
 语义（Plan Behavior C-H 契约）：
 - 硬删 conversation 内 ``created_at < target_message.created_at`` 的消息
 （Message 模型无 ``is_deleted`` 字段 → 真删）
 - ``before_id`` 必填；空/缺失 → 400
 - ``conversation_id`` 不存在 → 404
 - ``before_id`` 指向的消息不属于本 conversation → 400（防跨 conversation 篡改）
 - Ownership 校验：非 superuser 必须有 conversation.project MEMBER+ 权限；
 跨项目越权 → 403 + audit log ``chat.cleanup_denied_cross_project``
 - 成功返回 ``{"deleted_count": N}`` + audit log ``chat.messages_cleaned``
 Threat model（T-/02/03）：
 - Ownership 校验 via PermissionService.has_project_access(MEMBER+)
 - before_id 归属校验通过 Django ORM filter(conversation=conv) 强制（Tampering 防御）
 - 硬删不可恢复 → UI 层必须有二次确认（Plan Task 2 CleanupDialog 中的 AlertDialog）
 """
 authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
 permission_classes = [ChatAuthPermission]
 @extend_schema(
 summary="批量删除对话历史消息",
 description=(
 "硬删 before_id 之前的所有消息（created_at 升序）。受 ownership 校验；"
 "conversation.project 需 user 有 MEMBER+ 权限（superuser 豁免）。"
 "Phase 。"
 ),
 responses={
 200: {"description": "删除成功 {deleted_count: N}"},
 400: {"description": "before_id 缺失或指向不属于本对话的消息"},
 403: {"description": "无权删除其他项目的对话消息"},
 404: {"description": "对话不存在"},
 },
 tags=["Conversations"],
 )
 async def delete(self, request, conversation_id):
 """批量删除 before_id 之前的消息。"""
 # Lazy import 避免循环（Message 在本模块仅此处使用）
 from chat.models import Message
 from permissions.services import PermissionService
 # 1. before_id query 参数必填
 before_id = request.query_params.get("before_id")
 if not before_id:
 return Response(
 {"detail": "before_id 参数必填"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 2. 对话存在性
 try:
 conversation = await Conversation.objects.select_related("project").aget(
 id=conversation_id,
 is_deleted=False,
 )
 except Conversation.DoesNotExist:
 return Response(
 {"error": "对话不存在"},
 status=status.HTTP_404_NOT_FOUND,
 )
 # 3. Ownership 校验（T- mitigate）：非 superuser 必须有 MEMBER+ 权限
 user = request.user
 if (
 getattr(user, "is_authenticated", False)
 and not getattr(user, "is_superuser", False)
 and conversation.project_id is not None
 ):
 has_access = await sync_to_async(PermissionService.has_project_access)(
 user, conversation.project, "member"
 )
 if not has_access:
 logger.warning(
 "chat.cleanup_denied_cross_project",
 user_id=str(getattr(user, "id", "")),
 conversation_id=str(conversation.id),
 space_id=str(conversation.project_id),
 )
 return Response(
 {"detail": "无权删除其他项目的对话消息"},
 status=status.HTTP_403_FORBIDDEN,
 )
 # 4. before_id 必须指向本 conversation 的消息（T- Tampering 防御）
 try:
 target = await Message.objects.aget(
 id=before_id, conversation=conversation
 )
 except Message.DoesNotExist:
 return Response(
 {"detail": "before_id 指向的消息不存在或不属于本对话"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 except (ValueError, TypeError):
 return Response(
 {"detail": "before_id 参数格式无效"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 5. 硬删（created_at < target.created_at）
 deleted_count, _ = await Message.objects.filter(
 conversation=conversation,
 created_at__lt=target.created_at,
 ).adelete
 logger.info(
 "chat.messages_cleaned",
 conversation_id=str(conversation.id),
 before_id=str(before_id),
 deleted_count=int(deleted_count),
 )
 return Response(
 {"deleted_count": int(deleted_count)},
 status=status.HTTP_200_OK,
 )
class WebPushPublicKeyView(APIView):
 """返回浏览器 Push 订阅所需的 VAPID 公钥。"""
 authentication_classes = [OptionalJWTAuthentication]
 permission_classes = [IsAuthenticated]
 @extend_schema(
 summary="获取 Web Push 公钥",
 responses={200: WebPushPublicKeySerializer},
 tags=["Conversations"],
 )
 async def get(self, request):
 from .push_service import ChatPushService
 config = await ChatPushService.aget_or_create_vapid_config
 return Response(
 {
 "public_key": config.public_key,
 "subject": config.subject,
 }
 )
class WebPushSubscriptionView(APIView):
 """保存当前浏览器的 Push 订阅。"""
 authentication_classes = [OptionalJWTAuthentication]
 permission_classes = [IsAuthenticated]
 @extend_schema(
 summary="保存 Web Push 订阅",
 request=WebPushSubscriptionSerializer,
 responses={200: {"description": "保存成功"}},
 tags=["Conversations"],
 )
 async def post(self, request):
 from .push_service import ChatPushService
 serializer = WebPushSubscriptionSerializer(data=request.data)
 if not serializer.is_valid:
 return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
 data = serializer.validated_data
 keys = data["keys"]
 await ChatPushService.asave_subscription(
 user_id=str(request.user.id),
 endpoint=data["endpoint"],
 p256dh=keys["p256dh"],
 auth=keys["auth"],
 user_agent=data.get("user_agent", ""),
 )
 return Response({"status": "ok"})
class WebPushUnsubscribeView(APIView):
 """停用浏览器 Push 订阅。"""
 authentication_classes = [OptionalJWTAuthentication]
 permission_classes = [IsAuthenticated]
 @extend_schema(
 summary="取消 Web Push 订阅",
 request=WebPushUnsubscribeSerializer,
 responses={200: {"description": "取消成功"}},
 tags=["Conversations"],
 )
 async def post(self, request):
 from .push_service import ChatPushService
 serializer = WebPushUnsubscribeSerializer(data=request.data)
 if not serializer.is_valid:
 return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
 await ChatPushService.adeactivate_subscription(
 user_id=str(request.user.id),
 endpoint=serializer.validated_data["endpoint"],
 )
 return Response({"status": "ok"})
class ChatStreamView(APIView):
 """SSE 流式消息端点。
 通过 Server-Sent Events 返回 AI 回复的实时流，
 每个事件包含结构化 JSON，类型包括 text_delta / tool_use_start /
 tool_use_result / message_complete / thinking / title_generated / error。
 """
 authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
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
 async def post(self, request, conversation_id):
 """发送消息并以 SSE 流式返回 AI 回复。"""
 serializer = SendMessageSerializer(data=request.data)
 if not serializer.is_valid:
 return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
 content = serializer.validated_data["content"]
 role = serializer.validated_data.get("role", "developer")
 force_deep_analysis = serializer.validated_data.get("force_deep_analysis", False)
 feishu_doc_id = serializer.validated_data.get("feishu_doc_id", "")
 branch_raw = serializer.validated_data.get("branch", "") or ""
 search_branch = branch_raw.strip or None
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
 str(conversation_id),
 content,
 role,
 str(request.user.id) if getattr(request.user, "is_authenticated", False) else None,
 force_deep_analysis=force_deep_analysis,
 feishu_doc_id=feishu_doc_id,
 search_branch=search_branch,
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
 notification_user_id: str | None,
 *,
 force_deep_analysis: bool = False,
 feishu_doc_id: str = "",
 search_branch: str | None = None,
 ):
 """生成 SSE 事件流。"""
 import uuid as uuid_mod
 from orchestration.models import OrchestrationRun
 message_id = str(uuid_mod.uuid4)
 # 获取当前 OrchestrationRun.run_id 用于所有 SSE 事件
 run_id = ""
 orch_run = await OrchestrationRun.objects.filter(
 conversation_id=conversation_id,
 ).order_by("-created_at").afirst
 if orch_run:
 run_id = str(orch_run.run_id)
 try:
 async for event in ConversationService.send_message_stream(
 conversation_id=conversation_id,
 content=content,
 role=role,
 notification_user_id=notification_user_id,
 force_deep_analysis=force_deep_analysis,
 feishu_doc_id=feishu_doc_id,
 search_branch=search_branch,
 ):
 if event.type == KEEPALIVE:
 yield format_keepalive
 else:
 # 延迟获取 run_id：send_message_stream 内部创建 OrchestrationRun
 if not run_id:
 latest = await OrchestrationRun.objects.filter(
 conversation_id=conversation_id,
 ).order_by("-created_at").afirst
 if latest:
 run_id = str(latest.run_id)
 yield format_sse(event, message_id=message_id, run_id=run_id)
 except Conversation.DoesNotExist:
 yield format_sse(
 AgentEvent(type=ERROR, data={"message": "对话不存在"}),
 message_id=message_id,
 run_id=run_id,
 )
 except ValueError as e:
 yield format_sse(
 AgentEvent(type=ERROR, data={"message": str(e)}),
 message_id=message_id,
 run_id=run_id,
 )
 except Exception:
 logger.exception("sse_stream_error", conversation_id=conversation_id)
 yield format_sse(
 AgentEvent(type=ERROR, data={"message": "服务内部错误"}),
 message_id=message_id,
 run_id=run_id,
 )
class ChatInterruptView(APIView):
 """中断活跃对话 — 支持 SDK 运行中断和 graph waiting 取消。"""
 authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
 permission_classes = [ChatAuthPermission]
 @extend_schema(
 summary="中断对话",
 description="中断正在进行的 AI 回复生成，支持 SDK 运行中断和 blocking tasks 等待中取消",
 responses={
 200: {"description": "中断成功"},
 404: {"description": "无活跃对话"},
 },
 tags=["Conversations"],
 )
 async def post(self, request, conversation_id):
 """中断活跃对话。
 场景 1: SDK 运行中 — 通过 runner.interrupt 中断 + 更新 DB 状态
 场景 2: graph waiting — 逐个取消 dispatched tasks + barrier.cancel_all
 """
 from orchestration.runner_registry import get_active_runner
 conv_id_str = str(conversation_id)
 # 场景 1: 检查是否有活跃 SDK runner
 runner = get_active_runner(conv_id_str)
 if runner:
 await runner.interrupt
 # 更新 OrchestrationRun 状态为 interrupted
 from orchestration.models import OrchestrationRun
 await OrchestrationRun.objects.filter(
 conversation_id=conv_id_str,
 status__in=[OrchestrationRun.Status.RUNNING, OrchestrationRun.Status.WAITING],
 ).aupdate(status=OrchestrationRun.Status.INTERRUPTED)
 await Conversation.objects.filter(id=conv_id_str).aupdate(
 status=Conversation.Status.INTERRUPTED,
 )
 # 标记最新 assistant 消息 metadata.status = interrupted
 from chat.models import Message
 latest_msg = await Message.objects.filter(
 conversation_id=conv_id_str,
 role=Message.Role.ASSISTANT,
 ).order_by("-created_at").afirst
 if latest_msg is not None:
 metadata = latest_msg.metadata if isinstance(latest_msg.metadata, dict) else {}
 metadata["status"] = "interrupted"
 latest_msg.metadata = metadata
 await latest_msg.asave(update_fields=["metadata"])
 return Response({"status": "interrupted"})
 # 场景 2: 检查是否有活跃 barrier（graph waiting 状态）
 from orchestration.barrier import get_barrier_manager
 from orchestration.models import OrchestrationRun
 barrier = get_barrier_manager
 if barrier.has_barrier_for_thread(conv_id_str):
 orch_run = await OrchestrationRun.objects.filter(
 conversation_id=conv_id_str,
 status=OrchestrationRun.Status.WAITING,
 ).order_by("-created_at").afirst
 if orch_run:
 run_id = str(orch_run.run_id)
 pending_tasks = barrier.get_pending_tasks(run_id)
 for task_info in pending_tasks:
 await _cancel_dispatched_task(task_info)
 await barrier.cancel_all(run_id)
 await Conversation.objects.filter(id=conv_id_str).aupdate(
 status=Conversation.Status.STOPPED,
 )
 return Response({"status": "cancelled"})
 return Response(
 {"error": "无活跃对话或对话已完成"},
 status=status.HTTP_404_NOT_FOUND,
 )
async def _cancel_dispatched_task(task_info: dict) -> None:
 """通过 TaskDispatcher 向 Runner 发送取消信号。"""
 from runners.dispatcher import get_dispatcher
 task_id = task_info.get("task_id", "")
 try:
 dispatcher = get_dispatcher
 await dispatcher.cancel(task_id)
 except Exception:
 logger.warning("dispatched_task_cancel_failed", task_id=task_id, exc_info=True)
# ============================================================================
# Export to Feishu (Phase)
# ============================================================================
class ExportToFeishuView(APIView):
 """导出对话消息到飞书文档（用户触发的 REST API 路径）。"""
 authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
 permission_classes = [ChatAuthPermission]
 async def post(self, request, conversation_id): # type: ignore[override]
 """导出选中的 assistant 消息为飞书文档。"""
 from agents.tools.feishu_doc_tools import create_feishu_doc_client_for_project
 from services.feishu_doc import FeishuDocAPIError, PermissionDeniedError
 from .models import Message
 serializer = ExportToFeishuSerializer(data=request.data)
 if not serializer.is_valid:
 return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
 try:
 conversation = await Conversation.objects.select_related("project").aget(
 id=conversation_id,
 is_deleted=False,
 )
 except Conversation.DoesNotExist:
 return Response({"error": "对话不存在"}, status=status.HTTP_404_NOT_FOUND)
 project = conversation.project
 message_ids = serializer.validated_data["message_ids"]
 title = serializer.validated_data["title"]
 folder_token = (
 serializer.validated_data.get("folder_token")
 or project.feishu_doc_folder_token
 )
 if not folder_token:
 return Response(
 {"error": "未配置导出文件夹", "error_type": "not_configured"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 安全：同时过滤 conversation_id 防止跨对话消息泄露 (T-)
 msgs = [
 msg
 async for msg in Message.objects.filter(
 id__in=message_ids,
 conversation_id=conversation_id,
 role=Message.Role.ASSISTANT,
 ).order_by("created_at")
 ]
 if not msgs:
 return Response(
 {"error": "未找到可导出的消息"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 #: 多条消息间用分隔线区分
 merged_content = "\n\n---\n\n".join(msg.content for msg in msgs)
 try:
 client = await create_feishu_doc_client_for_project(project)
 result = await client.create_document(
 title=title,
 folder_token=folder_token,
 content=merged_content,
 )
 exported_at = timezone.now.isoformat
 export_record = {
 "document_id": result["document_id"],
 "url": result["url"],
 "title": title,
 "exported_at": exported_at,
 }
 latest_msg = msgs[-1]
 _append_feishu_export_record(latest_msg, export_record)
 await latest_msg.asave(update_fields=["metadata"])
 return Response(
 {
 "document_id": result["document_id"],
 "url": result["url"],
 "title": title,
 "exported_at": exported_at,
 }
 )
 except ValueError as exc:
 return Response(
 {"error": str(exc), "error_type": "not_configured"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 except PermissionDeniedError:
 return Response(
 {"error": "飞书应用无该文件夹的写入权限", "error_type": "permission_denied"},
 status=status.HTTP_403_FORBIDDEN,
 )
 except FeishuDocAPIError as exc:
 logger.warning(
 "feishu_doc_export_failed",
 error=str(exc),
 conversation_id=str(conversation_id),
 )
 return Response(
 {"error": f"导出失败: {exc}", "error_type": "api_error"},
 status=status.HTTP_502_BAD_GATEWAY,
 )
# ============================================================================
# CodingSession Views (Phase)
# ============================================================================
class CodingSessionConfirmView(APIView):
 """POST /api/chat/coding-sessions/{id}/confirm/ -- 确认编码会话并 dispatch 到 Runner。"""
 authentication_classes = [OptionalJWTAuthentication]
 permission_classes = [IsAuthenticated]
 async def post(self, request, session_id): # type: ignore[override]
 """确认 draft CodingSession，创建 SubAgentSession 并 dispatch 到 Runner。"""
 from chat.coding_session_service import dispatch_coding_task
 from .models import CodingSession
 # 1. 获取 CodingSession
 try:
 coding_session = await CodingSession.objects.select_related(
 "repository", "conversation__project"
 ).aget(id=session_id)
 except CodingSession.DoesNotExist:
 return Response(
 {"detail": "CodingSession not found"},
 status=status.HTTP_404_NOT_FOUND,
 )
 # Phase: 处理前端传入的分支名覆盖
 branch_name = request.data.get("branch_name") if request.data else None
 if branch_name:
 from chat.branch_service import validate_branch_name
 validation = await validate_branch_name(
 branch_name, coding_session.repository_id,
 )
 if not validation.valid:
 return Response(
 {"detail": "; ".join(validation.errors)},
 status=status.HTTP_400_BAD_REQUEST,
 )
 coding_session.branch_name = branch_name
 await coding_session.asave(update_fields=["branch_name", "updated_at"])
 # 2. 状态机校验：只有 draft 可 confirm
 try:
 await coding_session.aconfirm
 except ValueError as exc:
 return Response(
 {"detail": str(exc)},
 status=status.HTTP_400_BAD_REQUEST,
 )
 repo = coding_session.repository
 project = coding_session.conversation.project
 # 3. 构建编码 prompt
 prompt = (
 f"你正在对项目「{project.name}」的代码仓库「{repo.name}」执行编码任务。\n\n"
 f"技术方案：\n{coding_session.tech_plan}\n\n"
 f"请根据以上技术方案进行编码实现，完成后创建 PR。"
 )
 # 4. dispatch 到 Runner（Runner 检查 + session 创建 + metadata + 分支校验 + dispatch）
 try:
 session_id_str = await dispatch_coding_task(
 coding_session,
 task_type="coding",
 prompt=prompt,
 )
 except RuntimeError:
 # Runner 不在线 — 回滚状态到 draft
 coding_session.status = CodingSession.Status.DRAFT
 await coding_session.asave(update_fields=["status", "updated_at"])
 return Response(
 {"detail": "没有可用的 Runner"},
 status=status.HTTP_503_SERVICE_UNAVAILABLE,
 )
 except ValueError as exc:
 # 分支名校验失败 — 回滚状态到 draft
 coding_session.status = CodingSession.Status.DRAFT
 await coding_session.asave(update_fields=["status", "updated_at"])
 return Response(
 {"detail": "分支名校验失败", "errors": str(exc)},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 5. 标记为 running
 await coding_session.arefresh_from_db
 await coding_session.amark_running(subagent_session_id=coding_session.subagent_session_id)
 logger.info(
 "coding_session_confirmed",
 coding_session_id=str(coding_session.id),
 session_id=session_id_str,
 )
 serializer = CodingSessionSerializer(coding_session)
 return Response(serializer.data)
class CommitConfirmView(APIView):
 """GET/POST /api/chat/coding-sessions/{id}/commit-confirm/
 GET: 返回 AI 建议的 commit message + 影响文件摘要
 POST: 接受用户编辑后的 commit message，resume CodingSession graph
 """
 authentication_classes = [OptionalJWTAuthentication]
 permission_classes = [IsAuthenticated]
 async def get(self, request, session_id): # type: ignore[override]
 """返回 AI 建议的 commit message 和影响文件列表。"""
 from .models import CodingSession
 try:
 coding_session = await CodingSession.objects.aget(id=session_id)
 except CodingSession.DoesNotExist:
 return Response(
 {"detail": "CodingSession not found"},
 status=status.HTTP_404_NOT_FOUND,
 )
 #: 状态校验 -- 仅 awaiting_confirmation + commit_message 步骤接受
 if not (
 coding_session.status == CodingSession.Status.AWAITING_CONFIRMATION
 and coding_session.confirmation_step == "commit_message"
 ):
 return Response(
 {"detail": "当前状态不支持此操作"},
 status=status.HTTP_409_CONFLICT,
 )
 return Response({
 "suggested_commit_message": coding_session.suggested_commit_message,
 "affected_files": coding_session.affected_files,
 })
 async def post(self, request, session_id): # type: ignore[override]
 """接受用户编辑后的 commit message 并 resume CodingSession graph。"""
 from .models import CodingSession
 try:
 coding_session = await CodingSession.objects.aget(id=session_id)
 except CodingSession.DoesNotExist:
 return Response(
 {"detail": "CodingSession not found"},
 status=status.HTTP_404_NOT_FOUND,
 )
 #: 状态校验
 if not (
 coding_session.status == CodingSession.Status.AWAITING_CONFIRMATION
 and coding_session.confirmation_step == "commit_message"
 ):
 return Response(
 {"detail": "当前状态不支持此操作"},
 status=status.HTTP_409_CONFLICT,
 )
 commit_message = request.data.get("commit_message", "").strip
 if not commit_message:
 return Response(
 {"detail": "commit message 不能为空"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 长度限制 (ASVS V5 Input Validation, T-)
 if len(commit_message) > 5000:
 return Response(
 {"detail": "commit message 超过最大长度限制"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # Resume CodingSession graph
 from langgraph.types import Command
 from orchestration.checkpointer import get_checkpointer
 from orchestration.coding_graph import build_coding_graph
 checkpointer = await get_checkpointer
 graph = build_coding_graph.compile(checkpointer=checkpointer)
 config = {"configurable": {"thread_id": f"coding-{coding_session.id}"}}
 await graph.ainvoke(Command(resume=commit_message), config=config)
 await coding_session.arefresh_from_db
 serializer = CodingSessionSerializer(coding_session)
 return Response(serializer.data)
class PRConfirmView(APIView):
 """GET/POST /api/chat/coding-sessions/{id}/pr-confirm/
 GET: 返回 AI 建议的 PR 标题、描述、默认 target_branch、branch_url
 POST: 接受用户编辑后的 PR 信息或跳过，resume CodingSession graph
 """
 authentication_classes = [OptionalJWTAuthentication]
 permission_classes = [IsAuthenticated]
 async def get(self, request, session_id): # type: ignore[override]
 from .models import CodingSession
 try:
 coding_session = await CodingSession.objects.select_related(
 "repository",
 ).aget(id=session_id)
 except CodingSession.DoesNotExist:
 return Response(
 {"detail": "CodingSession not found"},
 status=status.HTTP_404_NOT_FOUND,
 )
 #: 状态校验 -- 仅 awaiting_confirmation + pr_review
 if not (
 coding_session.status == CodingSession.Status.AWAITING_CONFIRMATION
 and coding_session.confirmation_step == "pr_review"
 ):
 return Response(
 {"detail": "当前状态不支持此操作"},
 status=status.HTTP_409_CONFLICT,
 )
 #: 构建 branch_url
 from orchestration.coding_graph import build_branch_url
 branch_url = build_branch_url(
 coding_session.repository.git_url,
 coding_session.repository.git_platform,
 coding_session.branch_name,
 )
 return Response({
 "suggested_pr_title": coding_session.suggested_pr_title,
 "suggested_pr_description": coding_session.suggested_pr_description,
 "target_branch": coding_session.repository.default_branch,
 "branch_url": branch_url,
 })
 async def post(self, request, session_id): # type: ignore[override]
 from .models import CodingSession
 try:
 coding_session = await CodingSession.objects.aget(id=session_id)
 except CodingSession.DoesNotExist:
 return Response(
 {"detail": "CodingSession not found"},
 status=status.HTTP_404_NOT_FOUND,
 )
 #: 状态校验
 if not (
 coding_session.status == CodingSession.Status.AWAITING_CONFIRMATION
 and coding_session.confirmation_step == "pr_review"
 ):
 return Response(
 {"detail": "当前状态不支持此操作"},
 status=status.HTTP_409_CONFLICT,
 )
 skip = request.data.get("skip", False)
 if skip:
 #: 跳过 PR 创建
 from langgraph.types import Command
 from orchestration.checkpointer import get_checkpointer
 from orchestration.coding_graph import build_coding_graph
 checkpointer = await get_checkpointer
 graph = build_coding_graph.compile(checkpointer=checkpointer)
 config = {"configurable": {"thread_id": f"coding-{coding_session.id}"}}
 await graph.ainvoke(
 Command(resume={"skip_pr": True}),
 config=config,
 )
 await coding_session.arefresh_from_db
 serializer = CodingSessionSerializer(coding_session)
 return Response(serializer.data)
 #: 非 skip 时校验字段
 title = request.data.get("title", "").strip
 description = request.data.get("description", "").strip
 target_branch = request.data.get("target_branch", "").strip
 if not title:
 return Response(
 {"detail": "PR 标题不能为空"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 if not description:
 return Response(
 {"detail": "PR 描述不能为空"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # ASVS V5 Input Validation: 长度限制
 if len(title) > 200:
 return Response(
 {"detail": "PR 标题超过最大长度限制（200 字符）"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 if len(description) > 10000:
 return Response(
 {"detail": "PR 描述超过最大长度限制（10000 字符）"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 if not target_branch:
 return Response(
 {"detail": "目标分支不能为空"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # Resume CodingSession graph
 from langgraph.types import Command
 from orchestration.checkpointer import get_checkpointer
 from orchestration.coding_graph import build_coding_graph
 checkpointer = await get_checkpointer
 graph = build_coding_graph.compile(checkpointer=checkpointer)
 config = {"configurable": {"thread_id": f"coding-{coding_session.id}"}}
 await graph.ainvoke(
 Command(resume={
 "skip_pr": False,
 "title": title,
 "description": description,
 "target_branch": target_branch,
 }),
 config=config,
 )
 await coding_session.arefresh_from_db
 serializer = CodingSessionSerializer(coding_session)
 return Response(serializer.data)
class ConflictCheckView(APIView):
 """GET /api/chat/coding-sessions/{id}/conflict-check/
 返回冲突预检结果（per ），供页面刷新恢复场景和前端主动查询。
 """
 authentication_classes = [OptionalJWTAuthentication]
 permission_classes = [IsAuthenticated]
 async def get(self, request, session_id): # type: ignore[override]
 from .models import CodingSession
 try:
 coding_session = await CodingSession.objects.aget(id=session_id)
 except CodingSession.DoesNotExist:
 return Response(
 {"detail": "CodingSession not found"},
 status=status.HTTP_404_NOT_FOUND,
 )
 return Response(coding_session.conflict_check_result or {})
class DiffSummaryView(APIView):
 """GET /api/chat/coding-sessions/{id}/diff-summary/
 返回相对 base 的 diff 摘要（per ）。
 文件级截断 + truncated 布尔标记，默认最多 50 文件（per ）。
 """
 authentication_classes = [OptionalJWTAuthentication]
 permission_classes = [IsAuthenticated]
 async def get(self, request, session_id): # type: ignore[override]
 from .models import CodingSession
 try:
 coding_session = await CodingSession.objects.aget(id=session_id)
 except CodingSession.DoesNotExist:
 return Response(
 {"detail": "CodingSession not found"},
 status=status.HTTP_404_NOT_FOUND,
 )
 return Response(coding_session.diff_summary or {})
class CodingSessionListView(APIView):
 """GET /api/chat/coding-sessions/ -- 按 conversation 查询 CodingSession 列表（ 恢复用）。"""
 authentication_classes = [OptionalJWTAuthentication]
 permission_classes = [IsAuthenticated]
 async def get(self, request): # type: ignore[override]
 """按 conversation_id 查询 CodingSession 列表。"""
 from .models import CodingSession
 conversation_id = request.query_params.get("conversation_id")
 if not conversation_id:
 return Response(
 {"detail": "conversation_id query parameter is required"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 验证 conversation 存在
 try:
 await Conversation.objects.select_related("project").aget(id=conversation_id)
 except Conversation.DoesNotExist:
 return Response(, status=status.HTTP_200_OK)
 sessions = [
 session
 async for session in CodingSession.objects.filter(
 conversation_id=conversation_id
 ).order_by("-created_at")
 ]
 serializer = CodingSessionSerializer(sessions, many=True)
 return Response(serializer.data)
class CodingSessionDetailView(APIView):
 """GET /api/chat/coding-sessions/{id}/ -- CodingSession 详情。"""
 authentication_classes = [OptionalJWTAuthentication]
 permission_classes = [IsAuthenticated]
 async def get(self, request, session_id): # type: ignore[override]
 """返回 CodingSession 详情。"""
 from .models import CodingSession
 try:
 session = await CodingSession.objects.aget(id=session_id)
 except CodingSession.DoesNotExist:
 return Response(
 {"detail": "CodingSession not found"},
 status=status.HTTP_404_NOT_FOUND,
 )
 serializer = CodingSessionSerializer(session)
 return Response(serializer.data)
