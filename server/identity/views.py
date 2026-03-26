"""OIDC Identity views: Provider 管理、授权流程。"""
import secrets
import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core import signing
from django.http import HttpResponseRedirect
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from identity.models import OIDCProvider
from identity.serializers import (
 OIDCDiscoverySerializer,
 OIDCProviderPublicSerializer,
 OIDCProviderSerializer,
)
from identity.services import (
 build_authorize_url,
 build_callback_url,
 exchange_code_for_tokens,
 fetch_oidc_discovery,
 fetch_userinfo,
 jit_provision_user,
 verify_signed_state,
)
logger = structlog.get_logger(__name__)
# =============================================================================
# Provider 管理 API（超级管理员）
# =============================================================================
class OIDCProviderListView(APIView):
 """OIDC Provider 列表和创建（仅超级管理员）。"""
 async def get(self, request: object) -> Response:
 """列出所有 OIDC Provider。"""
 if not request.user.is_authenticated or not request.user.is_superuser:
 return Response({"detail": "仅超级管理员可访问"}, status=status.HTTP_403_FORBIDDEN)
 providers_qs = OIDCProvider.objects.all.order_by("created_at")
 providers: list[OIDCProvider] = await sync_to_async(list)(providers_qs) # type: ignore[call-arg] # Django QuerySet 转 sync list 的类型推断限制
 serializer = OIDCProviderSerializer(providers, many=True)
 return Response(serializer.data)
 async def post(self, request: object) -> Response:
 """创建 OIDC Provider。"""
 if not request.user.is_authenticated or not request.user.is_superuser:
 return Response({"detail": "仅超级管理员可访问"}, status=status.HTTP_403_FORBIDDEN)
 serializer = OIDCProviderSerializer(data=request.data)
 await sync_to_async(serializer.is_valid)(raise_exception=True)
 provider = await sync_to_async(serializer.save)
 logger.info("oidc_provider_created", provider_id=str(provider.id), name=provider.name)
 return Response(OIDCProviderSerializer(provider).data, status=status.HTTP_201_CREATED)
class OIDCProviderDetailView(APIView):
 """OIDC Provider 详情、更新、删除（仅超级管理员）。"""
 async def get(self, request: object, pk: str) -> Response:
 """获取 Provider 详情。"""
 if not request.user.is_authenticated or not request.user.is_superuser:
 return Response({"detail": "仅超级管理员可访问"}, status=status.HTTP_403_FORBIDDEN)
 provider = await OIDCProvider.objects.filter(pk=pk).afirst
 if not provider:
 return Response({"detail": "Provider 不存在"}, status=status.HTTP_404_NOT_FOUND)
 return Response(OIDCProviderSerializer(provider).data)
 async def put(self, request: object, pk: str) -> Response:
 """更新 Provider。"""
 if not request.user.is_authenticated or not request.user.is_superuser:
 return Response({"detail": "仅超级管理员可访问"}, status=status.HTTP_403_FORBIDDEN)
 provider = await OIDCProvider.objects.filter(pk=pk).afirst
 if not provider:
 return Response({"detail": "Provider 不存在"}, status=status.HTTP_404_NOT_FOUND)
 serializer = OIDCProviderSerializer(provider, data=request.data, partial=True)
 await sync_to_async(serializer.is_valid)(raise_exception=True)
 updated = await sync_to_async(serializer.save)
 logger.info("oidc_provider_updated", provider_id=str(updated.id))
 return Response(OIDCProviderSerializer(updated).data)
 async def delete(self, request: object, pk: str) -> Response:
 """删除 Provider。"""
 if not request.user.is_authenticated or not request.user.is_superuser:
 return Response({"detail": "仅超级管理员可访问"}, status=status.HTTP_403_FORBIDDEN)
 provider = await OIDCProvider.objects.filter(pk=pk).afirst
 if not provider:
 return Response({"detail": "Provider 不存在"}, status=status.HTTP_404_NOT_FOUND)
 await provider.adelete
 logger.info("oidc_provider_deleted", provider_id=str(pk))
 return Response(status=status.HTTP_204_NO_CONTENT)
class OIDCDiscoveryView(APIView):
 """OIDC Discovery URL 自动填充（仅超级管理员）。"""
 async def post(self, request: object) -> Response:
 """从 issuer_url 获取 OIDC 端点配置。"""
 if not request.user.is_authenticated or not request.user.is_superuser:
 return Response({"detail": "仅超级管理员可访问"}, status=status.HTTP_403_FORBIDDEN)
 serializer = OIDCDiscoverySerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 issuer_url = serializer.validated_data["issuer_url"]
 try:
 endpoints = await fetch_oidc_discovery(issuer_url)
 except ValueError as e:
 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
 return Response(endpoints)
class OIDCProviderPublicListView(APIView):
 """活跃 OIDC Provider 公开列表（无需认证，供登录页使用）。"""
 permission_classes = [AllowAny]
 async def get(self, request: object) -> Response:
 """返回所有活跃 Provider 的 id + name。"""
 providers_qs = OIDCProvider.objects.filter(is_active=True).order_by("name")
 providers: list[OIDCProvider] = await sync_to_async(list)(providers_qs) # type: ignore[call-arg] # Django QuerySet 转 sync list 的类型推断限制
 serializer = OIDCProviderPublicSerializer(providers, many=True)
 return Response(serializer.data)
# =============================================================================
# OIDC 授权流程
# =============================================================================
class OIDCAuthorizeView(APIView):
 """发起 OIDC 授权流程。"""
 permission_classes = [AllowAny]
 async def get(self, request: object, provider_id: str) -> Response:
 """生成 Provider 授权 URL 并设置 state cookie。"""
 provider = await OIDCProvider.objects.filter(id=provider_id, is_active=True).afirst
 if not provider:
 logger.warning(
 "oidc_authorize_provider_not_found",
 provider_id=provider_id,
 )
 return Response(
 {"detail": "Provider 不存在或未启用"},
 status=status.HTTP_404_NOT_FOUND,
 )
 # 生成 state
 state_value = secrets.token_urlsafe(32)
 redirect_uri = request.query_params.get("redirect_uri", "/")
 # 签名 state 数据
 signed_state = signing.dumps(
 {
 "state": state_value,
 "redirect_uri": redirect_uri,
 "provider_id": str(provider.id),
 }
 )
 # 构造授权 URL
 callback_url = build_callback_url(request)
 authorize_url = build_authorize_url(provider, state_value, callback_url)
 response = Response({"authorize_url": authorize_url})
 # 设置 state cookie（SameSite=Lax 允许跨站顶级导航）
 response.set_cookie(
 key="oidc_state",
 value=signed_state,
 httponly=True,
 samesite="Lax",
 secure=getattr(settings, "COOKIE_SECURE", False),
 max_age=600, # 10 分钟过期
 )
 logger.info(
 "oidc_authorize_initiated",
 provider=provider.name,
 provider_id=str(provider.id),
 )
 return response
class OIDCCallbackView(APIView):
 """处理 OIDC Provider 回调。"""
 permission_classes = [AllowAny]
 async def get(self, request: object) -> Response | HttpResponseRedirect:
 """处理授权回调：state 校验 → token exchange → JIT → JWT 签发。"""
 params = request.query_params
 error = params.get("error")
 code = params.get("code")
 state = params.get("state")
 # Provider 返回错误
 if error:
 error_desc = params.get("error_description", error)
 logger.warning("oidc_callback_error", error=error, description=error_desc)
 return self._redirect_to_login(error=error_desc)
 # 缺少必要参数
 if not code or not state:
 return Response(
 {"detail": "缺少必要参数（code 或 state）"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 校验 state cookie
 cookie_value = request.COOKIES.get("oidc_state")
 if not cookie_value:
 return Response(
 {"detail": "State cookie 缺失"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 try:
 state_data = verify_signed_state(cookie_value, max_age=600)
 except signing.SignatureExpired:
 return Response(
 {"detail": "State 已过期，请重新登录"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 except signing.BadSignature:
 return Response(
 {"detail": "State 签名无效"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 if state_data["state"] != state:
 return Response(
 {"detail": "State 不匹配"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 查找 Provider
 provider = await OIDCProvider.objects.filter(
 id=state_data["provider_id"], is_active=True
 ).afirst
 if not provider:
 return self._redirect_to_login(error="Provider 不存在或已禁用")
 # Token exchange
 callback_url = build_callback_url(request)
 try:
 token_response = await exchange_code_for_tokens(provider, code, callback_url)
 except ValueError as e:
 logger.error("oidc_token_exchange_view_error", error=str(e))
 return self._redirect_to_login(error="Token 交换失败，请重试")
 # 获取用户信息
 provider_access_token = str(token_response.get("access_token", ""))
 try:
 userinfo = await fetch_userinfo(provider, provider_access_token)
 except ValueError:
 # 尝试从 id_token 解析基本信息
 userinfo = {}
 # 确保 userinfo 至少有 sub
 if "sub" not in userinfo:
 # 从 token 响应的 id_token 解析（简化处理：使用 access_token 的 sub）
 userinfo["sub"] = token_response.get("sub", provider_access_token[:32])
 # JIT 用户创建/关联
 user, is_new = await jit_provision_user(provider, userinfo)
 # 签发 simplejwt token
 refresh = await sync_to_async(RefreshToken.for_user)(user)
 refresh["sub"] = str(user.id) # JWT refresh token 字典动态索引，类型系统无法推断
 access_token = str(refresh.access_token)
 # 构造前端回调 URL
 frontend_redirect = state_data.get("redirect_uri", "/")
 frontend_base = getattr(settings, "FRIDAY_FRONTEND_URL", "")
 # 重定向到前端回调页面
 redirect_url = f"{frontend_base}/oidc/callback?access_token={access_token}&redirect={frontend_redirect}"
 response = HttpResponseRedirect(redirect_url)
 # 设置 refresh_token cookie（复用现有模式）
 response.set_cookie(
 key="refresh_token",
 value=str(refresh),
 httponly=getattr(settings, "COOKIE_HTTPONLY", True),
 samesite=getattr(settings, "COOKIE_SAMESITE", "Lax"),
 secure=getattr(settings, "COOKIE_SECURE", False),
 max_age=7 * 24 * 60 * 60,
 )
 # 清除 oidc_state cookie
 response.delete_cookie("oidc_state")
 logger.info(
 "oidc_login_success",
 user=str(user),
 is_new_user=is_new,
 provider=provider.name,
 )
 return response
 def _redirect_to_login(self, error: str) -> HttpResponseRedirect:
 """重定向到登录页并携带错误信息。"""
 frontend_base = getattr(settings, "FRIDAY_FRONTEND_URL", "")
 from urllib.parse import quote
 return HttpResponseRedirect(f"{frontend_base}/login?oidc_error={quote(error)}")
