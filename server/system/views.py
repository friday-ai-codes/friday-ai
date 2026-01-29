"""Settings views."""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from common.encryption import encrypt_value
from .models import SettingKeys, SystemSetting
from .serializers import (
 SystemSettingCreateSerializer,
 SystemSettingSerializer,
 SystemSettingUpdateSerializer,
)
ENCRYPTED_KEYS = {SettingKeys.ANTHROPIC_API_KEY, SettingKeys.QDRANT_API_KEY}
class SettingsListCreateView(APIView):
 """List and create system settings."""
 def get(self, request):
 settings_qs = SystemSetting.objects.all
 serializer = SystemSettingSerializer(settings_qs, many=True)
 return Response(serializer.data)
 def post(self, request):
 serializer = SystemSettingCreateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 key = serializer.validated_data["key"]
 # Check if already exists
 if SystemSetting.objects.filter(key=key).exists:
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
 setting = SystemSetting.objects.create(
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
 def get(self, request, key):
 try:
 setting = SystemSetting.objects.get(key=key)
 except SystemSetting.DoesNotExist:
 return Response(
 {"detail": f"设置 '{key}' 未找到"},
 status=status.HTTP_404_NOT_FOUND,
 )
 return Response(SystemSettingSerializer(setting).data)
 def put(self, request, key):
 serializer = SystemSettingUpdateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 setting, created = SystemSetting.objects.get_or_create(key=key)
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
 setting.save
 return Response(SystemSettingSerializer(setting).data)
 def delete(self, request, key):
 try:
 setting = SystemSetting.objects.get(key=key)
 except SystemSetting.DoesNotExist:
 return Response(
 {"detail": f"设置 '{key}' 未找到"},
 status=status.HTTP_404_NOT_FOUND,
 )
 setting.delete
 return Response(status=status.HTTP_204_NO_CONTENT)
