"""入站 webhook 原始留痕查看 API（LOG-07）。

把 ``InboundWebhookEvent``（飞书 / Git push / 容器回调等入口脱敏后入库的原始留痕）
对运维超管暴露为可筛选列表 + 单条原始详情：

- ``WebhookEventListView``：倒序 + kind / verified / user_id / 时间段筛选 + 分页。
- ``WebhookEventDetailView``：返回单条已脱敏的 headers / raw_body（原始可回放）。

全部端点 ``IsSuperUser`` fail-closed（T-71-05-03，沿用 ``log_views`` 运维端点惯例）；
async ORM 经 ``sync_to_async`` 桥接（per STATE 异步约束）。落库内容写入前已强制脱敏，
此处只读直出，绝不重拼明文（T-71-05-01 / 02）。
"""

from __future__ import annotations

from typing import Any

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.request import Request
from rest_framework.response import Response

from permissions.api_permissions import IsSuperUser

from .models import InboundWebhookEvent
from .serializers import InboundWebhookEventSerializer

logger = structlog.get_logger(__name__)

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _parse_ts_bound(value: str) -> Any:
    """解析 ISO8601 时间界；解析失败返回 None（调用方忽略该界）。"""
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
    return parsed


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_bool(value: Any) -> bool | None:
    """把查询参数解析为三态布尔：true/1 → True，false/0 → False，其余 → None（忽略）。"""
    if value is None:
        return None
    raw = str(value).strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    return None


def _apply_filters(
    qs: QuerySet[InboundWebhookEvent], params: Any
) -> QuerySet[InboundWebhookEvent]:
    """按查询参数组合 AND 过滤 ``InboundWebhookEvent`` queryset。"""
    kind = (params.get("kind") or "").strip()
    if kind:
        qs = qs.filter(kind=kind)

    user_id = (str(params.get("user_id")) if params.get("user_id") else "").strip()
    if user_id:
        qs = qs.filter(user_id=user_id)

    verified = _parse_bool(params.get("verified"))
    if verified is not None:
        qs = qs.filter(verified=verified)

    start = _parse_ts_bound((params.get("start") or "").strip())
    if start is not None:
        qs = qs.filter(received_at__gte=start)
    end = _parse_ts_bound((params.get("end") or "").strip())
    if end is not None:
        qs = qs.filter(received_at__lte=end)

    return qs


class WebhookEventListView(APIView):
    """GET /api/system/webhooks/ — 入站 webhook 原始留痕列表（LOG-07）。

    查询参数（全部可选，组合 AND）：``kind`` / ``user_id`` / ``verified`` 精确筛选；
    ``start`` / ``end`` ISO8601 时间段；``limit``（默认 100，最大 500）+ ``offset`` 分页。
    返回 ``{"items": [...], "total": <count>}``，倒序（received_at desc）。
    """

    permission_classes = [IsSuperUser]

    async def get(self, request: Request) -> Response:
        params = request.query_params
        limit = max(1, min(_coerce_int(params.get("limit"), _DEFAULT_LIMIT), _MAX_LIMIT))
        offset = max(0, _coerce_int(params.get("offset"), 0))

        items, total = await sync_to_async(self._query, thread_sensitive=True)(
            params, limit, offset
        )
        # 高频运维轮询：记 sampling 类，避免污染 caller 调用统计。
        logger.info(
            "webhook_events_queried",
            category="sampling",
            component="webhook_events",
            total=total,
            returned=len(items),
        )
        return Response({"items": items, "total": total})

    @staticmethod
    def _query(params: Any, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        qs = _apply_filters(
            InboundWebhookEvent.objects.all().order_by("-received_at"), params
        )
        total = qs.count()
        rows = list(qs[offset : offset + limit])
        items = InboundWebhookEventSerializer(rows, many=True).data
        return items, total


class WebhookEventDetailView(APIView):
    """GET /api/system/webhooks/<event_id>/ — 单条入站 webhook 原始详情（已脱敏）。"""

    permission_classes = [IsSuperUser]

    async def get(self, request: Request, event_id: int) -> Response:
        data = await sync_to_async(self._get, thread_sensitive=True)(event_id)
        if data is None:
            return Response({"detail": "未找到该 webhook 留痕"}, status=404)
        return Response(data)

    @staticmethod
    def _get(event_id: int) -> dict[str, Any] | None:
        obj = InboundWebhookEvent.objects.filter(id=event_id).first()
        if obj is None:
            return None
        return InboundWebhookEventSerializer(obj).data
