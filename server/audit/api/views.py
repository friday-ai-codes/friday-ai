"""AuditEvent REST views —— 管理员只读 list + detail + export。"""

from __future__ import annotations

import csv
import json

from django.http import HttpResponse, StreamingHttpResponse
from rest_framework import status
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import AuditEvent
from permissions.api_permissions import IsSuperUser

from .serializers import AuditEventSerializer


class _AuditPagination(PageNumberPagination):
    """审计事件分页器 —— 默认每页 20 条。"""

    page_size = 20


class AuditEventListView(ListAPIView):
    """管理员审计事件列表 —— 仅限 is_superuser。

    支持 query-param 过滤（action / source / target_type / actor）、
    search（actor_display / action / target_id）、
    排序（timestamp / action，默认 -timestamp）。
    """

    serializer_class = AuditEventSerializer
    permission_classes = [IsAuthenticated, IsSuperUser]
    pagination_class = _AuditPagination
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["actor_display", "action", "target_id"]
    ordering_fields = ["timestamp", "action"]
    ordering = ["-timestamp"]

    _filter_fields = ("action", "source", "target_type", "actor")

    def get_queryset(self):
        qs = AuditEvent.objects.all()
        for field in self._filter_fields:
            value = self.request.query_params.get(field)
            if value:
                qs = qs.filter(**{field: value})
        return qs


class AuditEventDetailView(RetrieveAPIView):
    """管理员审计事件详情 —— 仅限 is_superuser，显式阻止 mutation 方法。"""

    serializer_class = AuditEventSerializer
    permission_classes = [IsAuthenticated, IsSuperUser]
    queryset = AuditEvent.objects.all()

    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def destroy(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)


def _apply_filters(qs, request: Request):
    """从请求参数构建过滤 queryset（纯函数，便于 list 和 export 共用）。"""
    for field in ("action", "source", "target_type", "actor"):
        value = request.query_params.get(field)
        if value:
            qs = qs.filter(**{field: value})
    start_date = request.query_params.get("start_date")
    end_date = request.query_params.get("end_date")
    if start_date:
        qs = qs.filter(timestamp__date__gte=start_date)
    if end_date:
        qs = qs.filter(timestamp__date__lte=end_date)
    return qs


class _Echo:
    """csv.writer 所需的伪文件对象（用于 StreamingHttpResponse）。"""

    def write(self, value: str) -> str:
        return value


class AuditEventExportView(APIView):
    """GET /api/audit-events/export/ —— 导出 CSV 或 JSON，尊重当前过滤条件。"""

    permission_classes = [IsAuthenticated, IsSuperUser]

    def get(self, request: Request) -> HttpResponse:
        export_format = request.query_params.get("format", "json").lower()
        qs = _apply_filters(AuditEvent.objects.all(), request)

        if export_format == "csv":
            return self._export_csv(qs)
        return self._export_json(qs)

    @staticmethod
    def _export_csv(qs) -> StreamingHttpResponse:
        """流式导出 CSV。"""

        def generate_rows():
            yield [
                "id", "timestamp", "actor_display", "actor_type", "action",
                "target_type", "target_id", "source", "before", "after", "ip_address",
            ]
            for event in qs.iterator():
                yield [
                    str(event.id),
                    event.timestamp.isoformat() if event.timestamp else "",
                    event.actor_display,
                    event.actor_type,
                    event.action,
                    event.target_type,
                    event.target_id,
                    event.source,
                    json.dumps(event.before, ensure_ascii=False) if event.before else "",
                    json.dumps(event.after, ensure_ascii=False) if event.after else "",
                    event.ip_address or "",
                ]

        writer = csv.writer(_Echo())
        response = StreamingHttpResponse(
            (writer.writerow(row) for row in generate_rows()),
            content_type="text/csv; charset=utf-8",
        )
        response["Content-Disposition"] = 'attachment; filename="audit_events.csv"'
        return response

    @staticmethod
    def _export_json(qs) -> HttpResponse:
        """导出 JSON 数组。"""
        events = list(qs.values(
            "id", "timestamp", "actor_display", "actor_type", "action",
            "target_type", "target_id", "before", "after", "source", "ip_address",
        ))
        for event in events:
            event["id"] = str(event["id"])
            if event["timestamp"]:
                event["timestamp"] = event["timestamp"].isoformat()

        response = HttpResponse(
            json.dumps(events, ensure_ascii=False, default=str),
            content_type="application/json; charset=utf-8",
        )
        response["Content-Disposition"] = 'attachment; filename="audit_events.json"'
        return response
