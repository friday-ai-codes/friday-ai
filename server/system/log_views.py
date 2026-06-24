"""系统日志中心查询 / 清理 API（LOG-01 查询 + LOG-03 用户筛选 + LOG-08 清理）。

把"内存环形缓冲版" ``SystemLogsView`` 升级为基于 ``SystemLogEntry`` 的持久化查询：

- ``SystemLogQueryView``：时间倒序 + 组件/级别/用户/来源/关键词/时间段筛选与全文
  搜索（PG/SQLite 均用 ``icontains``，量级低不引专用全文索引，SQLite dev 天然降级）；
  顶部返回队列四计数（队列 x/5000 · 写入 · 丢弃 · 失败，``log_sink.snapshot_counters()``）。
- ``SystemLogClearView``：按同款筛选条件批量删除；无任何条件时必须显式
  ``confirm_all=true`` 才允许清空全表（防误清）。

全部端点 ``IsSuperUser`` fail-closed（沿用 ``observability_views`` 运维端点惯例）。
async ORM 经 ``sync_to_async`` 桥接（per STATE 异步约束）。查询/清理事件经 structlog
打点：查询为高频轮询记 ``category="sampling"``（避免污染调用类统计），清理为可归因
写操作记 ``category="caller"``。
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

from . import log_sink
from .models import SystemLogEntry
from .serializers import SystemLogEntrySerializer

logger = structlog.get_logger(__name__)

# 单次返回上限（防止超大返回拖慢日志页首屏）。
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500

# 与 log_sink._normalize_level 一致的级别归一（WARNING→warn），保证筛选命中落库值。
_LEVEL_ALIASES = {"warning": "warn"}


def _normalize_level(value: str) -> str:
    """级别归一小写；``WARNING`` → ``warn``（与落库 ``_normalize_level`` 对齐）。"""
    raw = (value or "").strip().lower()
    return _LEVEL_ALIASES.get(raw, raw)


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


def _coerce_int(value: Any, default: int) -> int:
    """容错转 int；失败回默认。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_filters(getter: Any) -> dict[str, Any]:
    """从 ``query_params`` / ``request.data`` 抽取筛选条件（全部可选）。

    ``getter`` 为 ``.get(key, default)`` 风格的访问器（QueryDict 或 dict 均可）。
    返回归一化后的筛选字典，供 ``_apply_filters`` 复用（查询与清理同款语义）。
    """
    return {
        "component": (getter.get("component") or "").strip(),
        "level": _normalize_level(getter.get("level") or ""),
        "user_id": (str(getter.get("user_id")) if getter.get("user_id") else "").strip(),
        "source": (getter.get("source") or "").strip(),
        "start": _parse_ts_bound((getter.get("start") or "").strip()),
        "end": _parse_ts_bound((getter.get("end") or "").strip()),
        "keyword": (getter.get("keyword") or "").strip(),
    }


def _has_any_filter(filters: dict[str, Any]) -> bool:
    """是否提供了至少一个有效筛选条件（用于 clear 防误清判定）。"""
    return any(filters.get(k) for k in ("component", "level", "user_id", "source", "start", "end", "keyword"))


def _apply_filters(qs: QuerySet[SystemLogEntry], filters: dict[str, Any]) -> QuerySet[SystemLogEntry]:
    """按筛选字典组合 AND 过滤 ``SystemLogEntry`` queryset（查询/清理共用）。

    - component / level / user_id / source 精确匹配；
    - start / end 映射 ``ts__gte`` / ``ts__lte``（None 忽略该界）；
    - keyword 全文：``message__icontains``（PG/SQLite 一致降级，量级低不引专用索引）。
    """
    if filters.get("component"):
        qs = qs.filter(component=filters["component"])
    if filters.get("level"):
        qs = qs.filter(level=filters["level"])
    if filters.get("user_id"):
        qs = qs.filter(user_id=filters["user_id"])
    if filters.get("source"):
        qs = qs.filter(source=filters["source"])
    if filters.get("start") is not None:
        qs = qs.filter(ts__gte=filters["start"])
    if filters.get("end") is not None:
        qs = qs.filter(ts__lte=filters["end"])
    if filters.get("keyword"):
        qs = qs.filter(message__icontains=filters["keyword"])
    return qs


class SystemLogQueryView(APIView):
    """GET /api/system/logs/ — 基于 ``SystemLogEntry`` 的日志查询（LOG-01 / LOG-03）。

    查询参数（全部可选，组合 AND）：
    - ``component`` / ``level`` / ``user_id`` / ``source``：精确筛选；
    - ``start`` / ``end``：ISO8601 时间段（``ts__gte`` / ``ts__lte``，解析失败忽略该界）；
    - ``keyword``：全文搜索（``message__icontains``，SQLite 天然降级）；
    - ``limit``（默认 100，最大 500）+ ``offset``（分页）。

    向后兼容旧 ``SystemLogsView`` 的 ``limit`` / ``level`` 参数。返回
    ``{"items": [...], "total": <count>, "counters": <queue counters>}``——
    顶部 counters 即队列(x/5000)/写入/丢弃/失败（UI-04 顶部计数前置，Phase 73 消费）。
    """

    permission_classes = [IsSuperUser]

    async def get(self, request: Request) -> Response:
        params = request.query_params
        filters = _extract_filters(params)
        limit = max(1, min(_coerce_int(params.get("limit"), _DEFAULT_LIMIT), _MAX_LIMIT))
        offset = max(0, _coerce_int(params.get("offset"), 0))

        items, total = await sync_to_async(self._query, thread_sensitive=True)(
            filters, limit, offset
        )
        # 高频轮询：记 sampling 类，避免污染 caller 调用统计（per 71-04 观测要求）。
        logger.info(
            "system_logs_queried",
            category="sampling",
            component="system_logs",
            total=total,
            returned=len(items),
        )
        return Response(
            {
                "items": items,
                "total": total,
                "counters": log_sink.snapshot_counters(),
            }
        )

    @staticmethod
    def _query(
        filters: dict[str, Any], limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        """在同步线程内一次性完成 count + 分页取数 + 序列化。"""
        qs = _apply_filters(SystemLogEntry.objects.all().order_by("-ts"), filters)
        total = qs.count()
        rows = list(qs[offset : offset + limit])
        items = SystemLogEntrySerializer(rows, many=True).data
        return items, total


class SystemLogClearView(APIView):
    """POST /api/system/logs/clear/ — 按条件批量清理日志（LOG-08）。

    body 同 ``SystemLogQueryView`` 的筛选条件（component/level/user_id/source/
    start/end/keyword）。**防误清**：未提供任何筛选条件时必须显式
    ``confirm_all=true`` 才允许清空全表，否则 400。返回 ``{"deleted": <count>}``。

    审计：经既有 ``AuditService.aemit`` 记一条 caller 类删除操作（best-effort，
    审计入口已强制脱敏），失败绝不反噬清理主流程。
    """

    permission_classes = [IsSuperUser]

    async def post(self, request: Request) -> Response:
        data = request.data if isinstance(request.data, dict) else {}
        filters = _extract_filters(data)
        confirm_all = bool(data.get("confirm_all"))

        if not _has_any_filter(filters) and not confirm_all:
            return Response(
                {"detail": "未提供任何筛选条件；如需清空全部日志请显式传 confirm_all=true。"},
                status=400,
            )

        deleted = await sync_to_async(self._delete, thread_sensitive=True)(filters)

        logger.info(
            "system_logs_cleared",
            category="caller",
            component="system_logs",
            source="rest",
            deleted=deleted,
            confirm_all=confirm_all,
        )
        await self._audit(request, filters, confirm_all, deleted)
        return Response({"deleted": deleted})

    @staticmethod
    def _delete(filters: dict[str, Any]) -> int:
        """按筛选删除并返回删除行数（同步线程内执行）。"""
        qs = _apply_filters(SystemLogEntry.objects.all(), filters)
        deleted, _ = qs.delete()
        return deleted

    @staticmethod
    async def _audit(
        request: Request, filters: dict[str, Any], confirm_all: bool, deleted: int
    ) -> None:
        """best-effort 审计留痕（AuditService 入口已强制脱敏）；失败绝不反噬。"""
        try:
            from audit.services import AuditService

            await AuditService.aemit(
                action="system_logs.clear",
                actor=getattr(request, "user", None),
                target_type="SystemLogEntry",
                source="rest",
                metadata={
                    "deleted": deleted,
                    "confirm_all": confirm_all,
                    "filters": {k: str(v) for k, v in filters.items() if v},
                },
            )
        except Exception:  # noqa: BLE001 — 审计 best-effort，绝不反噬清理主流程
            pass
