"""Chat API views."""

import asyncio
import contextvars
import time
from pathlib import Path
from typing import Any

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError
from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from agents.core.events import ERROR, KEEPALIVE, AgentEvent
from chat.coding_session_service import check_runner_online
from chat.multimodal import (
    ImageValidationError,
    build_image_part,
    read_image_bytes,
    store_image_bytes,
)
from common.log_context import LogSource, bind_source
from common.request_metrics import arecord_request_metric, classify_error
from feishu.coding_plan_exporter import export_coding_plan_to_feishu
from orchestration.checkpointer import get_checkpointer
from orchestration.coding_graph import build_coding_graph
from projects.models import Project

from .authentication import ChatKeyAuthentication, OptionalJWTAuthentication
from .conversation_service import ConversationService
from .models import Conversation
from .permissions import ChatAuthPermission
from .serializers import (
    ChatCompletionRequestSerializer,
    ChatCompletionResponseSerializer,
    ClarificationAnswerSerializer,
    CodingPlanSerializer,
    CodingSessionsBatchCreateRequestSerializer,
    CodingSessionsBatchCreateResponseSerializer,
    CodingSessionSerializer,
    ConversationDetailSerializer,
    ConversationForkRequestSerializer,
    ConversationListSerializer,
    ConversationMessageSerializer,
    ConversationPatchSerializer,
    ConversationRuntimeSerializer,
    CreateConversationSerializer,
    ExportCodingPlanToFeishuSerializer,
    ExportToFeishuSerializer,
    ModelsRequestSerializer,
    ModelsResponseSerializer,
    RoutingTraceManualOverrideSerializer,
    SendMessageSerializer,
    WebPushPublicKeySerializer,
    WebPushSubscriptionSerializer,
    WebPushUnsubscribeSerializer,
)
from .services import ChatMessage, ChatServiceError, aget_chat_service
from .streaming import format_keepalive, format_sse

logger = structlog.get_logger(__name__)
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def _append_feishu_export_record(message, record: dict[str, str]) -> None:
    """Persist export history on message metadata for refresh-safe recovery."""
    metadata = message.metadata if isinstance(message.metadata, dict) else {}
    raw_exports = metadata.get("feishu_exports", [])
    exports = raw_exports if isinstance(raw_exports, list) else []

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
        if not serializer.is_valid():
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

            models = await service.get_models()

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

    # implementation OpenAI compat 兼容性：除默认 Cookie JWT 外，再接受 Bearer JWT 与
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
        if not serializer.is_valid():
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


class ChatImageUploadView(APIView):
    """Upload one Web Chat image and return a storage-backed ImagePart."""

    authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
    permission_classes = [ChatAuthPermission]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        summary="上传聊天图片",
        description="上传 PNG/JPEG/GIF/WebP 图片并返回可用于 input_parts 的 image part",
        responses={
            201: {"description": "图片 part"},
            400: {"description": "图片格式、大小或内容无效"},
        },
        tags=["Conversations"],
    )
    async def post(self, request):
        uploaded = request.FILES.get("image") or request.FILES.get("file")
        if uploaded is None:
            return Response(
                {"code": "missing_image", "error": "请上传图片文件"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            data = await sync_to_async(uploaded.read)()
            stored = await sync_to_async(store_image_bytes)(
                data,
                declared_mime_type=getattr(uploaded, "content_type", "") or "",
                source="web",
                filename=getattr(uploaded, "name", "") or "",
            )
            part = build_image_part(
                index=0,
                mime_type=stored.mime_type,
                size_bytes=stored.size_bytes,
                storage_ref=stored.storage_ref,
                source_url=f"/api/chat/images/{Path(stored.storage_ref).name}/",
                alt_text=getattr(uploaded, "name", "") or "",
            )
            return Response({"part": part}, status=status.HTTP_201_CREATED)
        except ImageValidationError as exc:
            return Response(
                {"code": exc.code, "error": exc.message},
                status=status.HTTP_400_BAD_REQUEST,
            )


class ChatImageView(APIView):
    """Serve stored chat images through the authenticated chat API surface."""

    authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
    permission_classes = [ChatAuthPermission]

    async def get(self, request, file_name: str):
        storage_ref = f"chat_images/{file_name}"
        try:
            data = await sync_to_async(read_image_bytes)(storage_ref)
        except ImageValidationError as exc:
            return Response(
                {"code": exc.code, "error": exc.message},
                status=status.HTTP_404_NOT_FOUND,
            )

        suffix = Path(file_name).suffix.lower()
        content_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }.get(suffix, "application/octet-stream")
        return HttpResponse(data, content_type=content_type)


# ============================================================================
# Conversation Views (implementation)
# ============================================================================


class ConversationListView(APIView):
    """对话列表 + 创建。"""

    authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
    permission_classes = [ChatAuthPermission]

    @extend_schema(
        summary="获取对话列表",
        description=(
            "返回未删除、未归档的对话列表，按 updated_at 降序，默认取前 50 条。"
            "支持 ?q= 关键词搜索（匹配标题或消息内容）、?limit= 自定义条数。"
        ),
        responses={200: ConversationListSerializer(many=True)},
        tags=["Conversations"],
    )
    async def get(self, request):
        """获取对话列表（支持内容搜索 + top N）。"""
        q = request.query_params.get("q") or request.query_params.get("search")
        limit_raw = request.query_params.get("limit")
        try:
            limit = int(limit_raw) if limit_raw else 50
        except (TypeError, ValueError):
            limit = 50
        # 兜底裁剪到合理范围，防止超大 limit 拖垮内容搜索 join。
        limit = max(1, min(limit, 200))
        # ?archived=1 → 仅返回已归档会话（「查看已归档」入口）。
        archived_raw = (request.query_params.get("archived") or "").lower()
        archived_only = archived_raw in {"1", "true", "yes"}
        # owner gate（ISO-02）：已认证用户仅列自己的会话，无 superuser bypass。
        conversations = await ConversationService.list_conversations(
            request.user, query=q, limit=limit, archived_only=archived_only,
        )
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
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        # space_id 可空：None 表示创建不绑定空间的通用对话
        space_id = str(data["space_id"]) if data.get("space_id") else None
        title = data.get("title", "新对话")
        model = data.get("model", "")

        # 验证 project 存在（仅在指定了空间时）
        if space_id is not None:
            try:
                await Project.objects.aget(id=space_id)
            except Project.DoesNotExist:
                return Response(
                    {"error": f"空间不存在: {space_id}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # owner 注入（ISO-01）：已认证写 created_by=request.user，匿名/开放模式写 null。
        conversation = await ConversationService.create_conversation(
            space_id=space_id,
            title=title,
            model=model,
            user=request.user,
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

        implementation contract contract：响应扩展 resolved_provider 字段 = {provider_type,
        model, source, chain: [4 层]}。
        """
        # owner gate（ISO-04）：先于任何取数/序列化做 owner-scoped 存在性校验，
        # 越权/不存在统一 404，杜绝存在性泄漏（无 superuser bypass）。
        try:
            await ConversationService.aget_for_user(
                str(conversation_id), request.user
            )
        except Conversation.DoesNotExist:
            return Response(
                {"error": "对话不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

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

        # implementation contract contract：四层 Provider 解析 Inspector
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

        # 最新跨仓路由决策 trace —— 刷新后 hydrate routingStore，让 RelevanceBadge
        # 等依赖 routing trace 的徽章能回显（否则 routingStore 纯内存刷新即空）。
        from chat.models import RepositoryRoutingTrace

        latest_trace = await RepositoryRoutingTrace.objects.filter(
            conversation_id=conversation.id,
        ).order_by("-created_at").afirst()
        routing_trace_payload: dict[str, Any] | None = None
        if latest_trace is not None:
            routing_trace_payload = {
                "trace_id": str(latest_trace.id),
                "query": latest_trace.query,
                "candidates": latest_trace.candidates if isinstance(latest_trace.candidates, list) else [],
                "threshold": latest_trace.threshold,
                "triggered_by": latest_trace.triggered_by,
            }

        # 已回复的协商卡（ConversationIntentTrace）—— 刷新 / 切回会话时回显
        # ClarificationCard 的「已回复」态（待回复态由 runtime.pending_clarification
        # 提供）。只取 answered，避免历史脏数据里未回复的 trace 复活成幽灵卡片。
        from chat.models import ConversationIntentTrace

        clarifications_payload: list[dict[str, Any]] = []
        async for trace in ConversationIntentTrace.objects.filter(
            conversation_id=conversation.id,
            answered_at__isnull=False,
        ).order_by("created_at"):
            clarifications_payload.append({
                "clarification_id": trace.clarification_id,
                "question": trace.question,
                "options": trace.options if isinstance(trace.options, list) else [],
                "allow_freeform": True,
                "status": "answered",
                "answer": {
                    "selected_option_id": trace.selected_option_id or "",
                    "freeform_text": trace.freeform_answer or "",
                    "answered_at": trace.answered_at.isoformat() if trace.answered_at else "",
                },
                "triggering_message_id": trace.triggering_message_id or "",
            })

        # UAT 第 3 项 hotfix（follow-up）：detail 响应补齐 model + status +
        # provider_credential_id，与 list 字段对齐；conversation_prefetched 已 select_related
        # provider_credential_id（async-safe），直接读 FK 的 _id 列即可。
        response_data = {
            "id": str(conversation.id),
            "space_id": str(conversation.project_id) if conversation.project_id else None,
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
            "clarifications": clarifications_payload,
            "routing_trace": routing_trace_payload,
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
        # owner gate（ISO-04）：owner-scoped 软删，0 行更新 → DoesNotExist → 404。
        try:
            await ConversationService.delete_conversation(
                str(conversation_id), request.user
            )
        except Conversation.DoesNotExist:
            return Response(
                {"error": "对话不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="更新对话（pin 语义）",
        description=(
            "部分更新对话的 provider_credential_id / model / title / space_id。"
            "frozen 状态（completed/stopped/error）下拒绝修改 provider_credential_id 和 model，"
            "返回 HTTP 400 + {code: 'conversation_frozen'}（implementation contract contract 后端防御）。"
            "space_id 切换会话绑定空间（null 切回通用对话），running 态拒绝。"
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
        """implementation contract contract/contract：对话 pin 更新 + frozen 校验。"""
        # 1. owner gate（ISO-04）：owner-scoped 存在性校验，越权/不存在统一 404。
        try:
            conversation = await ConversationService.aget_for_user(
                str(conversation_id), request.user
            )
        except Conversation.DoesNotExist:
            return Response(
                {"error": "对话不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 2. Frozen 校验（contract 双重防御）
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

        # 4. 空间切换（会话内切换空间）：running 态拒绝（流式中切换语义混乱），
        # 不受 frozen 拦截（与 title 同等待遇）。委托 service 落库 space_switch 系统消息。
        data = serializer.validated_data
        if "space_id" in data:
            if conversation.status == Conversation.Status.RUNNING:
                return Response(
                    {
                        "code": "conversation_running",
                        "detail": "对话进行中，无法切换空间，请等待本轮回答完成",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                await ConversationService.switch_space(
                    conversation,
                    str(data["space_id"]) if data["space_id"] else None,
                )
            except ValueError as exc:
                return Response(
                    {"error": str(exc)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # 5. 应用变更（provider_credential_id 需写 FK 的 _id 列；Django 生成的 DB 列名
        # 为 `<field_name>_id` → 对本字段即 `provider_credential_id_id`，setattr 更稳妥。）
        updated_fields: list[str] = []
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
        if "is_archived" in data:
            # 归档与 frozen 正交：任何状态都可归档/取消归档。
            conversation.is_archived = data["is_archived"]
            updated_fields.append("is_archived")

        if updated_fields:
            updated_fields.append("updated_at")
            await sync_to_async(conversation.save)(update_fields=updated_fields)

        logger.info(
            "conversation.patch_applied",
            conversation_id=str(conversation.id),
            fields_updated=list(data.keys()),
        )

        # 6. 响应（复用 ConversationDetailSerializer）
        # UAT 第 3 项 hotfix（follow-up）：补齐 model + status + provider_credential_id，
        # 让前端 patchConversationCredential 直接拿响应回填本地 conversations[]，
        # 触发 currentConversation getter 反映新 pin。
        return Response(
            {
                "id": str(conversation.id),
                "space_id": str(conversation.project_id) if conversation.project_id else None,
                "title": conversation.title,
                "model": conversation.model,
                "status": conversation.status,
                "provider_credential_id": (
                    str(conversation.provider_credential_id_id)
                    if conversation.provider_credential_id_id
                    else None
                ),
                "is_archived": conversation.is_archived,
                "created_at": conversation.created_at,
                "updated_at": conversation.updated_at,
                "messages": [],
            },
        )


class ConversationPreflightView(APIView):
    """implementation contract contract：对话凭证前置探测（不发送 user message）。

    用于 ChatMessageArea 在用户进入对话 / 按 Send / 切换 Provider 时提前判定：
        - 若凭证解析成功 → 200 `{status: "ok", resolved: {...}}`，允许正常 Send。
        - 若四层均无凭证 → 400 `{code: "provider_credential_missing", data: {...}}`，
          前端渲染 ProviderCredentialMissingCard（contract 按角色分流 CTA）。

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
            "ProviderCredentialMissingCard（implementation contract contract）。"
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

        # owner gate（ISO-04，主/外层）：置于 select_related 预取之后、has_project_access
        # 与 aresolve_or_error 之前 —— owner-miss → 404，避免 provider payload 信息泄漏
        # （T-08-08）。用 created_by_id 比对避免 async 惰性 FK；无 superuser bypass（ISO-03）。
        user = request.user
        if (
            getattr(user, "is_authenticated", False)
            and conversation.created_by_id != user.id
        ):
            return Response(
                {"error": "对话不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # [implementation] Ownership 校验（security mitigation）
        # 模式与 ConversationMessagesDeleteView.delete work item 完全一致，仅：
        #   min_role: "member" → "viewer"（preflight 是只读探测）
        #   event name: "chat.cleanup_denied_cross_project" → "chat.preflight_denied_cross_project"
        #   detail: "无权删除其他项目的对话消息" → "无权访问该对话"
        # 放置位置：owner gate 之后，作 null-owner/共享行的次层防御（保留既有 403 语义）。
        from permissions.services import PermissionService
        if (
            getattr(user, "is_authenticated", False)
            and not getattr(user, "is_superuser", False)
            and conversation.project_id is not None
            # 已确认的 owner 已由上方 owner gate 授权，不再叠加 project 403；
            # 次层 has_project_access 仅作 null-owner/共享行的兜底（保留既有语义）。
            and conversation.created_by_id != user.id
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

        # Resolved：平铺 ResolvedProviderConfig 中的公开字段（不含 api_key 明文 security mitigation-01）
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
        # owner gate（ISO-04）：owner-scoped 存在性校验，越权/不存在统一 404。
        try:
            await ConversationService.aget_for_user(
                str(conversation_id), request.user
            )
        except Conversation.DoesNotExist:
            return Response(
                {"error": "对话不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        runtime = await ConversationService.get_conversation_runtime(str(conversation_id))
        return Response(runtime)


class ConversationMessagesDeleteView(APIView):
    """implementation contract contract：对话历史消息批量清理端点。

    路由：``DELETE /api/chat/conversations/{conversation_id}/messages/?before_id=X``

    语义（plan Behavior C-H 契约）：
        - 硬删 conversation 内 ``created_at < target_message.created_at`` 的消息
          （Message 模型无 ``is_deleted`` 字段 → 真删）
        - ``before_id`` 必填；空/缺失 → 400
        - ``conversation_id`` 不存在 → 404
        - ``before_id`` 指向的消息不属于本 conversation → 400（防跨 conversation 篡改）
        - Ownership 校验：非 superuser 必须有 conversation.project MEMBER+ 权限；
          跨项目越权 → 403 + audit log ``chat.cleanup_denied_cross_project``
        - 成功返回 ``{"deleted_count": N}`` + audit log ``chat.messages_cleaned``

    Threat model（security mitigation-01/02/03）：
        - Ownership 校验 via PermissionService.has_project_access(MEMBER+)
        - before_id 归属校验通过 Django ORM filter(conversation=conv) 强制（Tampering 防御）
        - 硬删不可恢复 → UI 层必须有二次确认（plan Task 2 CleanupDialog 中的 AlertDialog）
    """

    authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
    permission_classes = [ChatAuthPermission]

    @extend_schema(
        summary="批量删除对话历史消息",
        description=(
            "硬删 before_id 之前的所有消息（created_at 升序）。受 ownership 校验；"
            "conversation.project 需 user 有 MEMBER+ 权限（superuser 豁免）。"
            "implementation contract contract。"
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

        # 2.5 owner gate（ISO-04，主/外层）：先于 has_project_access，owner-miss → 404
        # （避免任意中断/篡改与存在性泄漏）；用 created_by_id 避免 async 惰性 FK；无 superuser bypass。
        user = request.user
        if (
            getattr(user, "is_authenticated", False)
            and conversation.created_by_id != user.id
        ):
            return Response(
                {"error": "对话不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 3. Ownership 校验（security mitigation-01 mitigate）：非 superuser 必须有 MEMBER+ 权限
        if (
            getattr(user, "is_authenticated", False)
            and not getattr(user, "is_superuser", False)
            and conversation.project_id is not None
            # 已确认的 owner 已由上方 owner gate 授权，不再叠加 project 403；
            # 次层 has_project_access 仅作 null-owner/共享行的兜底（保留既有语义）。
            and conversation.created_by_id != user.id
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

        # 4. before_id 必须指向本 conversation 的消息（security mitigation-03 Tampering 防御）
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
        ).adelete()

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


class ConversationMessageForkView(APIView):
    """编辑历史 user message 前创建新 conversation 分支。"""

    authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
    permission_classes = [ChatAuthPermission]

    @extend_schema(
        summary="编辑历史提问前创建会话分支",
        description=(
            "复制目标 user message 之前的历史到新 conversation；编辑后的内容由随后现有 "
            "SSE sendMessage 路径写入，原 conversation 保持不变。"
        ),
        request=ConversationForkRequestSerializer,
        responses={
            201: ConversationDetailSerializer,
            400: {"description": "请求参数错误或目标消息不可编辑"},
            403: {"description": "无权访问该对话"},
            404: {"description": "对话不存在"},
        },
        tags=["Conversations"],
    )
    async def post(self, request, conversation_id, message_id):
        serializer = ConversationForkRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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

        from permissions.services import PermissionService

        # owner gate（ISO-04，主/外层）：先于 has_project_access，owner-miss → 404；
        # 本期 fork 仅限自己（管理员 fork 他人留 Phase 9）；无 superuser bypass。
        user = request.user
        if (
            getattr(user, "is_authenticated", False)
            and conversation.created_by_id != user.id
        ):
            return Response(
                {"error": "对话不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if (
            getattr(user, "is_authenticated", False)
            and not getattr(user, "is_superuser", False)
            and conversation.project_id is not None
            # 已确认的 owner 已由上方 owner gate 授权，不再叠加 project 403；
            # 次层 has_project_access 仅作 null-owner/共享行的兜底（保留既有语义）。
            and conversation.created_by_id != user.id
        ):
            has_access = await sync_to_async(PermissionService.has_project_access)(
                user, conversation.project, "member"
            )
            if not has_access:
                logger.warning(
                    "chat.fork_denied_cross_project",
                    user_id=str(getattr(user, "id", "")),
                    conversation_id=str(conversation.id),
                    space_id=str(conversation.project_id),
                )
                return Response(
                    {"detail": "无权编辑该对话"},
                    status=status.HTTP_403_FORBIDDEN,
                )

        try:
            result = await ConversationService.fork_conversation_before_message(
                str(conversation_id),
                str(message_id),
                serializer.validated_data["content"],
            )
        except Conversation.DoesNotExist:
            return Response(
                {"error": "对话不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        forked = result["conversation"]
        messages = result["messages"]
        response_data = {
            "id": str(forked.id),
            "space_id": str(forked.project_id) if forked.project_id else None,
            "title": forked.title,
            "model": forked.model,
            "status": forked.status,
            "provider_credential_id": (
                str(forked.provider_credential_id_id)
                if forked.provider_credential_id_id
                else None
            ),
            "created_at": forked.created_at,
            "updated_at": forked.updated_at,
            "messages": ConversationMessageSerializer(messages, many=True).data,
        }
        return Response(response_data, status=status.HTTP_201_CREATED)


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

        config = await ChatPushService.aget_or_create_vapid_config()
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
        if not serializer.is_valid():
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
        if not serializer.is_valid():
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
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        content = serializer.validated_data["content"]
        input_parts = serializer.validated_data.get("input_parts") or []
        role = serializer.validated_data.get("role", "developer")
        force_deep_analysis = serializer.validated_data.get("force_deep_analysis", False)
        feishu_doc_id = serializer.validated_data.get("feishu_doc_id", "")
        branch_raw = serializer.validated_data.get("branch", "") or ""
        search_branch = branch_raw.strip() or None

        # owner gate（ISO-04，Pitfall 5）：必须在 StreamingHttpResponse 构造之前
        # 做 owner-scoped 存在性校验，越权返回干净 HTTP 404 而非 text/event-stream
        # 内的 error 事件；无 superuser bypass。
        try:
            await ConversationService.aget_for_user(
                str(conversation_id), request.user
            )
        except Conversation.DoesNotExist:
            return Response(
                {"error": "对话不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # source 改写为 chat_sse（覆盖中间件 rest 占位）：让中间件跳过兜底记录，
        # 由 _stream_events 在流结束记带 ttft 的指标行（避免重复计数）。
        bind_source(LogSource.CHAT_SSE)
        user_id = (
            str(request.user.id)
            if getattr(request.user, "is_authenticated", False)
            else "system"
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
                input_parts=input_parts or None,
                metric_user_id=user_id,
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
        input_parts: list[dict[str, Any]] | None = None,
        metric_user_id: str = "system",
    ):
        """生成 SSE 事件流。"""
        import uuid as uuid_mod

        from orchestration.models import OrchestrationRun

        message_id = str(uuid_mod.uuid4())

        # 指标埋点（RATE-01 / SLA-04，source=chat_sse）：首个真实 chunk 计 ttft_ms，
        # 生成器结束（finally）记一行总 duration_ms。best-effort，绝不打断 SSE。
        _metric_started = time.perf_counter()
        _metric_ttft_ms: int | None = None
        _metric_error_class = "none"

        # 获取当前 OrchestrationRun.run_id 用于所有 SSE 事件（work item）
        run_id = ""
        orch_run = await OrchestrationRun.objects.filter(
            conversation_id=conversation_id,
        ).order_by("-created_at").afirst()
        if orch_run:
            run_id = str(orch_run.run_id)

        try:
            stream_kwargs: dict[str, Any] = {
                "force_deep_analysis": force_deep_analysis,
                "feishu_doc_id": feishu_doc_id,
                "search_branch": search_branch,
            }
            if input_parts is not None:
                stream_kwargs["input_parts"] = input_parts

            async for event in ConversationService.send_message_stream(
                conversation_id=conversation_id,
                content=content,
                role=role,
                notification_user_id=notification_user_id,
                **stream_kwargs,
            ):
                if event.type == KEEPALIVE:
                    yield format_keepalive()
                else:
                    # 首个真实业务 chunk 的时刻 = ttft_ms（keepalive 不计）。
                    if _metric_ttft_ms is None:
                        _metric_ttft_ms = max(
                            int((time.perf_counter() - _metric_started) * 1000), 0
                        )
                    # 延迟获取 run_id：send_message_stream 内部创建 OrchestrationRun
                    if not run_id:
                        latest = await OrchestrationRun.objects.filter(
                            conversation_id=conversation_id,
                        ).order_by("-created_at").afirst()
                        if latest:
                            run_id = str(latest.run_id)
                    yield format_sse(event, message_id=message_id, run_id=run_id)
        except Conversation.DoesNotExist:
            _metric_error_class = "business"
            yield format_sse(
                AgentEvent(type=ERROR, data={"message": "对话不存在"}),
                message_id=message_id,
                run_id=run_id,
            )
        except ValueError as e:
            _metric_error_class = classify_error(exc=e)
            yield format_sse(
                AgentEvent(type=ERROR, data={"message": str(e)}),
                message_id=message_id,
                run_id=run_id,
            )
        except Exception as e:  # noqa: BLE001
            _metric_error_class = classify_error(exc=e)
            logger.exception("sse_stream_error", conversation_id=conversation_id)
            yield format_sse(
                AgentEvent(type=ERROR, data={"message": "服务内部错误"}),
                message_id=message_id,
                run_id=run_id,
            )
        finally:
            _metric_duration_ms = max(int((time.perf_counter() - _metric_started) * 1000), 0)
            await arecord_request_metric(
                source=LogSource.CHAT_SSE.value,
                route="/api/chat/conversations/{id}/stream",
                method="POST",
                status_code=200,
                error_class=_metric_error_class,
                duration_ms=_metric_duration_ms,
                ttft_ms=_metric_ttft_ms,
                user_id=metric_user_id,
                labels={"conversation_id": str(conversation_id)},
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

        场景 1: SDK 运行中 — 通过 runner.interrupt() 中断 + 更新 DB 状态
        场景 2: graph waiting — 逐个取消 dispatched tasks + barrier.cancel_all()
        """
        from orchestration.runner_registry import get_active_runner

        conv_id_str = str(conversation_id)

        # owner gate（ISO-04，T-08-11）：在执行 runner.interrupt()/barrier 取消之前
        # 做 owner-scoped 存在性校验，防任意用户中断他人 run；越权/不存在统一 404；
        # 无 superuser bypass。保留下方「无活跃对话」原有 404 分支。
        try:
            await ConversationService.aget_for_user(conv_id_str, request.user)
        except Conversation.DoesNotExist:
            return Response(
                {"error": "对话不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 场景 1: 检查是否有活跃 SDK runner
        runner = get_active_runner(conv_id_str)
        if runner:
            await runner.interrupt()

            # 更新 OrchestrationRun 状态为 interrupted（work item）
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
            ).order_by("-created_at").afirst()
            if latest_msg is not None:
                metadata = latest_msg.metadata if isinstance(latest_msg.metadata, dict) else {}
                metadata["status"] = "interrupted"
                latest_msg.metadata = metadata
                await latest_msg.asave(update_fields=["metadata"])

            return Response({"status": "interrupted"})

        # 场景 2: 检查是否有活跃 barrier（graph waiting 状态）
        from orchestration.barrier import get_barrier_manager
        from orchestration.models import OrchestrationRun

        barrier = get_barrier_manager()
        if barrier.has_barrier_for_thread(conv_id_str):
            orch_run = await OrchestrationRun.objects.filter(
                conversation_id=conv_id_str,
                status=OrchestrationRun.Status.WAITING,
            ).order_by("-created_at").afirst()

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
        dispatcher = get_dispatcher()
        await dispatcher.cancel(task_id)
    except Exception:
        logger.warning("dispatched_task_cancel_failed", task_id=task_id, exc_info=True)


# ============================================================================
# Export to Feishu (implementation)
# ============================================================================


class ExportToFeishuView(APIView):
    """导出对话消息到飞书文档（用户触发的 REST API 路径）。"""

    authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
    permission_classes = [ChatAuthPermission]

    async def post(self, request, conversation_id):  # type: ignore[override]
        """导出选中的 assistant 消息为飞书文档。"""
        from agents.tools.feishu_doc_tools import create_feishu_doc_client_for_project
        from services.feishu_doc import FeishuDocAPIError, PermissionDeniedError

        from .models import Message

        serializer = ExportToFeishuSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            conversation = await Conversation.objects.select_related("project").aget(
                id=conversation_id,
                is_deleted=False,
            )
        except Conversation.DoesNotExist:
            return Response({"error": "对话不存在"}, status=status.HTTP_404_NOT_FOUND)

        # owner gate（ISO-04）：在读取 project / messages 之前做 owner-scoped 校验，
        # 越权 → 404；用 created_by_id 避免 async 惰性 FK；无 superuser bypass。
        user = request.user
        if (
            getattr(user, "is_authenticated", False)
            and conversation.created_by_id != user.id
        ):
            return Response({"error": "对话不存在"}, status=status.HTTP_404_NOT_FOUND)

        project = conversation.project
        if project is None:
            # 无空间通用对话：没有飞书凭证与文件夹来源，导出不可用
            return Response(
                {"error": "当前对话未绑定空间，无法导出到飞书", "error_type": "not_configured"},
                status=status.HTTP_400_BAD_REQUEST,
            )
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

        # 安全：同时过滤 conversation_id 防止跨对话消息泄露 (security mitigation)
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

        # contract: 多条消息间用分隔线区分
        merged_content = "\n\n---\n\n".join(msg.content for msg in msgs)

        try:
            client = await create_feishu_doc_client_for_project(project)
            result = await client.create_document(
                title=title,
                folder_token=folder_token,
                content=merged_content,
            )
            exported_at = timezone.now().isoformat()
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


class FeishuExportAvailabilityView(APIView):
    """飞书文档导出可用性探测（前端按需隐藏「导出到飞书」按钮）。

    判定逻辑与 ExportToFeishuView 实际依赖一致：
        1. 必须有空间（无空间通用对话不可导出）
        2. 空间必须配置导出文件夹 feishu_doc_folder_token
        3. 凭证：空间级飞书 App（feishu_app_id + secret）或系统级 SystemSetting 兜底
    """

    authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
    permission_classes = [ChatAuthPermission]

    @extend_schema(
        summary="飞书导出可用性",
        description="按 space_id 探测「导出到飞书」是否可用，返回 {available, reason}",
        responses={200: {"description": "{available: bool, reason: str|null}"}},
        tags=["Conversations"],
    )
    async def get(self, request):
        space_id = request.query_params.get("space_id") or ""
        if not space_id:
            return Response({"available": False, "reason": "no_space"})

        try:
            project = await Project.objects.aget(id=space_id)
        except (Project.DoesNotExist, ValueError, ValidationError):
            return Response({"available": False, "reason": "space_not_found"})

        if not project.feishu_doc_folder_token:
            return Response({"available": False, "reason": "no_folder_token"})

        if project.feishu_app_id and project.feishu_app_secret_encrypted:
            return Response({"available": True, "reason": None})

        from agents.tools.feishu_doc_tools import (
            _aget_system_feishu_credentials_for_doc,
        )

        credentials = await _aget_system_feishu_credentials_for_doc()
        if credentials:
            return Response({"available": True, "reason": None})
        return Response({"available": False, "reason": "no_credentials"})


# ============================================================================
# Export CodingPlan to Feishu (implementation / work item)
# ============================================================================


class ExportCodingPlanToFeishuView(APIView):
    """导出 CodingPlan 到飞书文档（用户从 TechPlanCard 触发）。

    与 ``ExportToFeishuView`` 同模式（认证 / 异常映射），数据源换成
    ``CodingPlan`` + 关联 sessions；具体 markdown 拼接与飞书 API 调用
    委托给 ``feishu.coding_plan_exporter.export_coding_plan_to_feishu``。
    """

    authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]
    permission_classes = [ChatAuthPermission]

    async def post(self, request, coding_plan_id):  # type: ignore[override]
        from services.feishu_doc import FeishuDocAPIError, PermissionDeniedError

        from .models import CodingPlan

        serializer = ExportCodingPlanToFeishuSerializer(data=request.data or {})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            coding_plan = await CodingPlan.objects.select_related(
                "conversation__project"
            ).aget(id=coding_plan_id)
        except CodingPlan.DoesNotExist:
            return Response(
                {"error": "方案不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # owner gate（ISO-04）：经 plan.conversation 反查 owner，置于读取 project 之前，
        # 越权 → 404（与「不存在」同体）；用 created_by_id 避免 async 惰性 FK；无 superuser bypass。
        user = request.user
        if (
            getattr(user, "is_authenticated", False)
            and coding_plan.conversation.created_by_id != user.id
        ):
            return Response(
                {"error": "方案不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        project = coding_plan.conversation.project
        title = serializer.validated_data.get("title") or None
        folder_token = (
            serializer.validated_data.get("folder_token")
            or project.feishu_doc_folder_token
        )

        if not folder_token:
            return Response(
                {"error": "未配置导出文件夹", "error_type": "not_configured"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = await export_coding_plan_to_feishu(
                coding_plan=coding_plan,
                folder_token=folder_token,
                title=title,
            )
        except ValueError as exc:
            return Response(
                {"error": str(exc), "error_type": "not_configured"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except PermissionDeniedError:
            return Response(
                {
                    "error": "飞书应用无该文件夹的写入权限",
                    "error_type": "permission_denied",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        except FeishuDocAPIError as exc:
            logger.warning(
                "coding_plan_feishu_export_failed",
                error=str(exc),
                coding_plan_id=str(coding_plan_id),
            )
            return Response(
                {"error": f"导出失败: {exc}", "error_type": "api_error"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "doc_token": result["doc_token"],
                "doc_url": result["doc_url"],
                "title": title or coding_plan.title,
                "exported_at": timezone.now().isoformat(),
            }
        )


# ============================================================================
# CodingSession Views (implementation)
# ============================================================================


class CodingSessionConfirmView(APIView):
    """POST /api/chat/coding-sessions/{id}/confirm/ -- 确认编码会话并 dispatch 到 Runner。"""

    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [IsAuthenticated]

    async def post(self, request, session_id):  # type: ignore[override]
        """确认 draft CodingSession，启动 coding_graph 后台任务。

        implementation contract：本 view 不再直接调用 `dispatch_coding_task`，改为
        构建 `coding_graph` 并以 `asyncio.create_task` 异步驱动；同步前置仅做
        branch_name 校验、`aconfirm()` 与 Runner 在线探测。状态推进（confirmed
        -> running）由 graph 的 `dispatch_coding_node` 负责。
        """
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

        # owner gate（ISO-04，主/外层）：经 session.conversation 反查 owner，置于
        # 任何状态机校验/字段读取之前；越权 → 404（与「未找到」同体，隐藏存在性）。
        # 用 created_by_id 比对避免 async 惰性 FK；无 superuser bypass（ISO-03）。
        user = request.user
        if (
            getattr(user, "is_authenticated", False)
            and coding_session.conversation.created_by_id != user.id
        ):
            return Response(
                {"detail": "CodingSession not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 处理前端传入的分支名覆盖
        branch_name = request.data.get("branch_name") if request.data else None
        if branch_name:
            from chat.branch_service import validate_branch_name

            # 排除自己：用户保留默认 branch_name 直接提交时，前端传上来的值跟
            # 当前 draft session 已经入库的 branch_name 完全一致 —— 不剔除就会
            # 被识别成"分支名已被活跃的编码会话使用"。
            validation = await validate_branch_name(
                branch_name,
                coding_session.repository_id,
                exclude_session_id=coding_session.id,
            )
            if not validation.valid:
                return Response(
                    {"detail": "; ".join(validation.errors)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            coding_session.branch_name = branch_name
            await coding_session.asave(update_fields=["branch_name", "updated_at"])

        # 处理前端传入的 PR 目标分支（用户在 TechPlanCard 选定，默认 develop）。
        # 落到 CodingSession.target_branch，后续 PR 创建时使用，确保不会误并入 master。
        target_branch = request.data.get("target_branch") if request.data else None
        if target_branch:
            coding_session.target_branch = str(target_branch).strip()
            await coding_session.asave(update_fields=["target_branch", "updated_at"])

        # 2. 状态机校验：draft 首次确认；confirmed 但尚未创建 subagent 的中间态
        #    允许幂等重启 graph，修复 view 已写 confirmed、后台任务未跑到 dispatch 的卡住状态。
        should_start_graph = False
        if coding_session.status == CodingSession.Status.DRAFT:
            await coding_session.aconfirm()
            should_start_graph = True
        elif coding_session.status == CodingSession.Status.CONFIRMED:
            if coding_session.subagent_session_id is None:
                should_start_graph = True
                logger.warning(
                    "coding_session_confirm_recovering_stuck_confirmed",
                    coding_session_id=str(coding_session.id),
                )
            else:
                serializer = CodingSessionSerializer(coding_session)
                return Response(serializer.data)
        else:
            return Response(
                {"detail": "只有 draft 状态可确认"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3. Runner 在线前置探测 — 不在线则回滚到 draft 并返回 503，
        # graph 后台任务不能被创建（避免误启 graph 后 dispatch 节点抛 RuntimeError）。
        if not await check_runner_online():
            coding_session.status = CodingSession.Status.DRAFT
            await coding_session.asave(update_fields=["status", "updated_at"])
            return Response(
                {"detail": "没有可用的 Runner"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if not should_start_graph:
            serializer = CodingSessionSerializer(coding_session)
            return Response(serializer.data)

        # 4. 启动 coding_graph 后台任务（与 commit/pr confirm 路径一致的 thread_id 格式）
        checkpointer = await get_checkpointer()
        graph = build_coding_graph().compile(checkpointer=checkpointer)
        thread_id = f"coding-{coding_session.id}"
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        initial_state: dict[str, Any] = {
            "coding_session_id": str(coding_session.id),
        }

        try:
            # 直接推进到首个 interrupt（wait_coding_complete）。这一步只负责创建
            # SubAgentSession 并 dispatch 给 Runner，不能依赖易丢失的后台 task。
            await graph.ainvoke(initial_state, config=config)
            await coding_session.arefresh_from_db()
        except Exception as exc:
            logger.exception(
                "coding_graph_initial_dispatch_failed",
                coding_session_id=str(coding_session.id),
                thread_id=thread_id,
                error=str(exc),
            )
            await coding_session.arefresh_from_db()
            if coding_session.status not in (
                CodingSession.Status.FAILED,
                CodingSession.Status.COMPLETED,
            ):
                await coding_session.amark_failed(error=str(exc)[:500])
            return Response(
                {"detail": f"启动编码失败: {str(exc)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        logger.info(
            "coding_session_confirmed",
            coding_session_id=str(coding_session.id),
            thread_id=thread_id,
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

    async def get(self, request, session_id):  # type: ignore[override]
        """返回 AI 建议的 commit message 和影响文件列表。"""
        from .models import CodingSession

        try:
            coding_session = await CodingSession.objects.select_related(
                "conversation"
            ).aget(id=session_id)
        except CodingSession.DoesNotExist:
            return Response(
                {"detail": "CodingSession not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # owner gate（ISO-04）：经 session.conversation 反查 owner，越权 → 404。
        user = request.user
        if (
            getattr(user, "is_authenticated", False)
            and coding_session.conversation.created_by_id != user.id
        ):
            return Response(
                {"detail": "CodingSession not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # contract: 状态校验 -- 仅 awaiting_confirmation + commit_message 步骤接受
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

    async def post(self, request, session_id):  # type: ignore[override]
        """接受用户编辑后的 commit message 并 resume CodingSession graph。"""
        from .models import CodingSession

        try:
            coding_session = await CodingSession.objects.select_related(
                "conversation"
            ).aget(id=session_id)
        except CodingSession.DoesNotExist:
            return Response(
                {"detail": "CodingSession not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # owner gate（ISO-04）：经 session.conversation 反查 owner，越权 → 404。
        user = request.user
        if (
            getattr(user, "is_authenticated", False)
            and coding_session.conversation.created_by_id != user.id
        ):
            return Response(
                {"detail": "CodingSession not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # contract: 状态校验
        if not (
            coding_session.status == CodingSession.Status.AWAITING_CONFIRMATION
            and coding_session.confirmation_step == "commit_message"
        ):
            return Response(
                {"detail": "当前状态不支持此操作"},
                status=status.HTTP_409_CONFLICT,
            )

        commit_message = request.data.get("commit_message", "").strip()
        if not commit_message:
            return Response(
                {"detail": "commit message 不能为空"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 长度限制 (ASVS V5 Input Validation, security mitigation)
        if len(commit_message) > 5000:
            return Response(
                {"detail": "commit message 超过最大长度限制"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Resume CodingSession graph
        from langgraph.types import Command

        from orchestration.checkpointer import get_checkpointer
        from orchestration.coding_graph import build_coding_graph

        checkpointer = await get_checkpointer()
        graph = build_coding_graph().compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": f"coding-{coding_session.id}"}}

        await graph.ainvoke(Command(resume=commit_message), config=config)

        await coding_session.arefresh_from_db()
        serializer = CodingSessionSerializer(coding_session)
        return Response(serializer.data)


class PRConfirmView(APIView):
    """GET/POST /api/chat/coding-sessions/{id}/pr-confirm/

    GET: 返回 AI 建议的 PR 标题、描述、默认 target_branch、branch_url
    POST: 接受用户编辑后的 PR 信息或跳过，resume CodingSession graph
    """

    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [IsAuthenticated]

    async def get(self, request, session_id):  # type: ignore[override]
        from .models import CodingSession

        try:
            coding_session = await CodingSession.objects.select_related(
                "repository", "conversation",
            ).aget(id=session_id)
        except CodingSession.DoesNotExist:
            return Response(
                {"detail": "CodingSession not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # owner gate（ISO-04）：经 session.conversation 反查 owner，越权 → 404。
        user = request.user
        if (
            getattr(user, "is_authenticated", False)
            and coding_session.conversation.created_by_id != user.id
        ):
            return Response(
                {"detail": "CodingSession not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # contract: 状态校验 -- 仅 awaiting_confirmation + pr_review
        if not (
            coding_session.status == CodingSession.Status.AWAITING_CONFIRMATION
            and coding_session.confirmation_step == "pr_review"
        ):
            return Response(
                {"detail": "当前状态不支持此操作"},
                status=status.HTTP_409_CONFLICT,
            )

        # contract: 构建 branch_url
        from orchestration.coding_graph import _resolve_target_branch, build_branch_url

        branch_url = build_branch_url(
            coding_session.repository.git_url,
            coding_session.repository.git_platform,
            coding_session.branch_name,
        )

        return Response({
            "suggested_pr_title": coding_session.suggested_pr_title,
            "suggested_pr_description": coding_session.suggested_pr_description,
            "target_branch": _resolve_target_branch(coding_session),
            "branch_url": branch_url,
        })

    async def post(self, request, session_id):  # type: ignore[override]
        from .models import CodingSession

        try:
            coding_session = await CodingSession.objects.select_related(
                "conversation"
            ).aget(id=session_id)
        except CodingSession.DoesNotExist:
            return Response(
                {"detail": "CodingSession not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # owner gate（ISO-04）：经 session.conversation 反查 owner，越权 → 404。
        user = request.user
        if (
            getattr(user, "is_authenticated", False)
            and coding_session.conversation.created_by_id != user.id
        ):
            return Response(
                {"detail": "CodingSession not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # contract: 状态校验
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
            # contract: 跳过 PR 创建
            from langgraph.types import Command

            from orchestration.checkpointer import get_checkpointer
            from orchestration.coding_graph import build_coding_graph

            checkpointer = await get_checkpointer()
            graph = build_coding_graph().compile(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": f"coding-{coding_session.id}"}}

            await graph.ainvoke(
                Command(resume={"skip_pr": True}),
                config=config,
            )

            await coding_session.arefresh_from_db()
            serializer = CodingSessionSerializer(coding_session)
            return Response(serializer.data)

        # contract: 非 skip 时校验字段
        title = request.data.get("title", "").strip()
        description = request.data.get("description", "").strip()
        target_branch = request.data.get("target_branch", "").strip()

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

        checkpointer = await get_checkpointer()
        graph = build_coding_graph().compile(checkpointer=checkpointer)
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

        await coding_session.arefresh_from_db()
        serializer = CodingSessionSerializer(coding_session)
        return Response(serializer.data)


class ConflictCheckView(APIView):
    """GET /api/chat/coding-sessions/{id}/conflict-check/

    返回冲突预检结果（per contract），供页面刷新恢复场景和前端主动查询。
    """

    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [IsAuthenticated]

    async def get(self, request, session_id):  # type: ignore[override]
        from .models import CodingSession

        try:
            coding_session = await CodingSession.objects.select_related(
                "conversation"
            ).aget(id=session_id)
        except CodingSession.DoesNotExist:
            return Response(
                {"detail": "CodingSession not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # owner gate（ISO-04）：经 session.conversation 反查 owner，越权 → 404。
        user = request.user
        if (
            getattr(user, "is_authenticated", False)
            and coding_session.conversation.created_by_id != user.id
        ):
            return Response(
                {"detail": "CodingSession not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(coding_session.conflict_check_result or {})


class DiffSummaryView(APIView):
    """GET /api/chat/coding-sessions/{id}/diff-summary/

    返回相对 base 的 diff 摘要（per contract）。
    文件级截断 + truncated 布尔标记，默认最多 50 文件（per contract）。
    """

    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [IsAuthenticated]

    async def get(self, request, session_id):  # type: ignore[override]
        from .models import CodingSession

        try:
            coding_session = await CodingSession.objects.select_related(
                "conversation"
            ).aget(id=session_id)
        except CodingSession.DoesNotExist:
            return Response(
                {"detail": "CodingSession not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # owner gate（ISO-04）：经 session.conversation 反查 owner，越权 → 404。
        user = request.user
        if (
            getattr(user, "is_authenticated", False)
            and coding_session.conversation.created_by_id != user.id
        ):
            return Response(
                {"detail": "CodingSession not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(coding_session.diff_summary or {})


class CodingSessionListView(APIView):
    """GET /api/chat/coding-sessions/ -- 按 conversation 查询 CodingSession 列表（work item 恢复用）。"""

    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [IsAuthenticated]

    async def get(self, request):  # type: ignore[override]
        """按 conversation_id 查询 CodingSession 列表。"""
        from .models import CodingSession

        conversation_id = request.query_params.get("conversation_id")
        if not conversation_id:
            return Response(
                {"detail": "conversation_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # owner-scoped 存在性校验（ISO-02/04）：越权或不存在统一返回 []，
        # 不列他人会话下的 coding-session（保持既有「missing 返回 []」语义）。
        try:
            await ConversationService.aget_for_user(conversation_id, request.user)
        except Conversation.DoesNotExist:
            return Response([], status=status.HTTP_200_OK)

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

    async def get(self, request, session_id):  # type: ignore[override]
        """返回 CodingSession 详情。"""
        from .models import CodingSession

        try:
            session = await CodingSession.objects.select_related(
                "conversation"
            ).aget(id=session_id)
        except CodingSession.DoesNotExist:
            return Response(
                {"detail": "CodingSession not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # owner gate（ISO-04）：经 session.conversation 反查 owner，置于序列化之前，
        # 越权 → 404；用 created_by_id 避免 async 惰性 FK；无 superuser bypass。
        user = request.user
        if (
            getattr(user, "is_authenticated", False)
            and session.conversation.created_by_id != user.id
        ):
            return Response(
                {"detail": "CodingSession not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CodingSessionSerializer(session)
        return Response(serializer.data)


class CodingPlanListView(APIView):
    """GET /api/chat/coding-plans/?conversation_id=<uuid>

    按 conversation 查询 CodingPlan 列表。
    """

    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [IsAuthenticated]

    async def get(self, request):  # type: ignore[override]
        from .models import CodingPlan

        conversation_id = request.query_params.get("conversation_id")
        if not conversation_id:
            return Response(
                {"detail": "conversation_id query parameter is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # owner-scoped 存在性校验（ISO-02/04）：越权或不存在统一返回 []，
        # 不列他人会话下的 coding-plan（保持既有「missing 返回 []」语义）。
        try:
            await ConversationService.aget_for_user(conversation_id, request.user)
        except Conversation.DoesNotExist:
            return Response([], status=status.HTTP_200_OK)
        plans = [
            plan
            async for plan in CodingPlan.objects.filter(
                conversation_id=conversation_id
            ).order_by("-created_at")
        ]
        serializer = CodingPlanSerializer(plans, many=True)
        return Response(serializer.data)


class CodingPlanDetailView(APIView):
    """GET /api/chat/coding-plans/<uuid>/

    CodingPlan 详情。
    """

    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [IsAuthenticated]

    async def get(self, request, plan_id):  # type: ignore[override]
        from .models import CodingPlan

        try:
            plan = await CodingPlan.objects.select_related(
                "conversation"
            ).aget(id=plan_id)
        except CodingPlan.DoesNotExist:
            return Response(
                {"detail": "CodingPlan not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # owner gate（ISO-04）：经 plan.conversation 反查 owner，置于序列化之前，
        # 越权 → 404；用 created_by_id 避免 async 惰性 FK；无 superuser bypass。
        user = request.user
        if (
            getattr(user, "is_authenticated", False)
            and plan.conversation.created_by_id != user.id
        ):
            return Response(
                {"detail": "CodingPlan not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CodingPlanSerializer(plan)
        return Response(serializer.data)


class CodingPlanSessionsBatchCreateView(APIView):
    """POST /api/chat/coding-plans/{plan_id}/sessions/ -- work item 批量创建 CodingSession。

    在已有 CodingPlan 上为 N 个 repository 批量创建 DRAFT CodingSession。
    每个 repository 独立校验 + 独立事务，部分失败不阻塞其他 repository（CONTEXT
    §批量创建 endpoint 语义）。
    """

    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="批量创建 CodingSession（work item）",
        request=CodingSessionsBatchCreateRequestSerializer,
        responses={
            200: CodingSessionsBatchCreateResponseSerializer,
            400: {"description": "请求体校验失败"},
            403: {"description": "无权访问该 CodingPlan 所属项目"},
            404: {"description": "CodingPlan 不存在"},
        },
        tags=["CodingPlan"],
    )
    async def post(self, request, plan_id):  # type: ignore[override]
        from chat.coding_session_service import create_sessions_for_plan
        from permissions.models import ProjectRole
        from permissions.services import PermissionService

        from .models import CodingPlan

        # 1) 反序列化请求体
        req_ser = CodingSessionsBatchCreateRequestSerializer(data=request.data)
        req_ser.is_valid(raise_exception=True)

        # 2) CodingPlan 存在性
        try:
            plan = await CodingPlan.objects.select_related(
                "conversation", "conversation__project"
            ).aget(id=plan_id)
        except CodingPlan.DoesNotExist:
            return Response(
                {"detail": "CodingPlan 不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 3) owner gate（ISO-04，主/外层）：经 plan.conversation 反查 owner，置于既有
        #    has_project_access 之前 —— owner-miss 必须先 404（不是 403，不泄漏存在性）。
        #    用 created_by_id 避免 async 惰性 FK；无 superuser bypass（ISO-03）。
        user = request.user
        if (
            getattr(user, "is_authenticated", False)
            and plan.conversation.created_by_id != user.id
        ):
            return Response(
                {"detail": "CodingPlan 不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 4) 项目级 ownership（MEMBER+）—— 保留为 null-owner/共享行次层防御
        # 已确认的 owner 已由上方 owner gate 授权，不再叠加 project 403。
        is_owner = (
            getattr(user, "is_authenticated", False)
            and plan.conversation.created_by_id == user.id
        )
        if not getattr(user, "is_superuser", False) and not is_owner:
            allowed = await sync_to_async(PermissionService.has_project_access)(
                user=user,
                project=plan.conversation.project,
                min_role=ProjectRole.MEMBER,
            )
            if not allowed:
                return Response(
                    {"detail": "无权访问该 CodingPlan 所属项目"},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # 5) 业务调用
        result = await create_sessions_for_plan(
            plan=plan,
            repository_ids=req_ser.validated_data["repository_ids"],
            branch_template=req_ser.validated_data.get("branch_template", ""),
            target_branch=req_ser.validated_data.get("target_branch", ""),
        )

        # 6) dataclass -> dict -> serializer
        resp_payload: dict[str, Any] = {
            "created": [
                {
                    "session_id": str(i.session_id),
                    "repository_id": str(i.repository_id),
                    "branch_name": i.branch_name,
                }
                for i in result.created
            ],
            "failed": [
                {"repository_id": str(i.repository_id), "error": i.error}
                for i in result.failed
            ],
        }
        resp_ser = CodingSessionsBatchCreateResponseSerializer(data=resp_payload)
        resp_ser.is_valid(raise_exception=True)
        return Response(resp_ser.data, status=status.HTTP_200_OK)


# ============================================================================
# 路由决策手动微调 endpoint
# ============================================================================


class RoutingTraceManualOverrideView(APIView):
    """POST /api/chat/routing-traces/<uuid:trace_id>/override/

    用户在 RoutingDecisionPanel 改勾选 → 写一行新
    ``RepositoryRoutingTrace(triggered_by=MANUAL_OVERRIDE)`` —— 保留原 trace
    不变，evaluation SQL 可对比 AI 决策 vs 用户最终决策。

    body schema: ``{"candidates": [{"repository_id": uuid, "selected": bool}, ...]}``

    安全约束：serializer 只接受 ``{repository_id, selected}`` 两字段，
    ``score`` / ``evidence`` / ``level`` / ``selected_by_ai`` 由 Server 继承
    自原 trace —— 前端无权改写。
    """

    permission_classes = [IsAuthenticated]

    async def post(self, request, trace_id):  # type: ignore[override,no-untyped-def]
        from chat.models import RepositoryRoutingTrace

        ser = RoutingTraceManualOverrideSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        requested = {
            str(c["repository_id"]): bool(c["selected"])
            for c in ser.validated_data["candidates"]
        }

        try:
            original = await RepositoryRoutingTrace.objects.select_related(
                "conversation", "conversation__project"
            ).aget(id=trace_id)
        except RepositoryRoutingTrace.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        # owner gate（ISO-03/04，主/外层）：经 trace.conversation 反查 owner，越权 → 404
        # 隐藏存在性。**无 superuser bypass**（管理员作为认证用户操作他人会话 → 404）；
        # 用 created_by_id 避免 async 惰性 FK。
        from permissions.services import PermissionService

        user = request.user
        if (
            getattr(user, "is_authenticated", False)
            and original.conversation.created_by_id != user.id
        ):
            logger.warning(
                "routing_trace_manual_override_denied_cross_user",
                user_id=str(getattr(user, "id", "")),
                trace_id=str(original.id),
            )
            return Response(status=status.HTTP_404_NOT_FOUND)

        # 既有 project 级 has_project_access 保留为 null-owner/共享行次层防御
        # （不 bypass 上面的 owner gate；保留 superuser→project 语义仅作用于无主行）。
        if not getattr(user, "is_superuser", False):
            allowed = await sync_to_async(PermissionService.has_project_access)(
                user, original.conversation.project, "member"
            )
            if not allowed:
                logger.warning(
                    "routing_trace_manual_override_denied_cross_project",
                    user_id=str(getattr(user, "id", "")),
                    trace_id=str(original.id),
                )
                return Response(status=status.HTTP_404_NOT_FOUND)

        # 继承原 candidates，仅更新 selected_by_user_final
        new_candidates: list[dict[str, Any]] = []
        for c in (original.candidates or []):
            c2 = dict(c)
            rid = str(c2.get("repository_id", ""))
            if rid in requested:
                c2["selected_by_user_final"] = requested[rid]
            new_candidates.append(c2)

        new_trace = await RepositoryRoutingTrace.objects.acreate(
            agent_session=None,
            conversation_id=original.conversation_id,
            query=original.query,
            candidates=new_candidates,
            threshold=original.threshold,
            triggered_by=RepositoryRoutingTrace.TriggeredBy.MANUAL_OVERRIDE,
        )

        logger.info(
            "routing_trace_manual_override_created",
            original_trace_id=str(original.id),
            new_trace_id=str(new_trace.id),
            conversation_id=str(original.conversation_id),
            updated_count=sum(
                1 for c in new_candidates if str(c.get("repository_id", "")) in requested
            ),
        )

        return Response(
            {
                "trace_id": str(new_trace.id),
                "original_trace_id": str(original.id),
                "candidates": new_candidates,
                "triggered_by": new_trace.triggered_by,
            },
            status=status.HTTP_201_CREATED,
        )


# ============================================================================
# implementation / work item / 协商答复 endpoint
# ============================================================================


class ClarificationAnswerView(APIView):
    """POST /api/chat/clarifications/<str:clarification_id>/answer/

    用户对 ``ask_clarification`` 卡片提交答复后调用本 endpoint。endpoint 完成：

    1. 校验 trace 归属（跨用户访问返 404 隐藏存在性）；
    2. 落 ``ConversationIntentTrace``（work item 写入点）—— ``answered_at`` /
       ``selected_option_id`` / ``freeform_answer`` / ``inferred_state`` 一次性
       update；
    3. 把用户答复作为新的 ``Message(role=user)`` 落库，``metadata`` 携带
       ``clarification_id`` / ``selected_option_id`` / ``kind=clarification_answer``；
    4. 后台 ``graph.ainvoke(Command(resume=...))`` 唤醒 chat_graph 让 LLM 看到
       用户答复继续推理（前端通过现有 runtime polling / SSE 拿后续输出）。

    设计约束（与 ``CodingSessionConfirmView`` 一致）：

    - 同一对话的并发 answer 通过 ``ConversationIntentTrace.clarification_id``
      unique 索引 + ``answered_at`` 判断幂等：已答 → 409 + 返回原答复。
    - resume 后台 task 走 ``_BACKGROUND_TASKS`` 强引用，防止 asyncio GC 中止。
    """

    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [IsAuthenticated]

    async def post(self, request, clarification_id):  # type: ignore[override,no-untyped-def]
        from chat.models import ConversationIntentTrace, Message

        ser = ClarificationAnswerSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        selected_id = (data.get("selected_option_id") or "").strip()
        freeform = (data.get("freeform_text") or "").strip()

        try:
            trace = await ConversationIntentTrace.objects.select_related(
                "conversation", "conversation__project",
            ).aget(clarification_id=clarification_id)
        except ConversationIntentTrace.DoesNotExist:
            return Response(
                {"detail": "clarification 不存在或已过期"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # owner gate（ISO-03/04，主/外层）：经 trace.conversation 反查 owner，越权 → 404
        # （404 body 与「不存在或已过期」一致，隐藏存在性）；owner-miss 必须在落库/resume
        # 之前 404。**无 superuser bypass**（管理员操作他人会话 → 404）；
        # 用 created_by_id 避免 async 惰性 FK。
        user = request.user
        if (
            getattr(user, "is_authenticated", False)
            and trace.conversation.created_by_id != user.id
        ):
            logger.warning(
                "clarification_answer_denied_cross_user",
                user_id=str(getattr(user, "id", "")),
                clarification_id=clarification_id,
            )
            return Response(
                {"detail": "clarification 不存在或已过期"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 既有 project 级 has_project_access 保留为 null-owner/共享行次层防御
        # （不 bypass 上面的 owner gate）。
        if not getattr(user, "is_superuser", False):
            from permissions.services import PermissionService

            allowed = await sync_to_async(PermissionService.has_project_access)(
                user, trace.conversation.project, "member",
            )
            if not allowed:
                logger.warning(
                    "clarification_answer_denied_cross_project",
                    user_id=str(getattr(user, "id", "")),
                    clarification_id=clarification_id,
                )
                return Response(
                    {"detail": "clarification 不存在或已过期"},
                    status=status.HTTP_404_NOT_FOUND,
                )

        # 幂等：已答 → 409 + 返回原答复（防止前端重复提交导致重复 resume）
        if trace.answered_at is not None:
            return Response(
                {
                    "detail": "该 clarification 已被答复",
                    "clarification_id": clarification_id,
                    "selected_option_id": trace.selected_option_id,
                    "freeform_text": trace.freeform_answer,
                    "answered_at": trace.answered_at.isoformat(),
                },
                status=status.HTTP_409_CONFLICT,
            )

        # 提取 selected_option.implies → inferred_state
        implies: dict[str, Any] = {}
        selected_label = ""
        if selected_id:
            for opt in (trace.options or []):
                if not isinstance(opt, dict):
                    continue
                if str(opt.get("id", "")) == selected_id:
                    raw_implies = opt.get("implies") or {}
                    if isinstance(raw_implies, dict):
                        implies = dict(raw_implies)
                    selected_label = str(opt.get("label", "") or "")
                    break

        now = timezone.now()
        await ConversationIntentTrace.objects.filter(pk=trace.pk).aupdate(
            selected_option_id=selected_id,
            freeform_answer=freeform,
            inferred_state=implies,
            answered_at=now,
        )

        # 把用户答复落 Message 表 —— 这条 user message 作为下一轮 LLM 输入由
        # wait_clarification_node 的 user_message 字段覆盖；前端在 hydrate
        # 阶段也能看到这条「我选了 X」的对话气泡。
        reply_content = freeform or selected_label or "（已确认）"
        await Message.objects.acreate(
            conversation=trace.conversation,
            role=Message.Role.USER,
            content=reply_content,
            metadata={
                "kind": "clarification_answer",
                "clarification_id": clarification_id,
                "selected_option_id": selected_id,
            },
        )

        # 后台 resume graph：与 CodingSessionConfirmView 同模式（asyncio 后台
        # task + _BACKGROUND_TASKS 强引用），endpoint 不阻塞 SSE 等待。
        # resume 全流程（重建 graph config + finalize 落库）收敛在
        # ConversationService.resume_clarification_run —— 裸 thread_id config
        # 会让 executing_node 拿不到 api_key 静默失败（详见该方法 docstring）。
        thread_id = str(trace.conversation_id)
        resume_payload = {
            "clarification_id": clarification_id,
            "selected_option_id": selected_id or None,
            "selected_option_label": selected_label or None,
            "freeform_text": freeform or None,
            "implies": implies,
        }

        async def _resume_graph() -> None:
            try:
                await ConversationService.resume_clarification_run(
                    thread_id, resume_payload,
                )
            except Exception:
                logger.exception(
                    "clarification_answer_resume_failed",
                    clarification_id=clarification_id,
                    thread_id=thread_id,
                )

        # 必须用干净的 contextvars 上下文启动：默认 create_task 会复制当前请求的
        # contextvars，其中含 asgiref 的 CurrentThreadExecutor；请求结束后该
        # executor 退出，后台任务里的 sync_to_async（async ORM 内部）再向它提交
        # 工作会抛 "CurrentThreadExecutor already quit or is broken"，导致 run
        # 永久卡在 waiting_clarification。
        task = asyncio.create_task(_resume_graph(), context=contextvars.Context())
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)

        logger.info(
            "clarification_answer_recorded",
            clarification_id=clarification_id,
            conversation_id=thread_id,
            selected_option_id=selected_id,
            has_freeform=bool(freeform),
            implies_keys=sorted(implies.keys()),
        )

        return Response(
            {
                "clarification_id": clarification_id,
                "selected_option_id": selected_id,
                "freeform_text": freeform,
                "answered_at": now.isoformat(),
                "inferred_state": implies,
            },
            status=status.HTTP_200_OK,
        )


# 用户主动跳过澄清时注入给 LLM 的指令文本：作为 resume 后的 user turn，
# 让模型不再追问、直接基于已检索/分析到的内容给出最佳回答。
_CLARIFICATION_SKIP_INSTRUCTION = (
    "用户选择跳过这个澄清问题，不再补充信息。"
    "请不要再追问，直接基于目前已经检索和分析到的内容，给出你能给出的最佳回答；"
    "如有不确定之处，可在回答中说明假设。"
)


class ClarificationSkipView(APIView):
    """POST /api/chat/conversations/<uuid:conversation_id>/clarification/skip/

    用户在「等待澄清」态下选择跳过的兜底出口。典型场景：编排层自动构造的
    clarification 漏发卡片 payload（如深度分析子代理发起的追问），导致 run
    永久卡在 ``waiting_clarification`` 而前端无卡可答、既不能结束也无法选择。

    本 endpoint 不依赖前端持有 ``clarification_id`` —— 按 conversation 维度
    定位等待中的 run，完成：

    1. owner gate 校验会话归属（越权/不存在统一 404）；
    2. 找到该会话最近一条未答复的 ``ConversationIntentTrace``（若有）标记为
       已跳过（落审计 + 幂等）；
    3. 落一条 ``Message(role=user)`` 作为「已跳过追问」的可见气泡；
    4. 后台 ``resume_clarification_run`` 唤醒 graph —— 注入跳过指令作为新的
       user turn，让 LLM 基于现有信息直接作答。

    设计与 ``ClarificationAnswerView`` 对齐：resume 后台 task 走
    ``_BACKGROUND_TASKS`` 强引用 + 干净 contextvars，防 asyncio GC 中止 /
    ``CurrentThreadExecutor already quit``。
    """

    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [IsAuthenticated]

    async def post(self, request, conversation_id):  # type: ignore[override,no-untyped-def]
        from chat.models import ConversationIntentTrace, Message
        from orchestration.models import OrchestrationRun

        # owner gate（ISO-04）：owner-scoped 存在性校验，越权/不存在统一 404。
        try:
            conversation = await ConversationService.aget_for_user(
                str(conversation_id), request.user
            )
        except Conversation.DoesNotExist:
            return Response(
                {"detail": "对话不存在"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 仅当确有等待澄清的 run 时才执行跳过；否则幂等返回，避免误触把一个
        # 正常会话强行 resume。
        #
        # status 同时匹配 WAITING 与 RUNNING：正常路径会把 run 落成 WAITING；
        # 但 dispatch 的后台 finalizer 若被中途打断（如 dev reload / SSE 异常
        # 断开后台任务被回收），run 会停在 ``status=running, phase=waiting_clarification``
        # 且无 ConversationIntentTrace —— 这正是「无卡可答、永久等待」的孤儿态，
        # 跳过出口必须能覆盖它。
        waiting_run = await OrchestrationRun.objects.filter(
            conversation=conversation,
            status__in=[
                OrchestrationRun.Status.WAITING,
                OrchestrationRun.Status.RUNNING,
            ],
            phase=OrchestrationRun.Phase.WAITING_CLARIFICATION,
        ).order_by("-created_at").afirst()
        if waiting_run is None:
            return Response(
                {"status": "no_pending"},
                status=status.HTTP_200_OK,
            )

        # 最近一条未答复 trace（可能不存在：waiting_clarification_without_clarification_id
        # 的退化场景）。有则标记已跳过 + 落审计；无则仍可凭 waiting_run 直接 resume。
        trace = await ConversationIntentTrace.objects.filter(
            conversation=conversation,
            answered_at__isnull=True,
        ).order_by("-created_at").afirst()

        now = timezone.now()
        clarification_id = trace.clarification_id if trace else None
        if trace is not None:
            await ConversationIntentTrace.objects.filter(pk=trace.pk).aupdate(
                selected_option_id="",
                freeform_answer=_CLARIFICATION_SKIP_INSTRUCTION,
                inferred_state={},
                answered_at=now,
            )

        await Message.objects.acreate(
            conversation=conversation,
            role=Message.Role.USER,
            content="（已跳过追问，请基于现有信息继续回答）",
            metadata={
                "kind": "clarification_skip",
                "clarification_id": clarification_id or "",
            },
        )

        thread_id = str(conversation.id)
        resume_payload = {
            "clarification_id": clarification_id,
            "selected_option_id": None,
            "selected_option_label": None,
            "freeform_text": _CLARIFICATION_SKIP_INSTRUCTION,
            "implies": {},
            "skipped": True,
        }

        async def _resume_graph() -> None:
            try:
                await ConversationService.resume_clarification_run(
                    thread_id, resume_payload,
                )
            except Exception:
                logger.exception(
                    "clarification_skip_resume_failed",
                    clarification_id=clarification_id,
                    thread_id=thread_id,
                )

        # 同 ClarificationAnswerView：干净 contextvars 上下文启动，防请求结束后
        # 后台任务向已退出的 CurrentThreadExecutor 提交工作而抛错。
        task = asyncio.create_task(_resume_graph(), context=contextvars.Context())
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)

        logger.info(
            "clarification_skip_recorded",
            clarification_id=clarification_id,
            conversation_id=thread_id,
        )

        return Response(
            {
                "status": "skipped",
                "clarification_id": clarification_id,
                "answered_at": now.isoformat(),
            },
            status=status.HTTP_200_OK,
        )
