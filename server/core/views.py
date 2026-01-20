"""Core views: Authentication and Settings."""
from django.conf import settings
from services.crypto import encrypt_value
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from .models import SettingKeys, SystemSetting
from .serializers import (
 ChangePasswordSerializer,
 LoginResponseSerializer,
 LoginSerializer,
 SystemSettingCreateSerializer,
 SystemSettingSerializer,
 SystemSettingUpdateSerializer,
 TokenResponseSerializer,
 UserSerializer,
)
# ============ Authentication Views ============
class LoginView(APIView):
 """User login endpoint."""
 permission_classes = [AllowAny]
 def post(self, request):
 serializer = LoginSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 user = serializer.validated_data["user"]
 # Generate tokens
 refresh = RefreshToken.for_user(user)
 # Set custom claim to match FastAPI format
 refresh["sub"] = str(user.id)
 access_token = str(refresh.access_token)
 response = Response(
 LoginResponseSerializer(
 {
 "access_token": access_token,
 "user": user,
 }
 ).data
 )
 # Set refresh token cookie
 response.set_cookie(
 key="refresh_token",
 value=str(refresh),
 httponly=settings.COOKIE_HTTPONLY,
 samesite=settings.COOKIE_SAMESITE,
 secure=settings.COOKIE_SECURE,
 max_age=7 * 24 * 60 * 60, # 7 days
 )
 return response
class LogoutView(APIView):
 """User logout endpoint."""
 permission_classes = [AllowAny]
 def post(self, request):
 response = Response({"message": "登出成功"})
 response.delete_cookie("refresh_token")
 return response
class RefreshTokenView(APIView):
 """Refresh access token endpoint."""
 permission_classes = [AllowAny]
 def post(self, request):
 refresh_token = request.COOKIES.get("refresh_token")
 if not refresh_token:
 return Response(
 {"detail": "Refresh Token 无效或已过期"},
 status=status.HTTP_401_UNAUTHORIZED,
 )
 try:
 refresh = RefreshToken(refresh_token)
 access_token = str(refresh.access_token)
 # Create new refresh token (rolling refresh)
 new_refresh = (
 RefreshToken.for_user(request.user) if request.user.is_authenticated else refresh
 )
 new_refresh["sub"] = refresh.get("sub")
 response = Response(TokenResponseSerializer({"access_token": access_token}).data)
 response.set_cookie(
 key="refresh_token",
 value=str(new_refresh),
 httponly=settings.COOKIE_HTTPONLY,
 samesite=settings.COOKIE_SAMESITE,
 secure=settings.COOKIE_SECURE,
 max_age=7 * 24 * 60 * 60,
 )
 return response
 except Exception:
 response = Response(
 {"detail": "Refresh Token 无效或已过期"},
 status=status.HTTP_401_UNAUTHORIZED,
 )
 response.delete_cookie("refresh_token")
 return response
class MeView(APIView):
 """Get current user info endpoint."""
 def get(self, request):
 return Response(UserSerializer(request.user).data)
class ChangePasswordView(APIView):
 """Change password endpoint."""
 def post(self, request):
 serializer = ChangePasswordSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 if not request.user.check_password(serializer.validated_data["old_password"]):
 return Response(
 {"detail": "旧密码错误"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 request.user.set_password(serializer.validated_data["new_password"])
 request.user.save
 return Response({"message": "密码修改成功"})
# ============ Settings Views ============
ENCRYPTED_KEYS = {SettingKeys.ANTHROPIC_API_KEY}
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
# ============ Health Check ============
class HealthCheckView(APIView):
 """Health check endpoint."""
 permission_classes = [AllowAny]
 def get(self, request):
 return Response({"status": "ok", "service": "friday"})
