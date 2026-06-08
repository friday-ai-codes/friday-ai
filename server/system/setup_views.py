"""首启向导 Phase 4：安全密钥校验（只读，非阻塞）+ 飞书 / 向量检索可选配置编排端点。

设计要点（关键复用约束）：
- 飞书 / RAG 配置一律复用既有 `SystemSetting` + `SettingKeys` + `common.encryption.encrypt_value`，
  写法与 `bootstrap_system_settings` 一致（非敏感项明文 `is_encrypted=False`，敏感项 Fernet 密文
  `is_encrypted=True`）；既有读路径（feishu/websocket_client、services/feishu_im、qdrant_service、
  repositories/index_views）已按 `is_encrypted` / `decrypt_value` 兼容，故加密落库对读取透明。
- 安全校验端点只读、只返回布尔判定 + 风险清单，**绝不回显任何密钥明文**，且**永不阻塞**向导完成。
- adrf 异步视图；ORM 写经 `sync_to_async`（与 `ProviderSetupWizardView` 一致）。

权限：均为 `IsSuperUser`（向导完成管理员创建并自动登录后，调用方为已认证 superuser）。
"""

from __future__ import annotations

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.conf import settings
from rest_framework import status
from rest_framework.response import Response

from common.encryption import encrypt_value
from permissions.api_permissions import IsSuperUser

from .models import SettingKeys, SystemSetting
from .setup_serializers import SetupFeishuSerializer, SetupRagSerializer

logger = structlog.get_logger(__name__)

# 与 friday/settings.py 的 INSECURE_SECRET_KEY 同值；settings 暴露大写模块变量，
# 优先 getattr 取真实值，缺失时用同一字符串常量兜底。
_DEFAULT_INSECURE_SECRET_KEY = "django-insecure-change-me-in-production"


class SetupSecurityCheckView(APIView):
    """GET /api/system/security-check/ —— 加密/安全密钥健康校验（SEC-01，只读，非阻塞）。

    检测 `SECRET_KEY` / `FRIDAY_ENCRYPTION_KEY` 是否安全（非默认、相互独立），返回布尔判定 +
    风险清单（`level="warning"`）。**绝不返回任何密钥明文**；调用方据此展示风险提示，但不得阻塞向导。
    """

    permission_classes = [IsSuperUser]

    async def get(self, request) -> Response:  # type: ignore[no-untyped-def]
        secret_key = getattr(settings, "SECRET_KEY", "") or ""
        enc_key = getattr(settings, "FRIDAY_ENCRYPTION_KEY", "") or ""
        insecure_default = getattr(settings, "INSECURE_SECRET_KEY", _DEFAULT_INSECURE_SECRET_KEY)

        secret_key_secure = bool(secret_key) and secret_key != insecure_default
        encryption_key_set = bool(enc_key)
        # 加密密钥为空时回退派生自 SECRET_KEY（common/encryption._derive_fernet_key）→ 视为不独立
        keys_independent = bool(enc_key) and enc_key != secret_key

        risks: list[dict[str, str]] = []
        if not secret_key_secure:
            risks.append({"code": "secret_key_default", "level": "warning"})
        if not encryption_key_set:
            risks.append({"code": "encryption_key_unset", "level": "warning"})
        if encryption_key_set and not keys_independent:
            risks.append({"code": "keys_not_independent", "level": "warning"})

        return Response(
            {
                "secure": secret_key_secure and encryption_key_set and keys_independent,
                "secret_key_secure": secret_key_secure,
                "encryption_key_set": encryption_key_set,
                "keys_independent": keys_independent,
                "risks": risks,
            }
        )


class SetupFeishuWizardView(APIView):
    """POST /api/system/setup-feishu/ —— 飞书集成可选配置（FEISHU-01/02）。

    写入与既有 `SystemSetting` / `bootstrap_system_settings` 路径一致：
    - `FEISHU_APP_ID` → 明文（非敏感）。
    - `FEISHU_APP_SECRET` → `encrypt_value` 密文 + `is_encrypted=True`（既有读路径按 is_encrypted 解密）。
    幂等：`update_or_create`，向导可重试覆盖。跳过由前端不调用本端点实现。
    """

    permission_classes = [IsSuperUser]

    async def post(self, request) -> Response:  # type: ignore[no-untyped-def]
        serializer = SetupFeishuSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        data = serializer.validated_data
        app_id = data["app_id"]
        app_secret = data["app_secret"]

        @sync_to_async
        def _write() -> None:
            SystemSetting.objects.update_or_create(
                key=SettingKeys.FEISHU_APP_ID,
                defaults={
                    "value": app_id,
                    "is_encrypted": False,
                    "description": "Feishu App ID configured via setup wizard",
                },
            )
            SystemSetting.objects.update_or_create(
                key=SettingKeys.FEISHU_APP_SECRET,
                defaults={
                    "value": encrypt_value(app_secret),
                    "is_encrypted": True,
                    "description": "Feishu App Secret configured via setup wizard",
                },
            )

        await _write()
        logger.info("setup_feishu_configured", user_id=str(request.user.id))
        return Response({"feishu_configured": True}, status=status.HTTP_200_OK)


class SetupRagWizardView(APIView):
    """POST /api/system/setup-rag/ —— 向量检索可选配置（RAG-01/02）。

    键名严格对齐既有 `SettingKeys`（QDRANT_URL/QDRANT_API_KEY/EMBEDDING_*）；仅写"已提供且非空"字段。
    敏感项（QDRANT_API_KEY / EMBEDDING_API_KEY）`encrypt_value` + `is_encrypted=True`（与 bootstrap 一致），
    非敏感项明文。幂等 `update_or_create`。跳过由前端不调用本端点实现。
    """

    permission_classes = [IsSuperUser]

    async def post(self, request) -> Response:  # type: ignore[no-untyped-def]
        serializer = SetupRagSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        data = serializer.validated_data

        qdrant_url = data["qdrant_url"]
        qdrant_api_key = (data.get("qdrant_api_key") or "").strip()
        embedding_api_url = (data.get("embedding_api_url") or "").strip()
        embedding_api_key = (data.get("embedding_api_key") or "").strip()
        embedding_model = (data.get("embedding_model") or "").strip()
        embedding_dimension = data.get("embedding_dimension")

        # (key, value, is_encrypted, description) —— 仅非空项纳入写入
        plan: list[tuple[str, str, bool, str]] = [
            (SettingKeys.QDRANT_URL, qdrant_url, False, "Qdrant URL configured via setup wizard"),
        ]
        if qdrant_api_key:
            plan.append(
                (
                    SettingKeys.QDRANT_API_KEY,
                    encrypt_value(qdrant_api_key),
                    True,
                    "Qdrant API key configured via setup wizard",
                )
            )
        if embedding_api_url:
            plan.append(
                (
                    SettingKeys.EMBEDDING_API_URL,
                    embedding_api_url,
                    False,
                    "Embedding API URL configured via setup wizard",
                )
            )
        if embedding_api_key:
            plan.append(
                (
                    SettingKeys.EMBEDDING_API_KEY,
                    encrypt_value(embedding_api_key),
                    True,
                    "Embedding API key configured via setup wizard",
                )
            )
        if embedding_model:
            plan.append(
                (
                    SettingKeys.EMBEDDING_MODEL,
                    embedding_model,
                    False,
                    "Embedding model configured via setup wizard",
                )
            )
        if embedding_dimension is not None:
            plan.append(
                (
                    SettingKeys.EMBEDDING_DIMENSION,
                    str(embedding_dimension),
                    False,
                    "Embedding dimension configured via setup wizard",
                )
            )

        @sync_to_async
        def _write() -> None:
            for key, value, is_encrypted, description in plan:
                SystemSetting.objects.update_or_create(
                    key=key,
                    defaults={
                        "value": value,
                        "is_encrypted": is_encrypted,
                        "description": description,
                    },
                )

        await _write()
        written_keys = [key for key, *_ in plan]
        logger.info(
            "setup_rag_configured",
            user_id=str(request.user.id),
            written_keys=written_keys,
        )
        return Response(
            {"rag_configured": True, "written_keys": written_keys},
            status=status.HTTP_200_OK,
        )
