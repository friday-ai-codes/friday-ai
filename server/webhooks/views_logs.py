"""Logs views for webhook and work item logs."""
import json
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import WebhookLog, WorkItemLog
class WebhookLogListView(APIView):
 """List webhook logs with filtering and pagination."""
 def get(self, request):
 queryset = WebhookLog.objects.all
 # Filters
 project_id = request.query_params.get("project_id")
 if project_id:
 queryset = queryset.filter(project_id=project_id)
 event_type = request.query_params.get("event_type")
 if event_type:
 queryset = queryset.filter(event_type=event_type)
 log_status = request.query_params.get("status")
 if log_status:
 queryset = queryset.filter(status=log_status)
 start_date = request.query_params.get("start_date")
 if start_date:
 queryset = queryset.filter(created_at__gte=start_date)
 end_date = request.query_params.get("end_date")
 if end_date:
 queryset = queryset.filter(created_at__lte=end_date)
 # Pagination
 limit = int(request.query_params.get("limit", 50))
 offset = int(request.query_params.get("offset", 0))
 total = queryset.count
 logs = queryset.order_by("-created_at")[offset: offset + limit]
 items = [
 {
 "id": str(log.id),
 "event_uuid": log.event_uuid,
 "event_type": log.event_type,
 "project_key": log.project_key,
 "raw_request": log.raw_request,
 "status": log.status,
 "error_message": log.error_message,
 "project_id": str(log.project_id) if log.project_id else None,
 "created_at": log.created_at.isoformat,
 }
 for log in logs
 ]
 return Response({"items": items, "total": total})
class WebhookLogDetailView(APIView):
 """Get webhook log detail."""
 def get(self, request, log_id):
 try:
 log = WebhookLog.objects.get(id=log_id)
 except WebhookLog.DoesNotExist:
 return Response(
 {"detail": "日志不存在"},
 status=status.HTTP_404_NOT_FOUND,
 )
 # Parse raw JSON
 raw_request_parsed = None
 try:
 raw_request_parsed = json.loads(log.raw_request)
 except (json.JSONDecodeError, TypeError):
 pass
 return Response({
 "id": str(log.id),
 "event_uuid": log.event_uuid,
 "event_type": log.event_type,
 "project_key": log.project_key,
 "raw_request": log.raw_request,
 "status": log.status,
 "error_message": log.error_message,
 "project_id": str(log.project_id) if log.project_id else None,
 "created_at": log.created_at.isoformat,
 "raw_request_parsed": raw_request_parsed,
 })
class WorkItemLogListView(APIView):
 """List work item logs with filtering and pagination."""
 def get(self, request):
 queryset = WorkItemLog.objects.all
 # Filters
 project_id = request.query_params.get("project_id")
 if project_id:
 queryset = queryset.filter(project_id=project_id)
 task_id = request.query_params.get("task_id")
 if task_id:
 queryset = queryset.filter(task_id=task_id)
 work_item_id = request.query_params.get("work_item_id")
 if work_item_id:
 queryset = queryset.filter(work_item_id=work_item_id)
 start_date = request.query_params.get("start_date")
 if start_date:
 queryset = queryset.filter(created_at__gte=start_date)
 end_date = request.query_params.get("end_date")
 if end_date:
 queryset = queryset.filter(created_at__lte=end_date)
 # Pagination
 limit = int(request.query_params.get("limit", 50))
 offset = int(request.query_params.get("offset", 0))
 total = queryset.count
 logs = queryset.order_by("-created_at")[offset: offset + limit]
 items = [
 {
 "id": str(log.id),
 "work_item_id": log.work_item_id,
 "work_item_type": log.work_item_type,
 "project_key": log.project_key,
 "raw_response": log.raw_response,
 "project_id": str(log.project_id) if log.project_id else None,
 "task_id": str(log.task_id) if log.task_id else None,
 "created_at": log.created_at.isoformat,
 }
 for log in logs
 ]
 return Response({"items": items, "total": total})
class WorkItemLogDetailView(APIView):
 """Get work item log detail."""
 def get(self, request, log_id):
 try:
 log = WorkItemLog.objects.get(id=log_id)
 except WorkItemLog.DoesNotExist:
 return Response(
 {"detail": "日志不存在"},
 status=status.HTTP_404_NOT_FOUND,
 )
 # Parse raw JSON
 raw_response_parsed = None
 try:
 raw_response_parsed = json.loads(log.raw_response)
 except (json.JSONDecodeError, TypeError):
 pass
 return Response({
 "id": str(log.id),
 "work_item_id": log.work_item_id,
 "work_item_type": log.work_item_type,
 "project_key": log.project_key,
 "raw_response": log.raw_response,
 "project_id": str(log.project_id) if log.project_id else None,
 "task_id": str(log.task_id) if log.task_id else None,
 "created_at": log.created_at.isoformat,
 "raw_response_parsed": raw_response_parsed,
 })
