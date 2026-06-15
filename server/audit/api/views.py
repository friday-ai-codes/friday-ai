"""AuditEvent REST views —— 管理员只读 list + detail。"""

from __future__ import annotations

from rest_framework import status
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

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
