"""Accounts views: Authentication."""

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from audit.emitter import aemit_audit_event

from .models import Invitation, UserSource
from .permissions import SetupNotInitialized
from .serializers import (
    ChangePasswordSerializer,
    InvitationAcceptSerializer,
    InvitationCreateSerializer,
    InvitationResponseSerializer,
    LoginResponseSerializer,
    LoginSerializer,
    MeSerializer,
    ProfileUpdateSerializer,
    SetupInitSerializer,
    TokenResponseSerializer,
    UserSerializer,
)
from .throttles import LoginIPRateThrottle, LoginRateThrottle, RefreshRateThrottle

User = get_user_model()
logger = structlog.get_logger(__name__)


class LoginView(APIView):
    """User login endpoint."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle, LoginIPRateThrottle]

    async def post(self, request):
        serializer = LoginSerializer(data=request.data)
        # KEEP: LoginSerializer.is_valid() 内部调用 authenticate()，涉及 DB 查询
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        user = serializer.validated_data["user"]

        # 登录成功即清空该「IP+用户名」的限流计数：限流只应拦截连续失败（爆破），
        # 不应惩罚正常登录/切换账号（cache 后端可能是 Redis，走 sync_to_async）
        await sync_to_async(LoginRateThrottle().reset)(request)

        # Generate tokens
        # KEEP: simplejwt RefreshToken.for_user() 无 async API
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
            max_age=7 * 24 * 60 * 60,  # 7 days
        )

        # Set access token cookie (HTTP-only, same flags as refresh token)
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=settings.COOKIE_HTTPONLY,
            samesite=settings.COOKIE_SAMESITE,
            secure=settings.COOKIE_SECURE,
            max_age=int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
        )

        # 审计：登录成功
        try:
            await aemit_audit_event(
                action="user.login",
                target_type="User",
                target_id=str(user.id),
                actor_type="user",
                actor_id=str(user.id),
                actor_display=user.username,
            )
        except Exception:
            logger.warning("audit_emit_failed", action="user.login", exc_info=True)

        return response


class LogoutView(APIView):
    """User logout endpoint."""

    authentication_classes = []
    permission_classes = [AllowAny]

    async def post(self, request):
        response = Response({"message": "登出成功"})
        response.delete_cookie("refresh_token")
        response.delete_cookie("access_token")
        return response


class RefreshTokenView(APIView):
    """Refresh access token endpoint.

    每次刷新时签发新 Refresh Token 并废弃旧 Token（Token 旋转），
    防止泄露的 Token 被持续利用。
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [RefreshRateThrottle]

    async def post(self, request):
        refresh_token = request.COOKIES.get("refresh_token")
        if not refresh_token:
            return Response(
                {"detail": "Refresh Token 无效或已过期"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            # simplejwt 的 RefreshToken 构造和 blacklist 涉及 DB 查询，
            # 需要用 sync_to_async 包装所有同步 DB 操作
            old_refresh = await sync_to_async(RefreshToken)(refresh_token)
            # 获取新 access token（在 blacklist 前，因为 blacklist 后 token 不可用）
            access_token = str(old_refresh.access_token)

            # 从 token 中提取用户 ID
            user_id = old_refresh.get("sub") or old_refresh.get("user_id")

            # 将旧 token 加入黑名单
            await sync_to_async(old_refresh.blacklist)()
            logger.info(
                "refresh_token_blacklisted",
                user_id=str(user_id),
                jti=str(old_refresh.get("jti", "")),
            )

            # 签发新 refresh token
            user = await User.objects.aget(pk=user_id)
            new_refresh = await sync_to_async(RefreshToken.for_user)(user)
            new_refresh["sub"] = str(user.id)

            response = Response(TokenResponseSerializer({"access_token": access_token}).data)

            response.set_cookie(
                key="refresh_token",
                value=str(new_refresh),
                httponly=settings.COOKIE_HTTPONLY,
                samesite=settings.COOKIE_SAMESITE,
                secure=settings.COOKIE_SECURE,
                max_age=7 * 24 * 60 * 60,
            )

            # 同步更新 access token cookie
            response.set_cookie(
                key="access_token",
                value=access_token,
                httponly=settings.COOKIE_HTTPONLY,
                samesite=settings.COOKIE_SAMESITE,
                secure=settings.COOKIE_SECURE,
                max_age=int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
            )

            return response
        except TokenError:
            logger.warning("refresh_token_invalid_or_blacklisted", token_prefix=refresh_token[:20])
            response = Response(
                {"detail": "Refresh Token 无效或已过期"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            response.delete_cookie("refresh_token")
            response.delete_cookie("access_token")
            return response
        except Exception:
            logger.exception("refresh_token_unexpected_error")
            response = Response(
                {"detail": "Refresh Token 无效或已过期"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            response.delete_cookie("refresh_token")
            response.delete_cookie("access_token")
            return response


class MeView(APIView):
    """Get current user info endpoint."""

    async def get(self, request):
        # MeSerializer 内部的 get_project_memberships() 需要 DB 查询，用 sync_to_async 包装
        data = await sync_to_async(lambda: MeSerializer(request.user).data)()
        return Response(data)


class ProfileUpdateView(APIView):
    """更新当前用户资料（display_name）。"""

    async def patch(self, request):
        serializer = ProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.display_name = serializer.validated_data["display_name"]
        await user.asave(update_fields=["display_name"])

        # 审计：更新个人资料
        try:
            await aemit_audit_event(
                action="user.updated",
                target_type="User",
                target_id=str(user.id),
                after={"display_name": user.display_name},
            )
        except Exception:
            logger.warning("audit_emit_failed", action="user.updated", exc_info=True)

        data = await sync_to_async(lambda: MeSerializer(user).data)()
        return Response(data)


class InvitationView(APIView):
    """邀请令牌管理：创建（POST）或校验（GET）。"""

    def get_permissions(self) -> list:
        """按 HTTP method 分派权限：GET 公开（校验令牌），POST 需认证（创建邀请）。"""
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsAuthenticated()]

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

        # 审计：创建邀请
        try:
            await aemit_audit_event(
                action="user.invitation_created",
                target_type="Invitation",
                target_id=str(invitation.id),
                after={"email": invitation.email},
            )
        except Exception:
            logger.warning("audit_emit_failed", action="user.invitation_created", exc_info=True)

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

        if not await sync_to_async(invitation.is_valid)():
            return Response({"detail": "邀请令牌已过期或已使用"}, status=status.HTTP_410_GONE)

        return Response(InvitationResponseSerializer(invitation).data)


class InvitationAcceptView(APIView):
    """接受邀请并注册新用户（公开端点）。"""

    authentication_classes = []
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

        if not await sync_to_async(invitation.is_valid)():
            return Response({"detail": "邀请令牌已过期或已使用"}, status=status.HTTP_410_GONE)

        # 检查用户名是否已被占用
        username_exists = await sync_to_async(
            User.objects.filter(username=data["username"]).exists
        )()
        if username_exists:
            return Response({"detail": "该用户名已被使用"}, status=status.HTTP_409_CONFLICT)

        # 创建用户
        user = await sync_to_async(User.objects.create_user)(
            username=data["username"],
            password=data["password"],
            email=invitation.email,
            display_name=data.get("display_name", ""),
            source=UserSource.INVITATION.value,
        )

        # 标记邀请已使用
        invitation.accepted_at = timezone.now()
        await sync_to_async(invitation.save)(update_fields=["accepted_at"])

        # 审计：邀请注册用户
        try:
            await aemit_audit_event(
                action="user.created",
                target_type="User",
                target_id=str(user.id),
                after={"username": user.username, "source": UserSource.INVITATION.value},
            )
        except Exception:
            logger.warning("audit_emit_failed", action="user.created", exc_info=True)

        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class UserListView(APIView):
    """系统用户列表（仅超级管理员）。"""

    async def get(self, request):
        if not request.user.is_superuser:
            return Response({"detail": "仅超级管理员可访问"}, status=status.HTTP_403_FORBIDDEN)

        users = await sync_to_async(list)(User.objects.all().order_by("created_at"))
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
            old_is_active = target_user.is_active
            target_user.is_active = bool(request.data["is_active"])
            await target_user.asave(update_fields=["is_active"])

            # 审计：用户状态变更
            try:
                await aemit_audit_event(
                    action="user.updated",
                    target_type="User",
                    target_id=str(target_user.id),
                    before={"is_active": old_is_active},
                    after={"is_active": target_user.is_active},
                )
            except Exception:
                logger.warning("audit_emit_failed", action="user.updated", exc_info=True)

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

        # 审计：密码修改
        try:
            await aemit_audit_event(
                action="user.password_changed",
                target_type="User",
                target_id=str(request.user.id),
            )
        except Exception:
            logger.warning("audit_emit_failed", action="user.password_changed", exc_info=True)

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

        # 审计：强制密码修改
        try:
            await aemit_audit_event(
                action="user.password_changed",
                target_type="User",
                target_id=str(request.user.id),
            )
        except Exception:
            logger.warning("audit_emit_failed", action="user.password_changed", exc_info=True)

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
        # KEEP: AdminProfileUpdateSerializer.validate_username() 执行 User.objects.filter().exists() DB 查询
        await sync_to_async(serializer.is_valid)(raise_exception=True)

        user = request.user
        if "username" in serializer.validated_data:
            user.username = serializer.validated_data["username"]
        if "display_name" in serializer.validated_data:
            user.display_name = serializer.validated_data["display_name"]
        await user.asave()

        # 审计：管理员更新 profile
        try:
            await aemit_audit_event(
                action="user.updated",
                target_type="User",
                target_id=str(user.id),
                after={
                    "username": user.username,
                    "display_name": user.display_name,
                },
            )
        except Exception:
            logger.warning("audit_emit_failed", action="user.updated", exc_info=True)

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

        # 审计：管理员密码修改
        try:
            await aemit_audit_event(
                action="user.password_changed",
                target_type="User",
                target_id=str(request.user.id),
            )
        except Exception:
            logger.warning("audit_emit_failed", action="user.password_changed", exc_info=True)

        return Response({"message": "密码修改成功"})


# ============================================================================
# 首启向导门禁层（SETUP-02/03/04）
# ============================================================================


class SetupStatusView(APIView):
    """只读初始化状态接口。

    GET /api/auth/setup/status/ 无需认证，不泄露用户名/数量，
    仅返回 {is_initialized: bool, needs_setup: bool}（SETUP-02）。
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    async def get(self, request):
        import os

        is_initialized = await sync_to_async(User.objects.filter(is_superuser=True).exists)()
        # Qdrant 由部署环境管理：只要注入了 QDRANT_URL（helm/compose 内置或外接），即视为"已托管"，
        # 向导锁定 Qdrant 地址、连接直接走 env（见 QdrantService.get_config 的 env 优先级）。
        # 兼容旧 compose：QDRANT_BUNDLED 显式置位也算托管。
        env_qdrant_url = os.environ.get("QDRANT_URL", "").strip()
        qdrant_bundled = bool(env_qdrant_url) or os.environ.get(
            "QDRANT_BUNDLED", ""
        ).strip().lower() in {
            "1",
            "true",
            "yes",
        }
        return Response(
            {
                "is_initialized": is_initialized,
                "needs_setup": not is_initialized,
                "qdrant_bundled": qdrant_bundled,
                # 托管时回传真实地址，供向导锁定展示（非托管为空字符串）
                "qdrant_url": env_qdrant_url,
            }
        )


def _atomic_create_superuser(username: str, password: str, display_name: str):
    """在原子事务内创建 superuser，并发/重入安全。

    返回 None 表示已存在 superuser（并发冲突），由调用方返回 409。
    SQLite 依赖 WAL 写锁串行化，Postgres 依赖 READ COMMITTED 事务；
    不使用 select_for_update()——SQLite 不支持，会抛 NotSupportedError。
    IntegrityError（username UNIQUE 约束）作最终兜底（SETUP-04）。
    """
    with transaction.atomic():
        if User.objects.filter(is_superuser=True).exists():
            return None
        return User.objects.create_superuser(
            username=username,
            password=password,
            display_name=display_name,
            source=UserSource.SYSTEM.value,
        )


class SetupInitView(APIView):
    """首启初始化写入接口（fail-closed + 防重入）。

    POST /api/auth/setup/ — 仅当无 superuser 时可用（SETUP-03），
    在原子事务内创建 superuser 并返回 201（SETUP-02）；
    已初始化时 SetupNotInitialized 返回 403，与调用者身份无关（SETUP-04）。

    注意：authentication_classes = [] 是必要的：
    DRF 在 permission_denied() 中检查 request.authenticators，
    若存在 authenticator 但无成功认证则抛 NotAuthenticated (401) 而非 PermissionDenied (403)。
    清空 authentication_classes 确保匿名请求被 SetupNotInitialized 拒绝时返回 403。
    """

    authentication_classes = []
    permission_classes = [AllowAny, SetupNotInitialized]

    async def post(self, request):
        serializer = SetupInitSerializer(data=request.data)
        # KEEP: validate_username 执行 DB 查询，需要 sync_to_async 包装
        await sync_to_async(serializer.is_valid)(raise_exception=True)

        try:
            user = await sync_to_async(_atomic_create_superuser)(
                username=serializer.validated_data["username"],
                password=serializer.validated_data["password"],
                display_name=serializer.validated_data.get("display_name", "系统管理员"),
            )
        except IntegrityError:
            return Response({"detail": "用户名已存在"}, status=status.HTTP_409_CONFLICT)

        if user is None:
            logger.warning("setup_init_conflict_concurrent")
            return Response(
                {"detail": "系统已初始化，初始化接口已关闭"}, status=status.HTTP_409_CONFLICT
            )

        logger.info("setup_init_success", username=serializer.validated_data["username"])

        # 审计：首启初始化创建管理员
        try:
            await aemit_audit_event(
                action="user.created",
                target_type="User",
                target_id=str(user.id),
                actor_type="system",
                actor_id="system",
                actor_display="首启向导",
                after={
                    "username": serializer.validated_data["username"],
                    "display_name": serializer.validated_data.get("display_name", "系统管理员"),
                    "source": UserSource.SYSTEM.value,
                },
            )
        except Exception:
            logger.warning("audit_emit_failed", action="user.created", exc_info=True)

        # 创建成功后复用 LoginView 的 cookie-JWT 路径建立会话，使前端无需二次登录（ADMIN-03）。
        # must_change_password 保持 create_superuser 的默认 False，不强制改密（ADMIN-02）。
        refresh = await sync_to_async(RefreshToken.for_user)(user)
        refresh["sub"] = str(user.id)
        access_token = str(refresh.access_token)

        response = Response(
            LoginResponseSerializer(
                {
                    "access_token": access_token,
                    "user": user,
                    "must_change_password": user.must_change_password,
                }
            ).data,
            status=status.HTTP_201_CREATED,
        )

        # Set refresh token cookie
        response.set_cookie(
            key="refresh_token",
            value=str(refresh),
            httponly=settings.COOKIE_HTTPONLY,
            samesite=settings.COOKIE_SAMESITE,
            secure=settings.COOKIE_SECURE,
            max_age=7 * 24 * 60 * 60,  # 7 days
        )

        # Set access token cookie (HTTP-only, same flags as refresh token)
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=settings.COOKIE_HTTPONLY,
            samesite=settings.COOKIE_SAMESITE,
            secure=settings.COOKIE_SECURE,
            max_age=int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
        )

        return response
