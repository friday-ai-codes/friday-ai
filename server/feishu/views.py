"""Feishu views: Webhook handling, config management, and logs."""
import json
import logging
import structlog
from asgiref.sync import async_to_sync
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from common.encryption import decrypt_value, encrypt_value
from projects.models import Project, generate_webhook_token
from .client import FeishuClient, create_feishu_client_for_project, verify_webhook_token
from .models import KeyFields, TriggerLog, TriggerLogStatus
from .serializers import (
 FeishuConfigCreateSerializer,
 FeishuConfigSerializer,
 TriggerLogDetailSerializer,
 TriggerLogSerializer,
 WebhookTokenSerializer,
 WebhookTokenUpdateSerializer,
)
from .workflow_bridge import FeishuWorkflowBridge
logger = logging.getLogger(__name__)
struct_logger = structlog.get_logger
# 幂等处理
_processed_events = set
_MAX_PROCESSED_EVENTS = 10000
def is_event_processed(event_uuid: str) -> bool:
 return event_uuid in _processed_events
def mark_event_processed(event_uuid: str) -> None:
 if len(_processed_events) >= _MAX_PROCESSED_EVENTS:
 to_remove = list(_processed_events)[: _MAX_PROCESSED_EVENTS // 2]
 for uuid in to_remove:
 _processed_events.discard(uuid)
 _processed_events.add(event_uuid)
# ============ Webhook View ============
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
 TriggerLog.objects.create(
 webhook_raw_request=raw_body,
 event_type="",
 status=TriggerLogStatus.IGNORED,
 error_message="缺少 header 或 payload",
 )
 return Response({"status": "ignored", "reason": "缺少 header 或 payload"})
 event_uuid = header.get("uuid")
 event_type = header.get("event_type", "")
 # Idempotency check
 if event_uuid and is_event_processed(event_uuid):
 TriggerLog.objects.create(
 webhook_raw_request=raw_body,
 event_uuid=event_uuid,
 event_type=event_type,
 status=TriggerLogStatus.DUPLICATE,
 )
 return Response({"status": "duplicate", "uuid": event_uuid})
 # Get project
 project_key = payload.get("project_key") or payload.get("project_simple_name")
 if not project_key:
 TriggerLog.objects.create(
 webhook_raw_request=raw_body,
 event_uuid=event_uuid,
 event_type=event_type,
 status=TriggerLogStatus.IGNORED,
 error_message="缺少 project_key",
 )
 return Response({"status": "ignored", "reason": "缺少 project_key"})
 try:
 project = Project.objects.prefetch_related("repositories").get(
 feishu_project_key=project_key
 )
 except Project.DoesNotExist:
 TriggerLog.objects.create(
 webhook_raw_request=raw_body,
 event_uuid=event_uuid,
 event_type=event_type,
 project_key=project_key,
 status=TriggerLogStatus.IGNORED,
 error_message=f"项目未配置: {project_key}",
 )
 return Response({"status": "ignored", "reason": f"项目未配置: {project_key}"})
 # Verify webhook token
 token = header.get("token", "")
 if project.feishu_webhook_token and not verify_webhook_token(
 token, project.feishu_webhook_token
 ):
 TriggerLog.objects.create(
 webhook_raw_request=raw_body,
 event_uuid=event_uuid,
 event_type=event_type,
 project_key=project_key,
 project=project,
 status=TriggerLogStatus.ERROR,
 error_message="Token 验证失败",
 )
 return Response(
 {"detail": "Token 验证失败"},
 status=status.HTTP_401_UNAUTHORIZED,
 )
 # Mark as processed
 if event_uuid:
 mark_event_processed(event_uuid)
 logger.info(f"处理事件: {event_type}, 项目: {project_key}, UUID: {event_uuid}")
 # Handle event and create trigger log
 work_item_id = payload.get("id")
 work_item_name = payload.get("name", "")
 work_item_type = payload.get("work_item_type_key", "story")
 trigger_log = TriggerLog.objects.create(
 webhook_raw_request=raw_body,
 event_uuid=event_uuid,
 event_type=event_type,
 project_key=project_key,
 project=project,
 work_item_id=str(work_item_id) if work_item_id else None,
 work_item_name=work_item_name,
 work_item_type=work_item_type,
 status=TriggerLogStatus.ACCEPTED,
 )
 # Handle specific events
 if event_type == "WorkitemCreateEvent":
 self._handle_workitem_create(project, payload, trigger_log)
 elif event_type == "WorkitemStatusEvent":
 self._handle_workitem_status(project, payload, trigger_log)
 elif event_type == "WorkFlowNodeStatusEvent":
 self._handle_workflow_node_status(project, payload, trigger_log)
 elif event_type == "WorkitemCommentEvent":
 self._handle_workitem_comment(project, payload, trigger_log)
 elif event_type == "WorkitemUpdateEvent":
 self._handle_workitem_update(project, payload, trigger_log)
 else:
 logger.info(f"未处理的事件类型: {event_type}")
 # Dispatch to workflow system (for all events)
 self._dispatch_to_workflows(event_type, project, payload, trigger_log)
 return Response(
 {
 "status": "accepted",
 "event_type": event_type,
 "uuid": event_uuid,
 }
 )
 def _dispatch_to_workflows(self, event_type: str, project, payload: dict, trigger_log):
 """Dispatch event to workflow system."""
 try:
 bridge = FeishuWorkflowBridge
 executions = async_to_sync(bridge.dispatch_event)(event_type, project, payload, trigger_log)
 if executions:
 struct_logger.info(
 "workflows_triggered",
 event_type=event_type,
 count=len(executions),
 execution_ids=[str(e.id) for e in executions],
 )
 except Exception as e:
 struct_logger.error(
 "workflow_dispatch_failed",
 event_type=event_type,
 error=str(e),
 )
 def _fetch_and_update_work_item(self, project, work_item_id, work_item_type, trigger_log):
 """Fetch work item details and update trigger log."""
 try:
 feishu_client = create_feishu_client_for_project(project)
 work_item_info = async_to_sync(feishu_client.get_work_item)(
 project_key=project.feishu_project_key or "",
 work_item_id=work_item_id,
 work_item_type=work_item_type,
 )
 # Update trigger log with work item details
 trigger_log.work_item_name = work_item_info.name
 trigger_log.work_item_raw_response = work_item_info.raw_response or ""
 trigger_log.description = work_item_info.description
 # Extract key fields
 fields = work_item_info.fields
 if KeyFields.PRD_URL in fields:
 trigger_log.prd_url = fields[KeyFields.PRD_URL] or ""
 if KeyFields.TECH_DOC_URL in fields:
 trigger_log.tech_doc_url = fields[KeyFields.TECH_DOC_URL] or ""
 trigger_log.save
 return work_item_info
 except Exception as e:
 logger.error(f"获取工作项详情失败: {e}")
 trigger_log.error_message = str(e)
 trigger_log.save
 return None
 def _handle_workitem_create(self, project, payload, trigger_log):
 """处理工作项创建事件。"""
 work_item_id = payload.get("id")
 work_item_name = payload.get("name", "")
 work_item_type = payload.get("work_item_type_key", "story")
 if not work_item_id:
 logger.warning("工作项创建事件缺少 id")
 return
 # Fetch work item details and update trigger log
 self._fetch_and_update_work_item(project, work_item_id, work_item_type, trigger_log)
 logger.info(f"工作项创建事件已处理: {work_item_id}")
 def _handle_workitem_status(self, project, payload, trigger_log):
 """处理工作项状态变更事件。"""
 work_item_id = payload.get("id")
 work_item_type = payload.get("work_item_type_key", "story")
 cur_status = payload.get("cur_work_item_status", {})
 pre_status = payload.get("pre_work_item_status", {})
 if not work_item_id:
 logger.warning("工作项状态变更事件缺少 id")
 return
 cur_state_key = cur_status.get("state_key", "")
 pre_state_key = pre_status.get("state_key", "")
 logger.info(f"状态变更: {work_item_id} {pre_state_key} -> {cur_state_key}")
 # Fetch work item details and update trigger log
 self._fetch_and_update_work_item(project, work_item_id, work_item_type, trigger_log)
 def _handle_workflow_node_status(self, project, payload, trigger_log):
 """处理工作项节点流转事件。"""
 work_item_id = payload.get("id")
 status_change_type = payload.get("status_change_type", "")
 if not work_item_id:
 return
 logger.info(f"节点流转: {work_item_id}, 类型: {status_change_type}")
 def _handle_workitem_comment(self, project, payload, trigger_log):
 """处理工作项评论事件。"""
 work_item_id = payload.get("id")
 comment = payload.get("comment", "")
 if not work_item_id or not comment:
 return
 # Check for approval/rejection keywords (for logging purposes)
 comment_lower = comment.lower
 approval_keywords = ["通过", "批准", "approved", "lgtm", "ok", "👍"]
 rejection_keywords = ["驳回", "拒绝", "rejected", "需要修改", "不通过", "👎"]
 is_approved = any(kw in comment_lower for kw in approval_keywords)
 is_rejected = any(kw in comment_lower for kw in rejection_keywords)
 if is_approved or is_rejected:
 logger.info(f"评论审批: {work_item_id}, 通过={is_approved}, 驳回={is_rejected}")
 # Workflow system handles actual approval logic via _dispatch_to_workflows
 def _handle_workitem_update(self, project, payload, trigger_log):
 """处理工作项字段修改事件。"""
 work_item_id = payload.get("id")
 changed_fields = payload.get("changed_fields", ) or
 if not work_item_id:
 return
 logger.info(f"字段变更: {work_item_id}, 字段数: {len(changed_fields)}")
# ============ Config Views ============
class FeishuConfigView(APIView):
 """Manage Feishu configuration for a project."""
 def get(self, request, project_id):
 project = get_object_or_404(Project, id=project_id)
 return Response(FeishuConfigSerializer(project).data)
 def put(self, request, project_id):
 project = get_object_or_404(Project, id=project_id)
 serializer = FeishuConfigCreateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 project.feishu_plugin_id = serializer.validated_data["plugin_id"]
 project.feishu_plugin_secret_encrypted = encrypt_value(
 serializer.validated_data["plugin_secret"]
 )
 project.feishu_user_key = serializer.validated_data.get("user_key", "")
 project.save
 return Response(FeishuConfigSerializer(project).data)
 def delete(self, request, project_id):
 project = get_object_or_404(Project, id=project_id)
 project.feishu_plugin_id = None
 project.feishu_plugin_secret_encrypted = None
 project.feishu_user_key = None
 project.save
 return Response(status=status.HTTP_204_NO_CONTENT)
class FeishuConfigTestView(APIView):
 """Test Feishu configuration."""
 def post(self, request, project_id):
 project = get_object_or_404(Project, id=project_id)
 if not project.has_feishu_config:
 return Response(
 {
 "success": False,
 "message": "飞书配置不完整，请填写插件 ID 和插件 Secret",
 "plugin_token_valid": False,
 "project_accessible": False,
 }
 )
 # Get test config if provided
 test_plugin_id = request.data.get("plugin_id")
 test_plugin_secret = request.data.get("plugin_secret")
 test_user_key = request.data.get("user_key")
 plugin_id = test_plugin_id or project.feishu_plugin_id
 plugin_secret = None
 if test_plugin_secret:
 plugin_secret = test_plugin_secret
 elif project.feishu_plugin_secret_encrypted:
 plugin_secret = decrypt_value(project.feishu_plugin_secret_encrypted)
 user_key = test_user_key or project.feishu_user_key
 if not plugin_id or not plugin_secret:
 return Response(
 {
 "success": False,
 "message": "飞书配置不完整，请填写插件 ID 和插件 Secret",
 "plugin_token_valid": False,
 "project_accessible": False,
 }
 )
 try:
 client = FeishuClient(
 plugin_id=plugin_id,
 plugin_secret=plugin_secret,
 project_key=project.feishu_project_key,
 user_key=user_key,
 )
 test_result = async_to_sync(client.test_connection)(project.feishu_project_key)
 return Response(test_result)
 except Exception as e:
 return Response(
 {
 "success": False,
 "message": f"测试失败: {str(e)}",
 "plugin_token_valid": False,
 "project_accessible": False,
 }
 )
class RefreshWebhookTokenView(APIView):
 """Refresh webhook token for a project."""
 def post(self, request, project_id):
 project = get_object_or_404(Project, id=project_id)
 project.feishu_webhook_token = generate_webhook_token
 project.save
 return Response(
 WebhookTokenSerializer({"webhook_token": project.feishu_webhook_token}).data
 )
class UpdateWebhookTokenView(APIView):
 """Update webhook token with custom value."""
 def put(self, request, project_id):
 project = get_object_or_404(Project, id=project_id)
 serializer = WebhookTokenUpdateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 token = serializer.validated_data["token"]
 if len(token) > 32:
 return Response(
 {"detail": "Token 长度不能超过 32 个字符"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 if len(token) == 0:
 return Response(
 {"detail": "Token 不能为空"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 project.feishu_webhook_token = token
 project.save
 return Response(
 WebhookTokenSerializer({"webhook_token": project.feishu_webhook_token}).data
 )
# ============ Log Views ============
class TriggerLogListView(APIView):
 """List trigger logs."""
 def get(self, request):
 queryset = TriggerLog.objects.select_related("project").all
 # Filter by project
 project_id = request.query_params.get("project_id")
 if project_id:
 queryset = queryset.filter(project_id=project_id)
 # Filter by event type
 event_type = request.query_params.get("event_type")
 if event_type:
 queryset = queryset.filter(event_type=event_type)
 # Filter by status
 log_status = request.query_params.get("status")
 if log_status:
 queryset = queryset.filter(status=log_status)
 # Get total count before pagination
 total = queryset.count
 # Pagination
 limit = int(request.query_params.get("limit", 50))
 offset = int(request.query_params.get("offset", 0))
 queryset = queryset[offset: offset + limit]
 serializer = TriggerLogSerializer(queryset, many=True)
 return Response({"items": serializer.data, "total": total})
class TriggerLogDetailView(APIView):
 """Get trigger log detail."""
 def get(self, request, log_id):
 log = get_object_or_404(TriggerLog, id=log_id)
 serializer = TriggerLogDetailSerializer(log)
 return Response(serializer.data)
class TriggerLogRawView(APIView):
 """Get raw trigger log data."""
 def get(self, request, log_id):
 log = get_object_or_404(TriggerLog, id=log_id)
 webhook_request = {}
 work_item_response = {}
 try:
 if log.webhook_raw_request:
 webhook_request = json.loads(log.webhook_raw_request)
 except json.JSONDecodeError:
 webhook_request = {"raw": log.webhook_raw_request}
 try:
 if log.work_item_raw_response:
 work_item_response = json.loads(log.work_item_raw_response)
 except json.JSONDecodeError:
 work_item_response = {"raw": log.work_item_raw_response}
 return Response(
 {
 "webhook_request": webhook_request,
 "work_item_response": work_item_response,
 }
 )
class TriggerLogDeleteView(APIView):
 """Delete a trigger log."""
 def delete(self, request, log_id):
 log = get_object_or_404(TriggerLog, id=log_id)
 log.delete
 return Response(status=status.HTTP_204_NO_CONTENT)
class TriggerLogRetryView(APIView):
 """Retry processing a trigger log."""
 def post(self, request, log_id):
 log = get_object_or_404(TriggerLog, id=log_id)
 if not log.webhook_raw_request:
 return Response(
 {"detail": "无法重试：缺少原始 Webhook 请求数据"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 try:
 data = json.loads(log.webhook_raw_request)
 except json.JSONDecodeError:
 return Response(
 {"detail": "无法重试：原始数据格式错误"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # Remove from processed events to allow re-processing
 header = data.get("header", {})
 event_uuid = header.get("uuid")
 if event_uuid and event_uuid in _processed_events:
 _processed_events.discard(event_uuid)
 original_log_id = str(log.id)
 raw_request_body = log.webhook_raw_request
 log.delete
 # Re-process the webhook
 webhook_view = FeishuWebhookView
 # Create a mock request with the original body
 from django.http import HttpRequest
 from rest_framework.request import Request
 mock_http_request = HttpRequest
 mock_http_request.method = "POST"
 mock_http_request._body = raw_request_body.encode("utf-8")
 mock_http_request.content_type = "application/json"
 mock_request = Request(mock_http_request)
 try:
 response = webhook_view.post(mock_request)
 return Response(
 {
 "status": "retried",
 "original_log_id": original_log_id,
 "result": response.data,
 }
 )
 except Exception as e:
 logger.error(f"重试失败: {e}")
 return Response(
 {"detail": f"重试失败: {str(e)}"},
 status=status.HTTP_500_INTERNAL_SERVER_ERROR,
 )
