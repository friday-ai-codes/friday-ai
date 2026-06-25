"""入站 Git 平台 MR/PR 状态 webhook 接收端点（MR-02）。

新增受保护端点 ``POST /api/git-webhooks/<platform>/``（platform ∈ github/gitlab）：

1. **共享密钥校验 fail-closed**：GitHub 校验 ``X-Hub-Signature-256`` HMAC-SHA256；GitLab 校验
   ``X-Gitlab-Token`` 等值。密钥取 ``SettingKeys.GIT_WEBHOOK_SECRET``；**未配置即拒绝**
   （绝不放行未签名 payload）。
2. **原始 payload 留痕**：经 ``system.webhook_recorder.record_inbound_webhook``（已
   ``redact_for_ledger`` + 截断 + best-effort）写 ``InboundWebhookEvent``（kind=``git_mr``）。
3. **状态同步**：``MergeRequestService.sync_from_webhook``（幂等去重 + 脱敏事件留痕），
   后台/外部触发携 ``initiated_by_user_id="system"``（无 git↔Friday 用户映射）。

观测：best-effort，绝不反噬；端点无 JWT（webhook 经密钥鉴权），认证类置空。
"""

from __future__ import annotations

import hashlib
import hmac
import json

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from initiatives.models import MRPlatform
from initiatives.services.mr_service import MergeRequestService, MergeRequestSyncError
from system.webhook_recorder import client_ip, record_inbound_webhook

logger = structlog.get_logger(__name__)

_KIND_GIT_MR = "git_mr"


@sync_to_async
def _get_webhook_secret() -> str:
    from system.models import SettingKeys, SystemSetting

    obj = SystemSetting.objects.filter(key=SettingKeys.GIT_WEBHOOK_SECRET).first()
    if obj is None or not obj.value:
        return ""
    if getattr(obj, "is_encrypted", False):
        try:
            from common.encryption import decrypt_value

            return decrypt_value(obj.value)
        except Exception:  # noqa: BLE001 — 解密失败视为未配置（fail-closed）
            return ""
    return obj.value


def _verify_github(secret: str, raw_body: bytes, signature_header: str) -> bool:
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header.split("=", 1)[1]
    return hmac.compare_digest(expected, provided)


def _verify_gitlab(secret: str, token_header: str) -> bool:
    return bool(token_header) and hmac.compare_digest(secret, token_header)


class GitMergeRequestWebhookView(APIView):
    """POST /api/git-webhooks/<platform>/ — GitHub/GitLab MR 状态入站同步（MR-02）。"""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    async def post(self, request, platform: str):
        platform = (platform or "").lower()
        if platform not in (MRPlatform.GITHUB, MRPlatform.GITLAB):
            return Response(
                {"detail": "unsupported platform"}, status=status.HTTP_400_BAD_REQUEST
            )

        secret = await _get_webhook_secret()
        if not secret:
            # fail-closed：未配置密钥绝不放行未签名 payload。
            logger.warning(
                "git_webhook_rejected_no_secret",
                platform=platform,
                category="caller",
                component="initiatives",
            )
            return Response(
                {"detail": "webhook secret not configured"},
                status=status.HTTP_403_FORBIDDEN,
            )

        raw_body: bytes = request.body or b""
        meta = request.META
        if platform == MRPlatform.GITHUB:
            verified = _verify_github(
                secret, raw_body, str(meta.get("HTTP_X_HUB_SIGNATURE_256", ""))
            )
        else:
            verified = _verify_gitlab(secret, str(meta.get("HTTP_X_GITLAB_TOKEN", "")))

        if not verified:
            logger.warning(
                "git_webhook_signature_invalid",
                platform=platform,
                category="caller",
                component="initiatives",
            )
            return Response(
                {"detail": "invalid signature"}, status=status.HTTP_403_FORBIDDEN
            )

        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return Response({"detail": "invalid json"}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(payload, dict):
            return Response({"detail": "invalid payload"}, status=status.HTTP_400_BAD_REQUEST)

        # 原始 payload 脱敏后留痕（best-effort，绝不反噬）。
        delivery_id = str(
            meta.get("HTTP_X_GITHUB_DELIVERY") or meta.get("HTTP_X_GITLAB_EVENT_UUID") or ""
        )
        try:
            await record_inbound_webhook(
                kind=_KIND_GIT_MR,
                raw_body=payload,
                headers=dict(request.headers),
                source_ip=client_ip(request),
                user_id="system",
                verified=True,
                correlation={"platform": platform, "delivery_id": delivery_id},
            )
        except Exception:  # noqa: BLE001 — 留痕 best-effort
            pass

        dedup_key = (
            f"{platform}:delivery:{delivery_id}" if delivery_id else None
        )
        try:
            result = await MergeRequestService().sync_from_webhook(
                platform=platform,
                payload=payload,
                dedup_key=dedup_key,
                initiated_by_user_id="system",
            )
        except MergeRequestSyncError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:  # noqa: BLE001 — 同步异常不向平台暴露细节，但响应 200 避免重投风暴
            logger.exception("git_webhook_sync_failed", platform=platform)
            return Response({"detail": "ok"}, status=status.HTTP_200_OK)

        return Response(result, status=status.HTTP_200_OK)
