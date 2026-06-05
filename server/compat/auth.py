"""OptionalBearerTokenAuth — 可选 Bearer Token 鉴权桩（contract/work item）。

默认 AllowAny；配置 OPENAI_COMPAT_API_KEYS 为非空列表后启用 Bearer token 白名单匹配。
"""

from __future__ import annotations

import hmac

import structlog
from django.conf import settings
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

logger = structlog.get_logger(__name__)


class OptionalBearerTokenAuth(BasePermission):
    """白名单为空时 AllowAny；非空时校验 Authorization: Bearer <token>。

    使用 hmac.compare_digest 防 timing attack（ASVS V2.1，security mitigation）。
    """

    def has_permission(self, request: Request, view: APIView) -> bool:  # type: ignore[override]
        whitelist: list[str] = settings.OPENAI_COMPAT_API_KEYS
        if not whitelist:
            logger.debug("compat_auth", auth_result="allowed", reason="whitelist_empty")
            return True

        auth_header: str = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            logger.warning("compat_auth", auth_result="denied", reason="missing_bearer_header")
            return False

        token = auth_header[7:].strip()
        # 强制与所有 key 完整比较，避免 any() 短路破坏常量时间保证（work item/security mitigation）
        matches = [hmac.compare_digest(token, key) for key in whitelist]
        is_valid = any(matches)
        if is_valid:
            logger.info("compat_auth", auth_result="allowed", reason="token_matched")
        else:
            logger.warning("compat_auth", auth_result="denied", reason="token_not_in_whitelist")
        return is_valid
