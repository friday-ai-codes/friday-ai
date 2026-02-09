"""Feishu views: Webhook handling, config management, and logs."""
import json
import logging
import uuid as uuid_module
from dataclasses import dataclass
from typing import Any, Callable
import structlog
from asgiref.sync import async_to_sync
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from common.encryption import decrypt_value, encrypt_value
from projects.models import Project, generate_webhook_token
from workflows.triggers.context import TriggerContext
from workflows.triggers.dispatcher import TriggerDispatcher
from services.feishu_im import FeishuIMClient
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
logger = logging.getLogger(__name__)
struct_logger = structlog.get_logger
# 幂等处理
_processed_events: set[str] = set
_MAX_PROCESSED_EVENTS = 10000
def is_event_processed(event_uuid: str) -> bool:
 return event_uuid in _processed_events
def mark_event_processed(event_uuid: str) -> None:
 if len(_processed_events) >= _MAX_PROCESSED_EVENTS:
 to_remove = list(_processed_events)[: _MAX_PROCESSED_EVENTS // 2]
 for uuid in to_remove:
 _processed_events.discard(uuid)
 _processed_events.add(event_uuid)
# ============ Card Callback ============
@dataclass
class CardCallback:
 """卡片回调数据结构。"""
 action_value: str
 message_id: str
 user_open_id: str
 chat_id: str
 tenant_key: str
# 卡片回调处理器注册表
_card_callback_handlers: dict[str, Callable[[CardCallback], dict[str, Any] | None]] = {}
def register_card_callback(action_prefix: str) -> Callable:
 """装饰器，注册卡片回调处理器。
 Args:
 action_prefix: action value 的前缀，用于匹配回调
 Example:
 @register_card_callback("approve_")
 def handle_approve(callback: CardCallback) -> dict | None:
 # 处理审批按钮点击
 return updated_card_json # 或 None 不更新卡片
 """
 def decorator(func: Callable[[CardCallback], dict[str, Any] | None]) -> Callable:
 _card_callback_handlers[action_prefix] = func
 return func
 return decorator
class CardCallbackView(APIView):
 """处理飞书卡片按钮点击回调。
 飞书会在用户点击卡片按钮时发送 POST 请求，必须在 3 秒内响应。
 复杂逻辑应异步处理，先返回"处理中"状态的卡片。
 配置回调 URL: https://your-domain/api/feishu/card/callback/
 """
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
 # 1. 处理 challenge 验证 (首次配置回调 URL)
 if "challenge" in data:
 return Response({"challenge": data["challenge"]})
 # 2. 验证签名 (如果配置了 encrypt_key)
 encrypt_key = getattr(settings, "FEISHU_ENCRYPT_KEY", "")
 if encrypt_key:
 timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
 nonce = request.headers.get("X-Lark-Request-Nonce", "")
 signature = request.headers.get("X-Lark-Signature", "")
 if not FeishuIMClient.verify_callback_signature(
 timestamp=timestamp,
 nonce=nonce,
 body=raw_body,
 signature=signature,
 encrypt_key=encrypt_key,
 ):
 struct_logger.warning("card_callback_signature_invalid")
 return Response(
 {"detail": "签名验证失败"},
 status=status.HTTP_401_UNAUTHORIZED,
 )
 # 解密加密内容
 if "encrypt" in data:
 try:
 data = FeishuIMClient.decrypt_callback(
 data["encrypt"], encrypt_key
 )
 except Exception as e:
 struct_logger.error("card_callback_decrypt_failed", error=str(e))
 return Response(
 {"detail": "解密失败"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 3. 解析回调数据
 action = data.get("action", {})
 action_value = action.get("value", {}).get("action", "")
 message_id = data.get("open_message_id", "")
 user_open_id = data.get("open_id", "")
 chat_id = data.get("open_chat_id", "")
 tenant_key = data.get("tenant_key", "")
 callback = CardCallback(
 action_value=action_value,
 message_id=message_id,
 user_open_id=user_open_id,
 chat_id=chat_id,
 tenant_key=tenant_key,
 )
 struct_logger.info(
 "card_callback_received",
 action_value=action_value,
 message_id=message_id,
 user_open_id=user_open_id,
 )
 # 4. 根据 action_value 分发处理
 for prefix, handler in _card_callback_handlers.items:
 if action_value.startswith(prefix):
 try:
 updated_card = handler(callback)
 if updated_card:
 # 返回更新后的卡片 JSON
 return Response(updated_card)
 # 处理器返回 None，不更新卡片
 return Response({})
 except Exception as e:
 struct_logger.error(
 "card_callback_handler_error",
 action_value=action_value,
 error=str(e),
 )
 return Response({})
 # 没有匹配的处理器
 struct_logger.warning(
 "card_callback_no_handler",
 action_value=action_value,
 )
 return Response({})
# ============ User Answer Callback Handler ============
@register_card_callback("user_answer")
def handle_user_answer(callback: CardCallback) -> dict[str, Any] | None:
 """Handle user answer from question card.
 Processes button clicks and form submissions from ask_user_question cards.
 Schedules async session resume and returns updated card immediately.
 Args:
 callback: Card callback data with action_value and context
 Returns:
 Updated card JSON showing answered state, or None
 """
 from feishu.cards.question_card import build_answered_card
 from tasks.agent_tasks import schedule_resume_agent_session
 # Parse action value (may be string or dict)
 action_data = callback.action_value
 if isinstance(action_data, str):
 try:
 action_data = json.loads(action_data)
 except json.JSONDecodeError:
 action_data = {}
 # For button clicks, action_value comes from action.value dict
 # For form submits, we need to check the raw callback data
 session_id = ""
 answer = ""
 if isinstance(action_data, dict):
 session_id = action_data.get("session_id", "")
 answer = action_data.get("answer", "")
 # If no answer from button, this might be a form submission
 # Form values come through differently - need to handle in CardCallbackView
 # For now, we extract from the callback structure
 if not session_id or not answer:
 struct_logger.warning(
 "user_answer_missing_data",
 session_id=session_id,
 has_answer=bool(answer),
 action_value=str(callback.action_value)[:100],
 )
 return None
 struct_logger.info(
 "user_answer_received",
 session_id=session_id,
 answer_preview=answer[:50] if answer else "",
 )
 # Schedule async session resume (don't block callback response)
 schedule_resume_agent_session(session_id, answer)
 # Get current question from session for the answered card
 # We use a simple approach - just show the answer
 return build_answered_card(
 question="", # Question was already in the card
 answer=answer,
 history=None,
 )
# ============ IM Message Webhook ============
def parse_message_content(msg_type: str, content: str) -> str:
 """解析飞书消息内容为纯文本。
 Args:
 msg_type: 消息类型 (text, post, interactive)
 content: JSON 格式的消息内容
 Returns:
 纯文本内容
 """
 try:
 content_data = json.loads(content)
 except json.JSONDecodeError:
 return content
 if msg_type == "text":
 return content_data.get("text", "")
 elif msg_type == "post":
 # 富文本: 提取所有 text 节点
 texts =
 for lang_content in content_data.values:
 if isinstance(lang_content, dict):
 for para in lang_content.get("content", ):
 for elem in para:
 if elem.get("tag") == "text":
 texts.append(elem.get("text", ""))
 return " ".join(texts)
 elif msg_type == "interactive":
 # 卡片消息: 返回空 (通常不需要解析)
 return ""
 else:
 return str(content_data)
# 消息接收队列 (内存队列，为 Phase 准备)
# 生产环境应使用 Redis 或数据库
_im_message_queue: list[dict[str, Any]] =
_MAX_MESSAGE_QUEUE_SIZE = 1000
class IMMessageWebhookView(APIView):
 """处理飞书 IM 消息事件 (im.message.receive_v1)。
 当用户在群聊中 @机器人 或私聊机器人时触发。
 用于 Phase 的用户问答回复匹配。
 配置事件订阅 URL: https://your-domain/api/feishu/im/message/
 """
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
 # 1. 处理 URL 验证 (url_verification 事件)
 if data.get("type") == "url_verification":
 return Response({"challenge": data.get("challenge", "")})
 # 2. 验证事件签名 (如果配置了 encrypt_key)
 encrypt_key = getattr(settings, "FEISHU_ENCRYPT_KEY", "")
 if encrypt_key:
 timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
 nonce = request.headers.get("X-Lark-Request-Nonce", "")
 signature = request.headers.get("X-Lark-Signature", "")
 if not FeishuIMClient.verify_callback_signature(
 timestamp=timestamp,
 nonce=nonce,
 body=raw_body,
 signature=signature,
 encrypt_key=encrypt_key,
 ):
 struct_logger.warning("im_message_signature_invalid")
 return Response(
 {"detail": "签名验证失败"},
 status=status.HTTP_401_UNAUTHORIZED,
 )
 # 解密加密内容
 if "encrypt" in data:
 try:
 data = FeishuIMClient.decrypt_callback(
 data["encrypt"], encrypt_key
 )
 except Exception as e:
 struct_logger.error("im_message_decrypt_failed", error=str(e))
 return Response(
 {"detail": "解密失败"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # 3. 解析事件数据
 header = data.get("header", {})
 event = data.get("event", {})
 event_id = header.get("event_id", "")
 event_type = header.get("event_type", "")
 # 幂等检查
 if event_id and is_event_processed(event_id):
 return Response({"status": "duplicate"})
 if event_id:
 mark_event_processed(event_id)
 # 只处理 im.message.receive_v1 事件
 if event_type != "im.message.receive_v1":
 struct_logger.debug("im_message_event_ignored", event_type=event_type)
 return Response({"status": "ignored"})
 # 提取消息信息
 message = event.get("message", {})
 sender = event.get("sender", {})
 chat_id = message.get("chat_id", "")
 message_id = message.get("message_id", "")
 msg_type = message.get("message_type", "text")
 content_raw = message.get("content", "{}")
 sender_open_id = sender.get("sender_id", {}).get("open_id", "")
 # 解析消息内容
 content_text = parse_message_content(msg_type, content_raw)
 struct_logger.info(
 "im_message_received",
 chat_id=chat_id,
 message_id=message_id,
 sender_open_id=sender_open_id,
 msg_type=msg_type,
 content_preview=content_text[:50] if content_text else "",
 )
 # 4. 存储消息到队列 (供 Phase 匹配)
 message_record = {
 "chat_id": chat_id,
 "message_id": message_id,
 "sender_open_id": sender_open_id,
 "content": content_text,
 "msg_type": msg_type,
 "raw_content": content_raw,
 "received_at": header.get("create_time", ""),
 }
 # 队列大小限制
 if len(_im_message_queue) >= _MAX_MESSAGE_QUEUE_SIZE:
 _im_message_queue.pop(0) # 移除最旧的消息
 _im_message_queue.append(message_record)
 # 5. 返回 200 OK (必须快速响应)
 return Response({"status": "ok"})
def get_pending_messages(chat_id: str | None = None) -> list[dict[str, Any]]:
 """获取待处理的消息队列 (供 Phase 使用)。
 Args:
 chat_id: 可选，过滤特定群聊的消息
 Returns:
 消息列表
 """
 if chat_id:
 return [m for m in _im_message_queue if m["chat_id"] == chat_id]
 return list(_im_message_queue)
def pop_message(message_id: str) -> dict[str, Any] | None:
 """从队列中移除并返回指定消息 (供 Phase 使用)。
 Args:
 message_id: 消息 ID
 Returns:
 消息记录或 None
 """
 for i, msg in enumerate(_im_message_queue):
 if msg["message_id"] == message_id:
 return _im_message_queue.pop(i)
 return None
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
 """Dispatch event to workflow system via TriggerDispatcher."""
 try:
 trace_id = str(uuid_module.uuid4)
 context = TriggerContext(
 trigger_type="feishu",
 raw_payload=payload,
 event_type=event_type,
 project=project,
 metadata={
 "trace_id": trace_id,
 "trigger_log_id": str(trigger_log.id),
 },
 )
 dispatcher = TriggerDispatcher
 executions = async_to_sync(dispatcher.dispatch)(context)
 if executions:
 struct_logger.info(
 "workflows_triggered",
 trace_id=trace_id,
 event_type=event_type,
 count=len(executions),
 execution_ids=[str(e.id) for e in executions],
 )
 # Update trigger_log with execution info
 if len(executions) == 1:
 trigger_log.workflow_execution = executions[0]
 trigger_log.save(update_fields=["workflow_execution"])
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
 # 检查并唤醒挂起的工作流
 self._check_and_resume_suspended_workflows(
 project=project,
 work_item_id=str(work_item_id),
 event_type="WorkitemStatusEvent",
 payload=payload,
 )
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
 # Call FeishuApprovalHandler
 from feishu.approval import FeishuApprovalHandler
 handler = FeishuApprovalHandler
 try:
 approved = is_approved and not is_rejected # Rejection takes priority
 result = async_to_sync(handler.on_approval_comment)(
 work_item_id=str(work_item_id),
 approved=approved,
 comment=comment,
 approver=None,
 )
 if result:
 struct_logger.info(
 "feishu_approval_processed_via_webhook",
 work_item_id=work_item_id,
 approved=approved,
 )
 else:
 struct_logger.warning(
 "feishu_approval_no_matching_execution",
 work_item_id=work_item_id,
 )
 except Exception as e:
 struct_logger.error(
 "feishu_approval_handler_error",
 work_item_id=work_item_id,
 error=str(e),
 )
 def _handle_workitem_update(self, project, payload, trigger_log):
 """处理工作项字段修改事件。"""
 work_item_id = payload.get("id")
 changed_fields = payload.get("changed_fields", ) or
 if not work_item_id:
 return
 logger.info(f"字段变更: {work_item_id}, 字段数: {len(changed_fields)}")
 # 检查并唤醒挂起的工作流
 self._check_and_resume_suspended_workflows(
 project=project,
 work_item_id=str(work_item_id),
 event_type="WorkitemUpdateEvent",
 payload=payload,
 )
 def _check_and_resume_suspended_workflows(
 self,
 project,
 work_item_id: str,
 event_type: str,
 payload: dict,
 ) -> None:
 """检查并唤醒匹配的挂起工作流"""
 from django.utils import timezone
 from workflows.conditions import evaluate_condition
 from workflows.engine.scheduler import WorkflowEngine
 from workflows.models.execution import (
 NodeExecutionStatus,
 WorkflowEventSubscription,
 )
 try:
 # 查找匹配的活跃订阅
 subscriptions = WorkflowEventSubscription.objects.filter(
 is_active=True,
 project_key=project.feishu_project_key,
 work_item_id=work_item_id,
 event_type=event_type,
 ).select_related("workflow_execution", "node_execution")
 # 获取当前字段值用于条件匹配
 fields = self._get_current_fields(project, work_item_id, payload)
 for sub in subscriptions:
 # 求值条件
 if evaluate_condition(sub.condition_expression, fields):
 struct_logger.info(
 "subscription_matched",
 subscription_id=str(sub.id),
 work_item_id=work_item_id,
 execution_id=str(sub.workflow_execution_id),
 )
 # 标记订阅已匹配
 sub.mark_matched(payload)
 # 恢复节点执行
 self._resume_node_execution(sub, fields)
 except Exception as e:
 struct_logger.error(
 "resume_suspended_workflows_error",
 work_item_id=work_item_id,
 error=str(e),
 )
 def _get_current_fields(self, project, work_item_id: str, payload: dict) -> dict:
 """获取当前字段值（优先从 payload 获取，否则调用 API）"""
 # payload 中可能包含 changed_fields 或完整字段
 if "fields" in payload:
 return payload["fields"]
 # 从 changed_fields 构建字段映射
 changed_fields = payload.get("changed_fields", )
 if changed_fields:
 fields: dict = {}
 for field in changed_fields:
 if isinstance(field, dict):
 field_key = field.get("field_key", "")
 new_value = field.get("new_value")
 if field_key:
 fields[field_key] = new_value
 if fields:
 return fields
 # 回退：调用 API 获取完整字段
 try:
 feishu_client = create_feishu_client_for_project(project)
 work_item = async_to_sync(feishu_client.get_work_item)(
 project_key=project.feishu_project_key or "",
 work_item_id=work_item_id,
 work_item_type=payload.get("work_item_type_key", "story"),
 )
 return work_item.fields if work_item else {}
 except Exception as e:
 logger.warning(f"获取工作项字段失败: {e}")
 return {}
 def _resume_node_execution(
 self, subscription, matched_fields: dict
 ) -> None:
 """恢复节点执行"""
 from django.utils import timezone
 from workflows.engine.scheduler import WorkflowEngine
 from workflows.models.execution import ExecutionStatus, NodeExecutionStatus
 node_execution = subscription.node_execution
 workflow_execution = subscription.workflow_execution
 # If workflow is suspended, mark it as running before continuing
 if workflow_execution.status == ExecutionStatus.SUSPENDED:
 workflow_execution.status = ExecutionStatus.RUNNING
 workflow_execution.save(update_fields=["status"])
 # 更新节点状态为完成
 node_execution.status = NodeExecutionStatus.COMPLETED
 node_execution.completed_at = timezone.now
 node_execution.output_data = {
 "matched": True,
 "field_value": matched_fields,
 "wait_duration": (
 timezone.now - subscription.created_at
 ).total_seconds,
 }
 node_execution.save(update_fields=["status", "completed_at", "output_data"])
 # 更新执行统计
 workflow_execution.completed_nodes += 1
 workflow_execution.save(update_fields=["completed_nodes"])
 # 触发后续节点执行
 engine = WorkflowEngine
 async_to_sync(engine._continue_after_node)(
 workflow_execution, node_execution
 )
 struct_logger.info(
 "node_resumed",
 node_execution_id=str(node_execution.id),
 execution_id=str(workflow_execution.id),
 )
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
 mock_request = Request(mock_http_request) # type: ignore[call-arg]
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
