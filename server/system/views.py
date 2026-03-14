"""Settings views."""
from asgiref.sync import sync_to_async
from rest_framework import status
from rest_framework.response import Response
from adrf.views import APIView
from common.encryption import encrypt_value
from permissions.api_permissions import IsSuperUser
from .models import SettingKeys, SystemSetting
from .serializers import (
 SystemSettingCreateSerializer,
 SystemSettingSerializer,
 SystemSettingUpdateSerializer,
)
ENCRYPTED_KEYS = {
 SettingKeys.ANTHROPIC_API_KEY,
 SettingKeys.QDRANT_API_KEY,
 SettingKeys.EMBEDDING_API_KEY,
 SettingKeys.RERANKER_API_KEY,
 SettingKeys.FEISHU_APP_SECRET,
}
class SettingsListCreateView(APIView):
 """List and create system settings."""
 permission_classes = [IsSuperUser]
 async def get(self, request):
 settings = [s async for s in SystemSetting.objects.all]
 serializer = SystemSettingSerializer(settings, many=True)
 return Response(serializer.data)
 async def post(self, request):
 serializer = SystemSettingCreateSerializer(data=request.data)
 await sync_to_async(serializer.is_valid)(raise_exception=True)
 key = serializer.validated_data["key"]
 # Check if already exists
 if await SystemSetting.objects.filter(key=key).aexists:
 return Response(
 {"detail": f"设置 '{key}' 已存在"},
 status=status.HTTP_409_CONFLICT,
 )
 # Determine if should encrypt
 should_encrypt = serializer.validated_data.get("is_encrypted", False)
 if not should_encrypt:
 should_encrypt = key in ENCRYPTED_KEYS
 value = serializer.validated_data.get("value")
 if should_encrypt and value:
 value = encrypt_value(value)
 setting = await SystemSetting.objects.acreate(
 key=key,
 value=value,
 is_encrypted=should_encrypt,
 description=serializer.validated_data.get("description"),
 )
 return Response(
 SystemSettingSerializer(setting).data,
 status=status.HTTP_201_CREATED,
 )
class SettingsDetailView(APIView):
 """Get, update, and delete a system setting."""
 permission_classes = [IsSuperUser]
 async def get(self, request, key):
 try:
 setting = await SystemSetting.objects.aget(key=key)
 except SystemSetting.DoesNotExist:
 return Response(
 {"detail": f"设置 '{key}' 未找到"},
 status=status.HTTP_404_NOT_FOUND,
 )
 return Response(SystemSettingSerializer(setting).data)
 async def put(self, request, key):
 serializer = SystemSettingUpdateSerializer(data=request.data)
 await sync_to_async(serializer.is_valid)(raise_exception=True)
 setting, created = await SystemSetting.objects.aget_or_create(key=key)
 # Determine if should encrypt
 should_encrypt = serializer.validated_data.get("is_encrypted")
 if should_encrypt is None:
 should_encrypt = key in ENCRYPTED_KEYS
 value = serializer.validated_data.get("value")
 if should_encrypt and value:
 value = encrypt_value(value)
 setting.value = value
 setting.is_encrypted = should_encrypt
 if "description" in serializer.validated_data:
 setting.description = serializer.validated_data["description"]
 await setting.asave
 return Response(SystemSettingSerializer(setting).data)
 async def delete(self, request, key):
 try:
 setting = await SystemSetting.objects.aget(key=key)
 except SystemSetting.DoesNotExist:
 return Response(
 {"detail": f"设置 '{key}' 未找到"},
 status=status.HTTP_404_NOT_FOUND,
 )
 await setting.adelete
 return Response(status=status.HTTP_204_NO_CONTENT)
class FeishuIMTestView(APIView):
 """Test Feishu IM configuration by sending a test message."""
 permission_classes = [IsSuperUser]
 async def post(self, request):
 from common.encryption import decrypt_value
 receive_id = request.data.get("receive_id") or request.data.get("user_id")
 receive_id_type = request.data.get("receive_id_type", "open_id")
 message = request.data.get("message", "这是一条测试消息，来自 Friday AI Agent 配置测试。")
 if not receive_id:
 return Response(
 {"success": False, "message": "请提供接收者 ID"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 if receive_id_type not in ("open_id", "chat_id", "user_id"):
 return Response(
 {"success": False, "message": "receive_id_type 必须是 open_id、chat_id 或 user_id"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 获取配置（优先使用请求中的临时配置）
 app_id = request.data.get("app_id")
 app_secret = request.data.get("app_secret")
 # 如果没有临时配置，使用系统设置
 if not app_id:
 try:
 setting = await SystemSetting.objects.aget(key=SettingKeys.FEISHU_APP_ID)
 app_id = setting.value
 except SystemSetting.DoesNotExist:
 pass
 if not app_secret:
 try:
 setting = await SystemSetting.objects.aget(key=SettingKeys.FEISHU_APP_SECRET)
 if setting.value and setting.is_encrypted:
 app_secret = decrypt_value(setting.value)
 else:
 app_secret = setting.value
 except SystemSetting.DoesNotExist:
 pass
 if not app_id or not app_secret:
 return Response(
 {"success": False, "message": "飞书 IM 配置不完整，请填写 App ID 和 App Secret"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 发送测试消息
 try:
 from services.feishu_im import FeishuIMClient
 client = FeishuIMClient(app_id=app_id, app_secret=app_secret)
 result = await client.send_message(
 receive_id=receive_id,
 receive_id_type=receive_id_type,
 msg_type="text",
 content={"text": message},
 )
 message_id = result.get("message_id", "")
 return Response({
 "success": True,
 "message": "测试消息发送成功",
 "message_id": message_id,
 })
 except Exception as e:
 return Response({
 "success": False,
 "message": f"发送失败: {e!s}",
 })
