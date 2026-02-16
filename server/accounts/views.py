"""Accounts views: Authentication."""
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import (
 ChangePasswordSerializer,
 LoginResponseSerializer,
 LoginSerializer,
 TokenResponseSerializer,
 UserSerializer,
)
class LoginView(APIView):
 """User login endpoint."""
 permission_classes = [AllowAny]
 def post(self, request):
 serializer = LoginSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 user = serializer.validated_data["user"]
 # Generate tokens
 refresh = RefreshToken.for_user(user)
 # 设置自定义 claim，统一 JWT 中的用户标识字段
 refresh["sub"] = str(user.id)
 access_token = str(refresh.access_token)
 response = Response(
 LoginResponseSerializer(
 {
 "access_token": access_token,
 "user": user,
 "must_change_password": user.must_change_password,
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
 # Clear must_change_password flag after successful password change
 request.user.must_change_password = False
 request.user.save(update_fields=["password", "must_change_password"])
 return Response({"message": "密码修改成功"})
class ForceChangePasswordView(APIView):
 """Force change password endpoint for users with must_change_password flag."""
 def post(self, request):
 from .serializers import ForceChangePasswordSerializer
 serializer = ForceChangePasswordSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 request.user.set_password(serializer.validated_data["new_password"])
 request.user.must_change_password = False
 request.user.save(update_fields=["password", "must_change_password"])
 return Response({"message": "密码修改成功，请重新登录"})
class AdminProfileView(APIView):
 """Admin profile management endpoint."""
 def get(self, request):
 if not request.user.is_superuser:
 return Response(
 {"detail": "仅超级管理员可访问"},
 status=status.HTTP_403_FORBIDDEN,
 )
 from .serializers import AdminProfileSerializer
 return Response(AdminProfileSerializer(request.user).data)
 def put(self, request):
 if not request.user.is_superuser:
 return Response(
 {"detail": "仅超级管理员可访问"},
 status=status.HTTP_403_FORBIDDEN,
 )
 from .serializers import AdminProfileUpdateSerializer
 serializer = AdminProfileUpdateSerializer(data=request.data, context={"user": request.user})
 serializer.is_valid(raise_exception=True)
 user = request.user
 if "username" in serializer.validated_data:
 user.username = serializer.validated_data["username"]
 if "display_name" in serializer.validated_data:
 user.display_name = serializer.validated_data["display_name"]
 user.save
 from .serializers import AdminProfileSerializer
 return Response(AdminProfileSerializer(user).data)
class AdminChangePasswordView(APIView):
 """Admin change password endpoint."""
 def post(self, request):
 if not request.user.is_superuser:
 return Response(
 {"detail": "仅超级管理员可访问"},
 status=status.HTTP_403_FORBIDDEN,
 )
 serializer = ChangePasswordSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 if not request.user.check_password(serializer.validated_data["old_password"]):
 return Response(
 {"detail": "旧密码错误"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 request.user.set_password(serializer.validated_data["new_password"])
 request.user.must_change_password = False
 request.user.save(update_fields=["password", "must_change_password"])
 return Response({"message": "密码修改成功"})
