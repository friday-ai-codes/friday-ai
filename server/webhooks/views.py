"""Webhooks app views."""
import json
import logging
from projects.models import Project
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import WebhookLog, WebhookLogStatus
logger = logging.getLogger(__name__)
# Store processed event UUIDs (in production, use Redis or database)
_processed_events = set
_MAX_PROCESSED_EVENTS = 10000
def is_event_processed(event_uuid: str) -> bool:
 """Check if event has been processed."""
 return event_uuid in _processed_events
def mark_event_processed(event_uuid: str) -> None:
 """Mark event as processed."""
 if len(_processed_events) >= _MAX_PROCESSED_EVENTS:
 # Simple cleanup strategy
 to_remove = list(_processed_events)[: _MAX_PROCESSED_EVENTS // 2]
 for uuid in to_remove:
 _processed_events.discard(uuid)
 _processed_events.add(event_uuid)
class FeishuWebhookView(APIView):
 """Handle Feishu webhook events."""
 permission_classes = [AllowAny]
 def post(self, request):
 raw_body = request.body.decode("utf-8")
 try:
 data = json.loads(raw_body)
 except json.JSONDecodeError:
 return Response(
 {"detail": "无效的 JSON 格式"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # Handle URL verification challenge
 if data.get("type") == "url_verification":
 return Response({"challenge": data.get("challenge", "")})
 # Parse webhook request
 header = data.get("header", {})
 payload = data.get("payload", {})
 if not header or not payload:
 WebhookLog.objects.create(
 raw_request=raw_body,
 event_type="",
 status=WebhookLogStatus.IGNORED,
 error_message="缺少 header 或 payload",
 )
 return Response({"status": "ignored", "reason": "缺少 header 或 payload"})
 event_uuid = header.get("uuid")
 event_type = header.get("event_type", "")
 # Idempotency check
 if event_uuid and is_event_processed(event_uuid):
 WebhookLog.objects.create(
 raw_request=raw_body,
 event_uuid=event_uuid,
 event_type=event_type,
 status=WebhookLogStatus.DUPLICATE,
 )
 return Response({"status": "duplicate", "uuid": event_uuid})
 # Get project
 project_key = payload.get("project_key") or payload.get("project_simple_name")
 if not project_key:
 WebhookLog.objects.create(
 raw_request=raw_body,
 event_uuid=event_uuid,
 event_type=event_type,
 status=WebhookLogStatus.IGNORED,
 error_message="缺少 project_key",
 )
 return Response({"status": "ignored", "reason": "缺少 project_key"})
 try:
 project = Project.objects.get(feishu_project_key=project_key)
 except Project.DoesNotExist:
 WebhookLog.objects.create(
 raw_request=raw_body,
 event_uuid=event_uuid,
 event_type=event_type,
 project_key=project_key,
 status=WebhookLogStatus.IGNORED,
 error_message=f"项目未配置: {project_key}",
 )
 return Response({"status": "ignored", "reason": f"项目未配置: {project_key}"})
 # Verify webhook token
 token = header.get("token", "")
 if project.feishu_webhook_token and token != project.feishu_webhook_token:
 WebhookLog.objects.create(
 raw_request=raw_body,
 event_uuid=event_uuid,
 event_type=event_type,
 project_key=project_key,
 project=project,
 status=WebhookLogStatus.ERROR,
 error_message="Token 验证失败",
 )
 return Response(
 {"detail": "Token 验证失败"},
 status=status.HTTP_401_UNAUTHORIZED,
 )
 # Mark as processed
 if event_uuid:
 mark_event_processed(event_uuid)
 # Log successful receipt
 WebhookLog.objects.create(
 raw_request=raw_body,
 event_uuid=event_uuid,
 event_type=event_type,
 project_key=project_key,
 project=project,
 status=WebhookLogStatus.ACCEPTED,
 )
 logger.info(f"Received Feishu webhook: {event_type} for project {project_key}")
 # TODO: Handle different event types
 # For now, just acknowledge receipt
 return Response(
 {
 "status": "accepted",
 "event_type": event_type,
 "uuid": event_uuid,
 }
 )
class GitHubWebhookView(APIView):
 """Handle GitHub webhook events."""
 permission_classes = [AllowAny]
 def post(self, request):
 raw_body = request.body.decode("utf-8")
 try:
 data = json.loads(raw_body)
 except json.JSONDecodeError:
 return Response(
 {"detail": "无效的 JSON 格式"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 action = data.get("action", "")
 pull_request = data.get("pull_request", {})
 # Handle PR merge
 if action == "closed" and pull_request.get("merged"):
 branch = pull_request.get("head", {}).get("ref", "")
 pr_url = pull_request.get("html_url", "")
 logger.info(f"PR merged: {branch} - {pr_url}")
 # TODO: Update task status to MERGED
 return Response({"status": "accepted"})
