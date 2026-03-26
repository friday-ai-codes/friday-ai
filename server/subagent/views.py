"""SubAgent API views."""
from __future__ import annotations
from typing import Any
from adrf.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from subagent.api.serializers import (
 ExecutionContextDetailSerializer,
 ExecutionContextListSerializer,
 ExecutionContextWriteSerializer,
)
from subagent.models import ExecutionContext
class ExecutionContextPagination(PageNumberPagination):
 page_size = 20
 page_size_query_param = "page_size"
 max_page_size = 100
class ExecutionContextViewSet(ModelViewSet):
 """ExecutionContext 完整 CRUD + 批量导出。"""
 queryset = ExecutionContext.objects.select_related("session").order_by("-created_at")
 permission_classes = [IsAuthenticated]
 pagination_class = ExecutionContextPagination
 def get_serializer_class(
 self,
 ) -> type[
 ExecutionContextDetailSerializer
 | ExecutionContextListSerializer
 | ExecutionContextWriteSerializer
 ]:
 if self.action == "retrieve":
 return ExecutionContextDetailSerializer
 if self.action in ("create", "update", "partial_update"):
 return ExecutionContextWriteSerializer
 return ExecutionContextListSerializer
 def get_queryset(self) -> Any:
 qs = super.get_queryset
 params = self.request.query_params
 if status:= params.get("status"):
 qs = qs.filter(session__status=status)
 if task_type:= params.get("task_type"):
 qs = qs.filter(session__task_type=task_type)
 if created_after:= params.get("created_after"):
 qs = qs.filter(created_at__gte=created_after)
 if created_before:= params.get("created_before"):
 qs = qs.filter(created_at__lte=created_before)
 if session_id:= params.get("session_id"):
 qs = qs.filter(session__session_id__icontains=session_id)
 if params.get("has_failure") == "true":
 qs = qs.exclude(session__failure_reason="")
 return qs
 @action(detail=False, methods=["post"])
 async def export(self, request: Request) -> Response:
 """批量导出执行上下文（JSON 格式）。"""
 ids = request.data.get("ids")
 filters = request.data.get("filters", {})
 qs = ExecutionContext.objects.select_related("session").order_by("-created_at")
 if ids:
 qs = qs.filter(id__in=ids)
 elif filters:
 if status:= filters.get("status"):
 qs = qs.filter(session__status=status)
 if task_type:= filters.get("task_type"):
 qs = qs.filter(session__task_type=task_type)
 if session_id:= filters.get("session_id"):
 qs = qs.filter(session__session_id__icontains=session_id)
 if filters.get("has_failure"):
 qs = qs.exclude(session__failure_reason="")
 qs = qs[:100]
 serializer = ExecutionContextDetailSerializer(qs, many=True)
 return Response(
 serializer.data,
 headers={
 "Content-Disposition": 'attachment; filename="execution_contexts_export.json"',
 },
 )
