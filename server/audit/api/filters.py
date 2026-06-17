"""审计查询过滤共享逻辑（list / export 复用，AUDITUI-01/02）。

把 query_params → queryset 过滤收口到单一函数，保证列表与导出过滤语义完全一致。
过滤维度对齐 ``AuditEvent`` 模型索引（action / target_type+target_id / actor_id /
occurred_at），走索引高效。
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet
from django.utils.dateparse import parse_datetime

from audit.models import AuditEvent

# 列表分页上限（防一次拉爆）
MAX_LIMIT = 200
DEFAULT_LIMIT = 50


def apply_audit_filters(params: Any) -> QuerySet[AuditEvent]:
    """按 query_params 构造已过滤、按 -occurred_at 排序的 AuditEvent queryset。

    支持精确过滤：actor_id / action / target_type / target_id / source；
    时间范围：occurred_from / occurred_to（ISO8601）；
    自由文本 q：actor_repr / target_repr icontains。
    """
    qs = AuditEvent.objects.all()

    actor_id = params.get("actor_id")
    if actor_id:
        qs = qs.filter(actor_id=actor_id)

    action = params.get("action")
    if action:
        qs = qs.filter(action=action)

    target_type = params.get("target_type")
    if target_type:
        qs = qs.filter(target_type=target_type)

    target_id = params.get("target_id")
    if target_id:
        qs = qs.filter(target_id=target_id)

    source = params.get("source")
    if source:
        qs = qs.filter(source=source)

    occurred_from = params.get("occurred_from")
    if occurred_from:
        dt = parse_datetime(occurred_from)
        if dt is not None:
            qs = qs.filter(occurred_at__gte=dt)

    occurred_to = params.get("occurred_to")
    if occurred_to:
        dt = parse_datetime(occurred_to)
        if dt is not None:
            qs = qs.filter(occurred_at__lte=dt)

    q = params.get("q")
    if q:
        qs = qs.filter(Q(actor_repr__icontains=q) | Q(target_repr__icontains=q))

    return qs.order_by("-occurred_at")


def parse_pagination(params: Any) -> tuple[int, int]:
    """解析 limit/offset（limit 默认 50、上限 200；非法值降级到默认/0）。"""
    try:
        limit = int(params.get("limit", DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    if limit <= 0:
        limit = DEFAULT_LIMIT
    limit = min(limit, MAX_LIMIT)

    try:
        offset = int(params.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0

    return limit, offset
