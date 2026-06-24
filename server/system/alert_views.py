"""系统告警规则 CRUD + 告警事件查询 API（ALERT-01/02 运维入口）。

镜像 ``log_views`` 范式：adrf async ``APIView`` + ``IsSuperUser`` fail-closed +
``sync_to_async`` 桥接 ORM（per STATE 异步约束）+ ``_extract/_apply_filters`` 筛选。

- ``SystemAlertRuleListCreateView``：GET 列表（可选 ?enabled 过滤）+ POST 创建。
- ``SystemAlertRuleDetailView``：单条 GET / PATCH / DELETE。
- ``AlertEventListView``：告警事件查询（severity/status/rule_id/时间段筛选 + 分页倒序），
  列对齐 REFERENCE-UI §1.4。

结构化打点：规则写操作为可归因调用记 ``category="caller"``；事件查询为高频轮询记
``category="sampling"``（避免污染 caller 调用统计）。``component="alerting"``。
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

from .alert_serializers import (
    AlertEventSerializer,
    SystemAlertRuleSerializer,
    SystemAlertRuleWriteSerializer,
)
from .models import AlertEvent, SystemAlertRule

logger = structlog.get_logger(__name__)

# 事件查询单次返回上限（防止超大返回拖慢告警事件页首屏）。
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _coerce_int(value: Any, default: int) -> int:
    """容错转 int；失败回默认。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_ts_bound(value: str) -> Any:
    """解析 ISO8601 时间界；解析失败返回 None（调用方忽略该界）。

    naive datetime 按默认时区补全为 aware（与 USE_TZ=True 项目惯例一致）。
    """
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
    return parsed


def _extract_event_filters(getter: Any) -> dict[str, Any]:
    """从 ``query_params`` 抽取告警事件筛选条件（全部可选，组合 AND）。"""
    return {
        "severity": (getter.get("severity") or "").strip(),
        "status": (getter.get("status") or "").strip(),
        "rule_id": (str(getter.get("rule_id")) if getter.get("rule_id") else "").strip(),
        "start": _parse_ts_bound((getter.get("start") or "").strip()),
        "end": _parse_ts_bound((getter.get("end") or "").strip()),
    }


def _apply_event_filters(
    qs: QuerySet[AlertEvent], filters: dict[str, Any]
) -> QuerySet[AlertEvent]:
    """按筛选字典组合 AND 过滤 ``AlertEvent`` queryset。

    - severity / status / rule_id 精确匹配；
    - start / end 映射 ``started_at__gte`` / ``started_at__lte``（None 忽略该界）。
    """
    if filters.get("severity"):
        qs = qs.filter(severity=filters["severity"])
    if filters.get("status"):
        qs = qs.filter(status=filters["status"])
    if filters.get("rule_id"):
        qs = qs.filter(rule_id=filters["rule_id"])
    if filters.get("start") is not None:
        qs = qs.filter(started_at__gte=filters["start"])
    if filters.get("end") is not None:
        qs = qs.filter(started_at__lte=filters["end"])
    return qs


class SystemAlertRuleListCreateView(APIView):
    """GET /api/system/alerts/rules/ — 列表（可选 ?enabled=true/false）；POST 创建。"""

    permission_classes = [IsSuperUser]

    async def get(self, request: Request) -> Response:
        enabled_param = (request.query_params.get("enabled") or "").strip().lower()
        items, total = await sync_to_async(self._list, thread_sensitive=True)(enabled_param)
        logger.info(
            "alert_rules_listed",
            category="caller",
            component="alerting",
            source="rest",
            total=total,
        )
        return Response({"items": items, "total": total})

    @staticmethod
    def _list(enabled_param: str) -> tuple[list[dict[str, Any]], int]:
        qs = SystemAlertRule.objects.all().order_by("-created_at")
        if enabled_param in ("true", "1", "yes", "on"):
            qs = qs.filter(enabled=True)
        elif enabled_param in ("false", "0", "no", "off"):
            qs = qs.filter(enabled=False)
        rows = list(qs)
        return SystemAlertRuleSerializer(rows, many=True).data, len(rows)

    async def post(self, request: Request) -> Response:
        serializer = SystemAlertRuleWriteSerializer(data=request.data)
        await sync_to_async(serializer.is_valid, thread_sensitive=True)(raise_exception=True)
        instance = await sync_to_async(serializer.save, thread_sensitive=True)()
        data = await sync_to_async(lambda: SystemAlertRuleSerializer(instance).data)()
        logger.info(
            "alert_rule_created",
            category="caller",
            component="alerting",
            source="rest",
            rule_id=instance.id,
            metric=instance.metric,
            severity=instance.severity,
        )
        return Response(data, status=201)


class SystemAlertRuleDetailView(APIView):
    """GET/PATCH/DELETE /api/system/alerts/rules/<rule_id>/ — 单条 CRUD。"""

    permission_classes = [IsSuperUser]

    async def get(self, request: Request, rule_id: int) -> Response:
        result = await sync_to_async(self._retrieve, thread_sensitive=True)(rule_id)
        if result is None:
            return Response({"detail": "告警规则不存在"}, status=404)
        return Response(result)

    @staticmethod
    def _retrieve(rule_id: int) -> dict[str, Any] | None:
        instance = SystemAlertRule.objects.filter(id=rule_id).first()
        if instance is None:
            return None
        return SystemAlertRuleSerializer(instance).data

    async def patch(self, request: Request, rule_id: int) -> Response:
        result = await sync_to_async(self._update, thread_sensitive=True)(rule_id, request.data)
        if result is None:
            return Response({"detail": "告警规则不存在"}, status=404)
        logger.info(
            "alert_rule_updated",
            category="caller",
            component="alerting",
            source="rest",
            rule_id=rule_id,
        )
        return Response(result)

    @staticmethod
    def _update(rule_id: int, data: Any) -> dict[str, Any] | None:
        instance = SystemAlertRule.objects.filter(id=rule_id).first()
        if instance is None:
            return None
        serializer = SystemAlertRuleWriteSerializer(instance, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        return SystemAlertRuleSerializer(instance).data

    async def delete(self, request: Request, rule_id: int) -> Response:
        deleted = await sync_to_async(self._delete, thread_sensitive=True)(rule_id)
        if not deleted:
            return Response({"detail": "告警规则不存在"}, status=404)
        logger.info(
            "alert_rule_deleted",
            category="caller",
            component="alerting",
            source="rest",
            rule_id=rule_id,
        )
        return Response(status=204)

    @staticmethod
    def _delete(rule_id: int) -> int:
        deleted, _ = SystemAlertRule.objects.filter(id=rule_id).delete()
        return deleted


class AlertEventListView(APIView):
    """GET /api/system/alerts/events/ — 告警事件查询（ALERT-02）。

    查询参数（全部可选，组合 AND）：
    - ``severity``(P0/P1/P2) / ``status``(firing/resolved) / ``rule_id``：精确筛选；
    - ``start`` / ``end``：ISO8601 时间段（``started_at__gte`` / ``started_at__lte``）；
    - ``limit``（默认 100，最大 500）+ ``offset``（分页）。

    返回 ``{"items": [...], "total": <count>}``，倒序 ``-started_at``，列对齐
    REFERENCE-UI §1.4。
    """

    permission_classes = [IsSuperUser]

    async def get(self, request: Request) -> Response:
        params = request.query_params
        filters = _extract_event_filters(params)
        limit = max(1, min(_coerce_int(params.get("limit"), _DEFAULT_LIMIT), _MAX_LIMIT))
        offset = max(0, _coerce_int(params.get("offset"), 0))

        items, total = await sync_to_async(self._query, thread_sensitive=True)(
            filters, limit, offset
        )
        # 高频轮询：记 sampling 类，避免污染 caller 调用统计。
        logger.info(
            "alert_events_queried",
            category="sampling",
            component="alerting",
            total=total,
            returned=len(items),
        )
        return Response({"items": items, "total": total})

    @staticmethod
    def _query(
        filters: dict[str, Any], limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        """在同步线程内一次性完成 count + 分页取数 + 序列化。"""
        qs = _apply_event_filters(AlertEvent.objects.all().order_by("-started_at"), filters)
        total = qs.count()
        rows = list(qs[offset : offset + limit])
        items = AlertEventSerializer(rows, many=True).data
        return items, total
