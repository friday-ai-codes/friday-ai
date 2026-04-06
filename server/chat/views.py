"""Chat API views."""
import structlog
from adrf.views import APIView
from django.http import StreamingHttpResponse
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
 ConversationDetailSerializer,
 ConversationListSerializer,
 ConversationMessageSerializer,
 ConversationRuntimeSerializer,
 CreateConversationSerializer,
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
