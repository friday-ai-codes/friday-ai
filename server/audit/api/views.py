"""审计查询/导出视图（AUDITUI-01 / AUDITUI-02）。

只读、superuser fail-closed：
- ``AuditEventListView`` / ``AuditEventDetailView``：adrf 异步 APIView，``IsSuperUser``。
- ``AuditEventExportView``：同步 APIView（StreamingHttpResponse 同步迭代 ORM），``IsSuperUser``。

绝不暴露任何 create/update/delete 入口——呼应 ``AuditEvent`` append-only 不可篡改语义。
"""

from __future__ import annotations

import csv
import json
from typing import Any

from adrf.views import APIView as AsyncAPIView
from asgiref.sync import sync_to_async
from django.http import StreamingHttpResponse
from django.shortcuts import aget_object_or_404
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import AuditEvent
from permissions.api_permissions import IsSuperUser

from .filters import apply_audit_filters, parse_pagination
from .serializers import AuditEventSerializer

# 导出行数硬上限（防滥用/内存峰值）；超限要求收紧过滤
EXPORT_MAX_ROWS = 50000

# CSV / JSON 导出列顺序（JSON 字段以 json.dumps 落单元格）
_EXPORT_COLUMNS = [
    "occurred_at",
    "actor_repr",
    "action",
    "target_type",
    "target_id",
    "target_repr",
    "source",
    "before",
    "after",
    "metadata",
]


class AuditEventListView(AsyncAPIView):
    """审计事件列表（过滤 + offset/limit 分页），仅 superuser。"""

    permission_classes = [IsSuperUser]

    async def get(self, request: Request) -> Response:
        qs = apply_audit_filters(request.query_params)
        limit, offset = parse_pagination(request.query_params)

        total = await qs.acount()
        items = [item async for item in qs[offset : offset + limit]]
        data = await sync_to_async(lambda: AuditEventSerializer(items, many=True).data)()
        return Response({"items": data, "total": total, "limit": limit, "offset": offset})


class AuditEventDetailView(AsyncAPIView):
    """审计事件详情（全字段 before/after 对比），仅 superuser。"""

    permission_classes = [IsSuperUser]

    async def get(self, request: Request, event_id: str) -> Response:
        event = await aget_object_or_404(AuditEvent, id=event_id)
        data = await sync_to_async(lambda: AuditEventSerializer(event).data)()
        return Response(data)


def _row_values(event: AuditEvent) -> list[Any]:
    return [
        event.occurred_at.isoformat() if event.occurred_at else "",
        event.actor_repr,
        event.action,
        event.target_type,
        event.target_id,
        event.target_repr,
        event.source,
        json.dumps(event.before, ensure_ascii=False),
        json.dumps(event.after, ensure_ascii=False),
        json.dumps(event.metadata, ensure_ascii=False),
    ]


class _Echo:
    """csv.writer 的伪文件对象：write 即返回该行字符串（流式生成器用）。"""

    def write(self, value: str) -> str:
        return value


class AuditEventExportView(APIView):
    """审计导出（CSV / JSON 流式），复用列表过滤，仅 superuser。

    同步视图：``StreamingHttpResponse`` 同步迭代 ORM queryset，避免 async 流式 ORM 复杂度。
    导出复用 ``apply_audit_filters`` 与列表完全一致；超 ``EXPORT_MAX_ROWS`` 返回 400 要求收紧过滤。
    """

    permission_classes = [IsSuperUser]

    def get(self, request: Request):
        qs = apply_audit_filters(request.query_params)
        # 用 fmt（非 DRF 保留 ``format`` query 参数，避免内容协商劫持路由）
        export_format = (request.query_params.get("fmt") or "csv").lower()

        total = qs.count()
        if total > EXPORT_MAX_ROWS:
            return Response(
                {
                    "detail": (
                        f"匹配 {total} 条超过导出上限 {EXPORT_MAX_ROWS}，请收紧过滤条件后重试"
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if export_format == "json":
            return self._stream_json(qs)
        return self._stream_csv(qs)

    def _stream_csv(self, qs) -> StreamingHttpResponse:
        writer = csv.writer(_Echo())

        def rows():
            yield writer.writerow(_EXPORT_COLUMNS)
            for event in qs.iterator():
                yield writer.writerow(_row_values(event))

        resp = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="audit_events.csv"'
        return resp

    def _stream_json(self, qs) -> StreamingHttpResponse:
        def chunks():
            yield '{"items":['
            first = True
            for event in qs.iterator():
                prefix = "" if first else ","
                first = False
                yield prefix + json.dumps(
                    AuditEventSerializer(event).data,
                    ensure_ascii=False,
                    default=str,
                )
            yield "]}"

        resp = StreamingHttpResponse(chunks(), content_type="application/json; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="audit_events.json"'
        return resp
