"""Chat API views."""
import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from adrf.views import APIView
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
 ModelsRequestSerializer,
 ModelsResponseSerializer,
 SendMessageResponseSerializer,
 SendMessageSerializer,
)
from .services import ChatMessage, ChatServiceError, aget_chat_service
from projects.models import Project
logger = structlog.get_logger(__name__)
class ModelsView(APIView):
 """API view for getting available models."""
 permission_classes = [IsAuthenticated]
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
 try:
 result = await ConversationService.send_message(
 conversation_id=str(conversation_id),
 content=content,
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
