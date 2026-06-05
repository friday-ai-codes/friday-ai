"""Chat API 自定义鉴权。

包含两个 authenticator：
- OptionalJWTAuthentication: 宽容模式的 JWT 认证，token 无效时返回 None 而非 401
- ChatKeyAuthentication: X-Chat-Key header 密钥认证

两者与 ChatAuthPermission 配合：认证失败不直接拒绝请求，
而是交由权限类根据鉴权开关决定是否放行。
"""

import hmac

import structlog
from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from common.authentication import CookieJWTAuthentication
from common.encryption import decrypt_value
from system.models import SettingKeys, SystemSetting

logger = structlog.get_logger(__name__)


class OptionalJWTAuthentication(CookieJWTAuthentication):
    """宽容模式的 JWT 认证（cookie 优先 + Authorization header 兜底）。

    与基类 ``CookieJWTAuthentication`` 的区别：
    - token 无效/过期时返回 None（交给下一个 authenticator），而非抛 AuthenticationFailed
    - 没有 token 时同样返回 None

    历史坑（implementation 之后暴露）：早期版本继承的是 SimpleJWT 默认
    ``JWTAuthentication``，**只看 Authorization header**。而项目全局默认认证（设置
    在 ``REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES`` 里）是 cookie 优先的
    ``CookieJWTAuthentication`` —— 前端只通过 HttpOnly cookie 携带 access_token。
    当 chat view 显式声明 ``authentication_classes = [OptionalJWTAuthentication, ...]``
    时就覆盖了全局默认，cookie 路径被丢弃，前端永远拿到 401，触发 ``auth:logout``
    跳首页（典型现象：``/api/chat/coding-sessions/<id>/confirm/`` 永远报"身份认证
    信息未提供"）。改继承 ``CookieJWTAuthentication`` 后两条路径都吃，行为与全局
    默认一致，宽容性仅叠在最外层。

    这样 ChatAuthPermission 才能正常根据鉴权开关决定是否放行，
    避免「开关关闭但过期 token 仍导致 401」的问题。
    """

    def authenticate(
        self, request
    ):  # DRF BaseAuthentication.authenticate 方法返回类型为 optional tuple
        try:
            return super().authenticate(request)
        except AuthenticationFailed:
            logger.debug("jwt_auth_skipped", reason="token invalid or expired")
            return None


class ChatKeyAuthentication(BaseAuthentication):
    """通过 X-Chat-Key header 认证。

    认证逻辑：
    - header 不存在 → 返回 None（交给下一个 authenticator）
    - 配置密钥不存在 → 返回 None
    - header 值匹配 → 返回 (AnonymousUser(), "chat-key")
    - header 值不匹配 → raise AuthenticationFailed

    注意：authenticate() 是同步方法（DRF BaseAuthentication 要求），
    在 async view 中 DRF/adrf 会自动用 sync_to_async 包装。
    """

    def authenticate(self, request) -> tuple | None:
        """验证 X-Chat-Key header。"""
        chat_key = request.META.get("HTTP_X_CHAT_KEY")
        if not chat_key:
            return None

        # 从 SystemSetting 获取配置密钥
        try:
            setting = SystemSetting.objects.get(key=SettingKeys.CHAT_KEY)
        except SystemSetting.DoesNotExist:
            return None

        if not setting.value:
            return None

        # 解密（如果加密存储）
        expected_key = decrypt_value(setting.value) if setting.is_encrypted else setting.value

        # 常量时间比较，防止 timing attack
        if hmac.compare_digest(chat_key, expected_key):
            return (AnonymousUser(), "chat-key")

        raise AuthenticationFailed("无效的 Chat Key")

    def authenticate_header(self, request) -> str:
        """返回 WWW-Authenticate header 值。"""
        return "X-Chat-Key"
