"""系统健康检查聚合接口。

汇总 Friday 各外部依赖的连接状态，供前端 header 状态面板展示。
单个依赖检测失败不会影响其它依赖的结果。
"""

from __future__ import annotations

import asyncio
import socket
import time
from typing import Any, TypedDict
from urllib.parse import urlparse

import httpx
import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import connections
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.encryption import decrypt_value
from services.qdrant_service import QdrantService
from system.models import SettingKeys, SystemSetting

logger = structlog.get_logger(__name__)


# 单个依赖检测超时（秒）。保持较小值以避免前端长时间等待。
CHECK_TIMEOUT_SECONDS = 3.0


class ServiceStatus(TypedDict, total=False):
    name: str
    label: str
    status: str  # healthy | unhealthy | not_configured
    message: str
    latency_ms: int


async def _check_database() -> ServiceStatus:
    """验证默认数据库连接可用。"""

    def _ping() -> None:
        connection = connections["default"]
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

    start = time.perf_counter()
    try:
        await asyncio.wait_for(
            sync_to_async(_ping, thread_sensitive=True)(),
            timeout=CHECK_TIMEOUT_SECONDS,
        )
        return {
            "name": "database",
            "label": "数据库",
            "status": "healthy",
            "latency_ms": int((time.perf_counter() - start) * 1000),
        }
    except Exception as exc:
        logger.warning("system_health_database_failed", error=str(exc))
        return {
            "name": "database",
            "label": "数据库",
            "status": "unhealthy",
            "message": str(exc),
        }


async def _check_redis() -> ServiceStatus:
    """验证 Redis 可达（仅在启用 Redis Channel Layer 时）。

    使用 TCP socket 连接确认端口可达，避免引入额外依赖。
    """
    use_redis: bool = getattr(settings, "USE_REDIS_CHANNEL_LAYER", False)
    redis_url: str = getattr(settings, "REDIS_CHANNEL_LAYER_URL", "")

    if not use_redis:
        return {
            "name": "redis",
            "label": "Redis",
            "status": "not_configured",
            "message": "未启用 Redis Channel Layer（使用内存层）",
        }

    parsed = urlparse(redis_url or "redis://127.0.0.1:6379/0")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 6379

    def _tcp_ping() -> None:
        with socket.create_connection((host, port), timeout=CHECK_TIMEOUT_SECONDS):
            pass

    start = time.perf_counter()
    try:
        await asyncio.wait_for(
            sync_to_async(_tcp_ping, thread_sensitive=False)(),
            timeout=CHECK_TIMEOUT_SECONDS,
        )
        return {
            "name": "redis",
            "label": "Redis",
            "status": "healthy",
            "message": f"{host}:{port}",
            "latency_ms": int((time.perf_counter() - start) * 1000),
        }
    except Exception as exc:
        logger.warning(
            "system_health_redis_failed", host=host, port=port, error=str(exc)
        )
        return {
            "name": "redis",
            "label": "Redis",
            "status": "unhealthy",
            "message": f"{host}:{port} — {exc}",
        }


async def _get_setting_value(key: str) -> str | None:
    try:
        setting = await SystemSetting.objects.filter(key=key).afirst()
    except Exception:
        return None
    if setting is None or not setting.value:
        return None
    if setting.is_encrypted:
        try:
            return decrypt_value(setting.value)
        except Exception:
            return None
    return setting.value


async def _check_feishu() -> ServiceStatus:
    """验证飞书 IM 配置可拿到 tenant_access_token。"""
    app_id = await _get_setting_value(SettingKeys.FEISHU_APP_ID)
    app_secret = await _get_setting_value(SettingKeys.FEISHU_APP_SECRET)

    if not app_id or not app_secret:
        return {
            "name": "feishu",
            "label": "飞书",
            "status": "not_configured",
            "message": "未配置 App ID / App Secret",
        }

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            data = resp.json()
    except Exception as exc:
        logger.warning("system_health_feishu_request_failed", error=str(exc))
        return {
            "name": "feishu",
            "label": "飞书",
            "status": "unhealthy",
            "message": f"请求失败: {exc}",
        }

    if data.get("code") == 0:
        return {
            "name": "feishu",
            "label": "飞书",
            "status": "healthy",
            "latency_ms": int((time.perf_counter() - start) * 1000),
        }

    return {
        "name": "feishu",
        "label": "飞书",
        "status": "unhealthy",
        "message": data.get("msg") or f"code={data.get('code')}",
    }


async def _check_qdrant() -> ServiceStatus:
    """复用现有 QdrantService.health_check。"""
    url_setting = await SystemSetting.objects.filter(key=SettingKeys.QDRANT_URL).afirst()
    if url_setting is None or not url_setting.value:
        return {
            "name": "qdrant",
            "label": "Qdrant",
            "status": "not_configured",
            "message": "未配置 Qdrant URL",
        }

    start = time.perf_counter()
    try:
        # 只做轻量 liveness 探测（GET /healthz），不枚举 collection——后者在
        # 一仓一 collection 时会拖垮 Qdrant 并让健康检查自身超时。
        result: dict[str, Any] = await asyncio.wait_for(
            sync_to_async(QdrantService.ping_liveness, thread_sensitive=False)(),
            timeout=CHECK_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        # asyncio.TimeoutError 的 str() 为空，补一个可读信息避免前端 message 空白
        message = str(exc) or f"{type(exc).__name__}（探测超时）"
        logger.warning("system_health_qdrant_failed", error=message)
        return {
            "name": "qdrant",
            "label": "Qdrant",
            "status": "unhealthy",
            "message": message,
        }

    if result.get("status") == "healthy":
        return {
            "name": "qdrant",
            "label": "Qdrant",
            "status": "healthy",
            "message": "",
            "latency_ms": int((time.perf_counter() - start) * 1000),
        }

    return {
        "name": "qdrant",
        "label": "Qdrant",
        "status": "unhealthy",
        "message": str(result.get("error") or "unknown"),
    }


def _overall_status(services: list[ServiceStatus]) -> str:
    """根据各依赖状态汇总整体状态。

    只有"正常 / 异常"两种业务态——未配置视为正常。
    例如 Redis 未启用 Channel Layer 属于预期配置，不算连接异常。

    - 任一 unhealthy → unhealthy
    - 其余（healthy / not_configured）→ healthy
    """
    if any(s.get("status") == "unhealthy" for s in services):
        return "unhealthy"
    return "healthy"


class SystemHealthView(APIView):
    """聚合返回系统各依赖的连接状态。

    GET /api/system/health/
    Response: {
        "overall": "healthy" | "degraded" | "unhealthy",
        "checked_at": "<iso8601>",
        "services": [ServiceStatus, ...]
    }
    """

    permission_classes = [IsAuthenticated]

    # 健康结果短缓存（秒）：前端 header 多个标签页/用户高频轮询，逐次打全部依赖
    # （含飞书外网请求）既慢又浪费。共享 Redis 缓存几秒，命中即直接返回。
    _CACHE_KEY = "system:health:v1"
    _CACHE_TTL_S = 5

    async def get(self, request: Any) -> Response:
        from django.core.cache import cache

        cached = await cache.aget(self._CACHE_KEY)
        if cached is not None:
            return Response(cached)

        services = await asyncio.gather(
            _check_database(),
            _check_redis(),
            _check_feishu(),
            _check_qdrant(),
            return_exceptions=False,
        )
        services_list: list[ServiceStatus] = list(services)

        payload = {
            "overall": _overall_status(services_list),
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "services": services_list,
        }
        await cache.aset(self._CACHE_KEY, payload, self._CACHE_TTL_S)
        return Response(payload)
