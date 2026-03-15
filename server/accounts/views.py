"""Accounts views: Authentication."""
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from adrf.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from .models import Invitation
from .serializers import (
 ChangePasswordSerializer,
 InvitationAcceptSerializer,
 InvitationCreateSerializer,
 InvitationResponseSerializer,
 LoginResponseSerializer,
 LoginSerializer,
 MeSerializer,
 ProfileUpdateSerializer,
 TokenResponseSerializer,
 UserSerializer,
)
User = get_user_model
class LoginView(APIView):
 """User login endpoint."""
 permission_classes = [AllowAny]
 async def post(self, request):
 serializer = LoginSerializer(data=request.data)
 # KEEP: LoginSerializer.is_valid 内部调用 authenticate，涉及 DB 查询
 await sync_to_async(serializer.is_valid)(raise_exception=True)
 user = serializer.validated_data["user"]
 # Generate tokens
 # KEEP: simplejwt RefreshToken.for_user 无 async API
 refresh = await sync_to_async(RefreshToken.for_user)(user)
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
 async def post(self, request):
 response = Response({"message": "登出成功"})
 response.delete_cookie("refresh_token")
 return response
class RefreshTokenView(APIView):
 """Refresh access token endpoint."""
 permission_classes = [AllowAny]
 async def post(self, request):
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
 if request.user.is_authenticated:
 # KEEP: simplejwt RefreshToken.for_user 无 async API
 new_refresh = await sync_to_async(RefreshToken.for_user)(request.user)
 else:
 new_refresh = refresh
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
 async def get(self, request):
 # MeSerializer 内部的 get_project_memberships 需要 DB 查询，用 sync_to_async 包装
 data = await sync_to_async(lambda: MeSerializer(request.user).data)
 return Response(data)
class ProfileUpdateView(APIView):
 """更新当前用户资料（display_name）。"""
 async def patch(self, request):
 serializer = ProfileUpdateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 user = request.user
 user.display_name = serializer.validated_data["display_name"]
 await user.asave(update_fields=["display_name"])
 data = await sync_to_async(lambda: MeSerializer(user).data)
 return Response(data)
class InvitationView(APIView):
 """邀请令牌管理：创建（POST）或校验（GET）。"""
 def get_permissions(self) -> list:
 """按 HTTP method 分派权限：GET 公开（校验令牌），POST 需认证（创建邀请）。"""
 if self.request.method == "GET":
 return [AllowAny]
 return [IsAuthenticated]
 async def post(self, request):
 """创建邀请令牌（仅超级管理员）。"""
 if not request.user.is_superuser:
 return Response({"detail": "仅超级管理员可创建邀请"}, status=status.HTTP_403_FORBIDDEN)
 serializer = InvitationCreateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 invitation = await sync_to_async(Invitation.objects.create)(
 created_by=request.user,
 email=serializer.validated_data.get("email", ""),
 )
 return Response(
 InvitationResponseSerializer(invitation).data,
 status=status.HTTP_201_CREATED,
 )
 async def get(self, request):
 """校验邀请令牌有效性（公开端点，用于邀请页面加载）。"""
 token = request.query_params.get("token", "")
 if not token:
 return Response({"detail": "缺少 token 参数"}, status=status.HTTP_400_BAD_REQUEST)
 try:
 invitation = await sync_to_async(Invitation.objects.get)(token=token)
 except Invitation.DoesNotExist:
 return Response({"detail": "邀请令牌不存在"}, status=status.HTTP_404_NOT_FOUND)
 if not await sync_to_async(invitation.is_valid):
 return Response({"detail": "邀请令牌已过期或已使用"}, status=status.HTTP_410_GONE)
 return Response(InvitationResponseSerializer(invitation).data)
class InvitationAcceptView(APIView):
 """接受邀请并注册新用户（公开端点）。"""
 permission_classes = [AllowAny]
 async def post(self, request):
 serializer = InvitationAcceptSerializer(data=request.data)
 # KEEP: validate_username 执行 DB 查询
 await sync_to_async(serializer.is_valid)(raise_exception=True)
 data = serializer.validated_data
 token = data["token"]
 # 校验邀请令牌
 try:
 invitation = await sync_to_async(Invitation.objects.get)(token=token)
 except Invitation.DoesNotExist:
 return Response({"detail": "邀请令牌不存在"}, status=status.HTTP_404_NOT_FOUND)
 if not await sync_to_async(invitation.is_valid):
 return Response({"detail": "邀请令牌已过期或已使用"}, status=status.HTTP_410_GONE)
 # 检查用户名是否已被占用
 username_exists = await sync_to_async(
 User.objects.filter(username=data["username"]).exists
 )
 if username_exists:
 return Response({"detail": "该用户名已被使用"}, status=status.HTTP_409_CONFLICT)
 # 创建用户
 user = await sync_to_async(User.objects.create_user)(
 username=data["username"],
 password=data["password"],
 email=invitation.email,
 display_name=data.get("display_name", ""),
 )
 # 标记邀请已使用
 invitation.accepted_at = timezone.now
 await sync_to_async(invitation.save)(update_fields=["accepted_at"])
 return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)
class UserListView(APIView):
 """系统用户列表（仅超级管理员）。"""
 async def get(self, request):
 if not request.user.is_superuser:
 return Response({"detail": "仅超级管理员可访问"}, status=status.HTTP_403_FORBIDDEN)
 users = await sync_to_async(list)(User.objects.all.order_by("created_at"))
 return Response(UserSerializer(users, many=True).data)
class UserDetailView(APIView):
 """系统用户详情与状态管理（仅超级管理员）。"""
 async def patch(self, request, user_id: str):
 if not request.user.is_superuser:
 return Response({"detail": "仅超级管理员可访问"}, status=status.HTTP_403_FORBIDDEN)
 try:
 target_user = await sync_to_async(User.objects.get)(pk=user_id)
 except User.DoesNotExist:
 return Response({"detail": "用户不存在"}, status=status.HTTP_404_NOT_FOUND)
 # 仅允许修改 is_active 字段
 if "is_active" in request.data:
 target_user.is_active = bool(request.data["is_active"])
 await target_user.asave(update_fields=["is_active"])
 return Response(UserSerializer(target_user).data)
class ChangePasswordView(APIView):
 """Change password endpoint."""
 async def post(self, request):
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
 await request.user.asave(update_fields=["password", "must_change_password"])
 return Response({"message": "密码修改成功"})
class ForceChangePasswordView(APIView):
 """Force change password endpoint for users with must_change_password flag."""
 async def post(self, request):
 from .serializers import ForceChangePasswordSerializer
 serializer = ForceChangePasswordSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 request.user.set_password(serializer.validated_data["new_password"])
 request.user.must_change_password = False
 await request.user.asave(update_fields=["password", "must_change_password"])
 return Response({"message": "密码修改成功，请重新登录"})
class AdminProfileView(APIView):
 """Admin profile management endpoint."""
 async def get(self, request):
 if not request.user.is_superuser:
 return Response(
 {"detail": "仅超级管理员可访问"},
 status=status.HTTP_403_FORBIDDEN,
 )
 from .serializers import AdminProfileSerializer
 return Response(AdminProfileSerializer(request.user).data)
 async def put(self, request):
 if not request.user.is_superuser:
 return Response(
 {"detail": "仅超级管理员可访问"},
 status=status.HTTP_403_FORBIDDEN,
 )
 from .serializers import AdminProfileUpdateSerializer
 serializer = AdminProfileUpdateSerializer(data=request.data, context={"user": request.user})
 # KEEP: AdminProfileUpdateSerializer.validate_username 执行 User.objects.filter.exists DB 查询
 await sync_to_async(serializer.is_valid)(raise_exception=True)
 user = request.user
 if "username" in serializer.validated_data:
 user.username = serializer.validated_data["username"]
 if "display_name" in serializer.validated_data:
 user.display_name = serializer.validated_data["display_name"]
 await user.asave
 from .serializers import AdminProfileSerializer
 return Response(AdminProfileSerializer(user).data)
class AdminChangePasswordView(APIView):
 """Admin change password endpoint."""
 async def post(self, request):
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
 await request.user.asave(update_fields=["password", "must_change_password"])
 return Response({"message": "密码修改成功"})
