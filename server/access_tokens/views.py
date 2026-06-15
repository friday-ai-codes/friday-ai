"""access_tokens app views —— Friday Access Token 管理 API。

Web 用户经现有 CookieJWT 认证管理「自己」创建的 token：
- create：一次性返回明文（contract），明文绝不入库（contract）。
- list/detail：仅返回元数据，永不返回明文（contract）。
- revoke：软吊销（revoked_at）。
- get_queryset 强制 created_by=request.user，跨用户隔离（安全域 V4）。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from accounts.models import User
from adrf.viewsets import ModelViewSet
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from runners.models import hash_token

from .models import AccessToken, generate_pat
from .serializers import AccessTokenCreateSerializer, AccessTokenSerializer

import structlog
from audit.emitter import aemit_audit_event

logger = structlog.get_logger(__name__)

# 默认过期时长：90 天（CONTEXT：缺省 90 天，可显式传 None 永不过期）。
DEFAULT_EXPIRY = timedelta(days=90)


class AccessTokenViewSet(ModelViewSet):
    """Access Token 管理（CookieJWT 认证，按 created_by 隔离）。"""

    serializer_class = AccessTokenSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self) -> Any:
        # 跨用户隔离：用户只能看见/操作自己创建的 token（安全域 V4）。
        return AccessToken.objects.filter(created_by=self.request.user).order_by(
            "-created_at"
        )

    async def acreate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = AccessTokenCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 缺省 90 天过期；显式传 expires_at=None 表示永不过期。
        if "expires_at" in data:
            expires_at = data["expires_at"]
        else:
            expires_at = timezone.now() + DEFAULT_EXPIRY

        # IsAuthenticated 保证 request.user 为真实 User（非 AnonymousUser）。
        user = cast(User, request.user)
        plaintext = generate_pat()
        token = await AccessToken.objects.acreate(
            name=data["name"],
            note=data.get("note", ""),
            token_hash=hash_token(plaintext),
            token_prefix=plaintext[:12],
            # 指纹后缀：明文后 4 字符，仅由内存中明文派生（绝不回传明文再反推）。
            token_suffix=plaintext[-4:],
            expires_at=expires_at,
            created_by=user,
        )

        response_data = AccessTokenSerializer(token).data
        # 明文 token 仅此一次返回，不入任何 DB 字段（contract / contract）。
        response_data["token"] = plaintext

        # 审计：创建访问令牌
        try:
            await aemit_audit_event(
                action="access_token.created",
                target_type="AccessToken",
                target_id=str(token.id),
                after={"name": data["name"], "token_prefix": plaintext[:12]},
            )
        except Exception:
            logger.warning("audit_emit_failed", action="access_token.created", exc_info=True)

        return Response(response_data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    async def revoke(self, request: Request, pk: str | None = None) -> Response:
        # aget_object 已受 get_queryset 限定，天然防越权吊销他人 token。
        token = await self.aget_object()
        # 幂等保护：仅首次吊销写入 revoked_at；重复吊销保留首次时间戳，
        # 避免覆盖审计记录（重复 revoke 仍返回 200 + 当前序列化结果）。
        revoked = token.revoked_at is None
        if revoked:
            token.revoked_at = timezone.now()
            await token.asave(update_fields=["revoked_at"])

            # 审计：吊销访问令牌
            try:
                await aemit_audit_event(
                    action="access_token.revoked",
                    target_type="AccessToken",
                    target_id=str(token.id),
                    after={"name": token.name},
                )
            except Exception:
                logger.warning("audit_emit_failed", action="access_token.revoked", exc_info=True)

        return Response(AccessTokenSerializer(token).data)
