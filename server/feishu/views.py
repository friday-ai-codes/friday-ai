"""Feishu views: Webhook handling, config management, and logs."""

import asyncio
import json
import uuid as uuid_module
from dataclasses import dataclass
from typing import Any, Callable

import structlog
from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import IntegrityError
from django.shortcuts import aget_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from audit.services import taxonomy
from audit.services.audit_service import AuditService
from common.encryption import decrypt_value, encrypt_value
from common.log_context import LogSource, bind_request_context
from permissions.models import ProjectRole
from permissions.services import PermissionService
from projects.models import Project, generate_webhook_token
from services.feishu_im import FeishuIMClient
from system.webhook_recorder import client_ip, record_inbound_webhook
from workflows.triggers.context import TriggerContext
from workflows.triggers.dispatcher import TriggerDispatcher

from .bot.dispatcher import dispatch_inbound_message
from .bot.parser import normalize_im_message
from .client import FeishuClient, create_feishu_client_for_project, verify_webhook_token
from .models import KeyFields, ProcessedEvent, TriggerLog, TriggerLogStatus
from .serializers import (
    FeishuConfigCreateSerializer,
    FeishuConfigSerializer,
    TriggerLogDetailSerializer,
    TriggerLogSerializer,
    WebhookTokenSerializer,
    WebhookTokenUpdateSerializer,
)

logger = structlog.get_logger(__name__)


def _mask_identifier(value: str | None, prefix: int = 6) -> str:
    """Mask identifiers for debug logs without leaking full values."""
    if not value:
        return ""
    return value[:prefix]


def _verify_and_decrypt_callback_payload(
    request,
    data: dict[str, Any],
    raw_body: str,
    *,
    source: str,
) -> tuple[dict[str, Any] | None, Response | None]:
    """Verify Feishu callback signature and decrypt payload when needed.

    Returns:
        (payload, None) on success
        (None, response) when request should be rejected immediately
    """
    encrypt_key = getattr(settings, "FEISHU_ENCRYPT_KEY", "")
    signature_required = bool(getattr(settings, "FEISHU_SIGNATURE_REQUIRED", False))

    if signature_required and not encrypt_key:
        logger.error(
            "feishu_signature_required_but_key_missing",
            source=source,
        )
        return None, Response(
            {"detail": "服务端未配置 FEISHU_ENCRYPT_KEY"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if not encrypt_key:
        logger.warning(
            "feishu_signature_bypassed_for_dev",
            source=source,
        )
        return data, None

    timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
    nonce = request.headers.get("X-Lark-Request-Nonce", "")
    signature = request.headers.get("X-Lark-Signature", "")

    if not timestamp or not nonce or not signature:
        logger.warning("feishu_signature_headers_missing", source=source)
        return None, Response(
            {"detail": "缺少签名头"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if not FeishuIMClient.verify_callback_signature(
        timestamp=timestamp,
        nonce=nonce,
        body=raw_body,
        signature=signature,
        encrypt_key=encrypt_key,
    ):
        logger.warning("feishu_signature_invalid", source=source)
        return None, Response(
            {"detail": "签名验证失败"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if "encrypt" not in data:
        return data, None

    try:
        decrypted_data = FeishuIMClient.decrypt_callback(data["encrypt"], encrypt_key)
    except Exception as exc:
        logger.error("feishu_callback_decrypt_failed", source=source, error=str(exc))
        return None, Response(
            {"detail": "解密失败"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return decrypted_data, None


# 幂等处理 — DB 级别唯一约束，支持多进程部署和服务重启


async def is_event_processed_db(event_id: str) -> bool:
    """检查事件是否已处理（DB 级别幂等）。"""
    return await ProcessedEvent.objects.filter(event_id=event_id).aexists()


async def mark_event_processed_db(event_id: str) -> bool:
    """标记事件为已处理，返回 True 表示首次标记成功，False 表示已存在。"""
    try:
        await ProcessedEvent.objects.acreate(event_id=event_id)
        return True
    except IntegrityError:
        return False


# ============ Card Callback ============


@dataclass
class CardCallback:
    """卡片回调数据结构。"""

    action_value: dict[str, Any] | str
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
            return updated_card_json  # 或 None 不更新卡片
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

    async def post(self, request):
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

        # LOG-07：卡片回调原始留痕（脱敏后入库，best-effort 绝不反噬主流程）。
        await record_inbound_webhook(
            kind="feishu",
            raw_body=raw_body,
            headers=dict(request.headers),
            source_ip=client_ip(request),
            verified=False,
            correlation={"feishu_entry": "card_callback"},
        )

        # 2. 验签与解密（生产默认强制）
        verified_payload, early_response = _verify_and_decrypt_callback_payload(
            request,
            data,
            raw_body,
            source="card_callback",
        )
        if early_response:
            return early_response
        if verified_payload is not None:
            data = verified_payload

        # 3. 解析回调数据
        action = data.get("action", {})
        # Pass the full value dict to preserve execution_id, node_id, etc.
        action_value_dict = action.get("value", {})
        # Merge form_value into action_value (for form submissions, e.g. custom_answer)
        form_value = action.get("form_value", {})
        if isinstance(form_value, dict) and isinstance(action_value_dict, dict):
            action_value_dict = {**action_value_dict, **form_value}
        # Extract action name for routing (string used for prefix matching)
        action_name = (
            action_value_dict.get("action", "")
            if isinstance(action_value_dict, dict)
            else str(action_value_dict)
        )
        message_id = data.get("open_message_id", "")
        user_open_id = data.get("open_id", "")
        chat_id = data.get("open_chat_id", "")
        tenant_key = data.get("tenant_key", "")

        callback = CardCallback(
            action_value=action_value_dict,
            message_id=message_id,
            user_open_id=user_open_id,
            chat_id=chat_id,
            tenant_key=tenant_key,
        )

        logger.info(
            "card_callback_received",
            action_name=action_name,
            message_id=message_id,
            user_open_id=user_open_id,
        )

        # 4. 根据 action_name 分发处理
        for prefix, handler in _card_callback_handlers.items():
            if action_name.startswith(prefix):
                try:
                    if asyncio.iscoroutinefunction(handler):
                        updated_card = await handler(callback)
                    else:
                        updated_card = handler(callback)
                    if updated_card:
                        # 返回更新后的卡片 JSON
                        return Response(updated_card)
                    # 处理器返回 None，不更新卡片
                    return Response({})
                except Exception as e:
                    logger.error(
                        "card_callback_handler_error",
                        action_name=action_name,
                        error=str(e),
                    )
                    return Response({})

        # 没有匹配的处理器
        logger.warning(
            "card_callback_no_handler",
            action_name=action_name,
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
    from agents.models import AgentSession
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
    # For form submits, form_value is merged into action_value dict
    session_id = ""
    answer = ""

    if isinstance(action_data, dict):
        session_id = action_data.get("session_id", "")
        # Button click: answer is in "answer" key
        # Form submit: user input is in "custom_answer" key (from input element name)
        answer = action_data.get("answer", "") or action_data.get("custom_answer", "")

    if not session_id or not answer:
        logger.warning(
            "user_answer_missing_data",
            session_id=session_id,
            has_answer=bool(answer),
            action_value=str(callback.action_value)[:100],
        )
        return None

    logger.info(
        "user_answer_received",
        session_id=session_id,
        answer_preview=answer[:50] if answer else "",
    )

    # Check session status before scheduling resume
    try:
        session = AgentSession.objects.get(session_id=session_id)
        if session.status != AgentSession.Status.SUSPENDED:
            logger.warning(
                "user_answer_session_not_suspended",
                session_id=session_id,
                status=session.status,
            )
            # Still update the card but don't resume
        else:
            schedule_resume_agent_session(session_id, answer)

        # Get question from session temp_data
        question = (session.temp_data or {}).get("current_question", "")
    except AgentSession.DoesNotExist:
        logger.warning("user_answer_session_not_found", session_id=session_id)
        question = ""
        schedule_resume_agent_session(session_id, answer)

    return build_answered_card(
        question=question,
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
        texts = []
        for lang_content in content_data.values():
            if isinstance(lang_content, dict):
                for para in lang_content.get("content", []):
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
_im_message_queue: list[dict[str, Any]] = []
_MAX_MESSAGE_QUEUE_SIZE = 1000


class IMMessageWebhookView(APIView):
    """处理飞书 IM 消息事件 (im.message.receive_v1)。

    当用户在群聊中 @机器人 或私聊机器人时触发。
    用于 Phase 的用户问答回复匹配。

    配置事件订阅 URL: https://your-domain/api/feishu/im/message/
    """

    permission_classes = [AllowAny]

    async def post(self, request):
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

        # LOG-07：IM 消息回调原始留痕（脱敏后入库，best-effort 绝不反噬主流程）。
        _im_hdr = data.get("header", {}) if isinstance(data, dict) else {}
        await record_inbound_webhook(
            kind="feishu",
            raw_body=raw_body,
            headers=dict(request.headers),
            source_ip=client_ip(request),
            verified=False,
            correlation={
                "feishu_entry": "im_message",
                "event_id": _im_hdr.get("event_id", "") if isinstance(_im_hdr, dict) else "",
                "event_type": _im_hdr.get("event_type", "") if isinstance(_im_hdr, dict) else "",
            },
        )

        # 2. 验签与解密（生产默认强制）
        verified_payload, early_response = _verify_and_decrypt_callback_payload(
            request,
            data,
            raw_body,
            source="im_message",
        )
        if early_response:
            return early_response
        if verified_payload is not None:
            data = verified_payload

        # 3. 解析事件数据
        header = data.get("header", {})
        event = data.get("event", {})

        event_id = header.get("event_id", "")
        event_type = header.get("event_type", "")

        # 幂等检查 — DB 级别
        if event_id and await is_event_processed_db(event_id):
            return Response({"status": "duplicate"})

        if event_id:
            await mark_event_processed_db(event_id)

        # 只处理 im.message.receive_v1 事件
        if event_type != "im.message.receive_v1":
            logger.debug("im_message_event_ignored", event_type=event_type)
            return Response({"status": "ignored"})

        # 提取消息信息
        message = event.get("message", {})
        normalized_message = normalize_im_message(data)

        logger.info(
            "im_message_received",
            chat_id=normalized_message.chat_id,
            message_id=normalized_message.message_id,
            sender_open_id=normalized_message.sender_open_id,
            msg_type=normalized_message.message_type,
            content_preview=normalized_message.normalized_text[:50]
            if normalized_message.normalized_text
            else "",
        )

        # 保留旧队列以兼容 Phase 调试能力
        message_record = {
            "chat_id": normalized_message.chat_id,
            "message_id": normalized_message.message_id,
            "sender_open_id": normalized_message.sender_open_id,
            "content": normalized_message.normalized_text,
            "msg_type": normalized_message.message_type,
            "raw_content": message.get("content", "{}"),
            "received_at": header.get("create_time", ""),
        }
        if len(_im_message_queue) >= _MAX_MESSAGE_QUEUE_SIZE:
            _im_message_queue.pop(0)
        _im_message_queue.append(message_record)

        dispatch_result = await dispatch_inbound_message(normalized_message)
        response_status = (
            "ok"
            if dispatch_result.status in {"bot_message_accepted", "resume_agent"}
            else dispatch_result.status
        )
        if dispatch_result.status == "ignored" and not normalized_message.chat_type:
            response_status = "ok"
        return Response(
            {
                "status": response_status,
                "result": dispatch_result.status,
                "reason": dispatch_result.reason,
            }
        )


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

    async def post(self, request, token=None):
        # CTX-01：webhook 是系统触发（user=system），覆盖入口中间件写入的 source=rest，
        # 声明为 webhook_feishu，使本次处理产生的所有 structlog 事件可归因到飞书 webhook
        # 链路。best-effort，绑定失败绝不影响 webhook 主响应。
        try:
            bind_request_context(
                source=LogSource.WEBHOOK_FEISHU,
                user_id="system",
                request_id=request.headers.get("X-Request-ID") or uuid_module.uuid4().hex,
                trace_id=request.headers.get("X-Trace-ID") or uuid_module.uuid4().hex,
            )
        except Exception:  # noqa: BLE001 — 观测代码绝不反噬业务
            pass

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

        # LOG-07：入站 webhook 原始留痕（脱敏后入库，与既有 TriggerLog 双写纳入统一视图）。
        # 在验签/路由前记录以捕获**全部**入站（含被拒），best-effort 绝不反噬 webhook 主流程。
        _hdr = data.get("header", {}) if isinstance(data, dict) else {}
        await record_inbound_webhook(
            kind="feishu",
            raw_body=raw_body,
            headers=dict(request.headers),
            source_ip=client_ip(request),
            verified=False,
            correlation={
                "event_uuid": _hdr.get("uuid", "") if isinstance(_hdr, dict) else "",
                "event_type": _hdr.get("event_type", "") if isinstance(_hdr, dict) else "",
            },
        )

        # Parse webhook request
        header = data.get("header", {})
        payload = data.get("payload", {})

        if not header or not payload:
            await TriggerLog.objects.acreate(
                webhook_raw_request=raw_body,
                event_type="",
                status=TriggerLogStatus.IGNORED,
                error_message="缺少 header 或 payload",
            )
            return Response({"status": "ignored", "reason": "缺少 header 或 payload"})

        event_uuid = header.get("uuid")
        event_type = header.get("event_type", "")

        # Idempotency check — DB 级别去重
        if event_uuid and await is_event_processed_db(event_uuid):
            logger.info("webhook_event_duplicate", event_uuid=event_uuid)
            return Response({"status": "duplicate", "uuid": event_uuid})

        # 解析路由模式：
        # - 专属端点模式（URL 携带 token）：token 直达唯一工作流，project 取自该工作流；
        #   token 本身即鉴权凭证，不再按 payload 解析空间、不再校验 header token。
        # - 旧版共享端点模式（无 token）：按 payload 的 project_key / project_simple_name
        #   解析空间，并按空间配置的 feishu_webhook_token 校验 header token（向后兼容）。
        if token:
            trigger = await self._resolve_trigger_by_token(token)
            if trigger is None:
                await TriggerLog.objects.acreate(
                    webhook_raw_request=raw_body,
                    event_uuid=None,
                    event_type=event_type,
                    status=TriggerLogStatus.IGNORED,
                    error_message="无效或已停用的触发器端点",
                )
                return Response(
                    {"status": "ignored", "reason": "无效或已停用的触发器端点"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            project = trigger.workflow.project
            project_key = project.feishu_project_key if project else None

            # 节点专属校验 token（纵深防御）：若该触发节点配置了 verification_token，
            # 则比对请求里的 header.token，不匹配即拒绝——端点 URL 泄露也无法触发。
            # 未配置（旧节点）则跳过，仅靠端点 URL 密钥（向后兼容）。
            node_token = await self._get_node_verification_token(trigger)
            if node_token and not verify_webhook_token(header.get("token", ""), node_token):
                await TriggerLog.objects.acreate(
                    webhook_raw_request=raw_body,
                    event_uuid=None,
                    event_type=event_type,
                    project_key=project_key,
                    project=project,
                    status=TriggerLogStatus.ERROR,
                    error_message="校验 Token 不匹配",
                )
                return Response(
                    {"detail": "校验 Token 不匹配"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
        else:
            # 事件 payload 同时携带 project_key（飞书内部空间 ID）与
            # project_simple_name（空间 URL 域名前缀）；用户在空间设置里配的
            # 通常是后者（UI 提示按 URL 前缀获取），两者任一命中即匹配成功。
            candidate_keys = [
                key
                for key in (payload.get("project_key"), payload.get("project_simple_name"))
                if key
            ]
            if not candidate_keys:
                await TriggerLog.objects.acreate(
                    webhook_raw_request=raw_body,
                    event_uuid=None,  # 事件未被处理，不占用 unique 约束位
                    event_type=event_type,
                    status=TriggerLogStatus.IGNORED,
                    error_message="缺少 space_key",
                )
                return Response({"status": "ignored", "reason": "缺少 space_key"})

            project = (
                await Project.objects.prefetch_related("repositories")
                .filter(feishu_project_key__in=candidate_keys)
                .afirst()
            )
            if project is None:
                keys_display = " / ".join(candidate_keys)
                await TriggerLog.objects.acreate(
                    webhook_raw_request=raw_body,
                    event_uuid=None,  # 事件未被处理，不占用 unique 约束位
                    event_type=event_type,
                    project_key=candidate_keys[0],
                    status=TriggerLogStatus.IGNORED,
                    error_message=f"空间未配置: {keys_display}",
                )
                return Response({"status": "ignored", "reason": f"空间未配置: {keys_display}"})

            # 后续日志/TriggerLog/摄取统一使用空间配置的 key（与 handler 内
            # project.feishu_project_key 取值一致，避免同一空间出现两种 key 记录）
            project_key = project.feishu_project_key

            # Verify webhook token
            header_token = header.get("token", "")
            if project.feishu_webhook_token and not verify_webhook_token(
                header_token, project.feishu_webhook_token
            ):
                await TriggerLog.objects.acreate(
                    webhook_raw_request=raw_body,
                    event_uuid=None,  # 事件未被处理，不占用 unique 约束位
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

        # Mark as processed — DB 级别
        if event_uuid:
            await mark_event_processed_db(event_uuid)

        logger.info(
            "webhook_event_processing",
            event_type=event_type,
            space_key=project_key,
            event_uuid=event_uuid,
        )

        # Handle event and create trigger log
        work_item_id = payload.get("id")
        work_item_name = payload.get("name", "")
        work_item_type = payload.get("work_item_type_key", "story")

        try:
            trigger_log = await TriggerLog.objects.acreate(
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
        except IntegrityError:
            # TriggerLog event_uuid unique 约束兜底（DB 级别双重保护）
            logger.info("webhook_event_duplicate_db", event_uuid=event_uuid)
            return Response({"status": "duplicate", "uuid": event_uuid})

        # Handle specific events（副作用：拉详情 / 知识库摄取 / 唤醒挂起工作流 / delivery）
        # 项目级副作用依赖 project；专属端点模式下若工作流未绑定空间则 project 可能为 None，
        # 此时跳过副作用，但仍正常触发工作流。
        if project is None:
            logger.info("webhook_event_no_project_skip_side_effects", event_type=event_type)
        elif event_type == "WorkitemCreateEvent":
            await self._handle_workitem_create(project, payload, trigger_log)
        elif event_type == "WorkitemStatusEvent":
            await self._handle_workitem_status(project, payload, trigger_log)
        elif event_type == "WorkFlowNodeStatusEvent":
            await self._handle_workflow_node_status(project, payload, trigger_log)
        elif event_type == "WorkitemCommentEvent":
            await self._handle_workitem_comment(project, payload, trigger_log)
        elif event_type == "WorkitemUpdateEvent":
            await self._handle_workitem_update(project, payload, trigger_log)
        else:
            logger.info("webhook_event_unhandled", event_type=event_type)

        # Dispatch to workflow system (for all events)
        # token 非空 → 专属端点模式，直达对应工作流；否则走旧版事件类型匹配。
        await self._dispatch_to_workflows(
            event_type, project, payload, trigger_log, trigger_token=token
        )

        return Response(
            {
                "status": "accepted",
                "event_type": event_type,
                "uuid": event_uuid,
            }
        )

    @staticmethod
    async def _resolve_trigger_by_token(token: str):
        """按专属端点 token 定位活跃的 WorkflowTrigger（含工作流与空间）。"""
        from workflows.models import WorkflowTrigger

        return (
            await WorkflowTrigger.objects.filter(
                token=token,
                is_active=True,
                workflow__is_active=True,
            )
            .select_related("workflow", "workflow__project")
            .afirst()
        )

    @staticmethod
    async def _get_node_verification_token(trigger) -> str:
        """读取触发节点 config.verification_token（节点专属校验 token）。

        trigger 无关联节点 / 节点不存在 / 未配置该字段 → 返回空串（跳过校验）。
        """
        if not trigger.node_id:
            return ""
        from workflows.models import WorkflowNode

        node = await WorkflowNode.objects.filter(id=trigger.node_id).afirst()
        if node is None:
            return ""
        return str((node.config or {}).get("verification_token", "")).strip()

    async def _dispatch_to_workflows(
        self, event_type: str, project, payload: dict, trigger_log, trigger_token=None
    ):
        """Dispatch event to workflow system via TriggerDispatcher.

        ``trigger_token`` 非空时走专属端点模式：直达该 token 对应的工作流。
        """
        try:
            trace_id = str(uuid_module.uuid4())

            metadata = {
                "trace_id": trace_id,
                "trigger_log_id": str(trigger_log.id),
            }
            if trigger_token:
                metadata["trigger_token"] = trigger_token

            context = TriggerContext(
                trigger_type="feishu",
                raw_payload=payload,
                event_type=event_type,
                project=project,
                metadata=metadata,
            )

            dispatcher = TriggerDispatcher()
            executions = await dispatcher.dispatch(context)

            if executions:
                logger.info(
                    "workflows_triggered",
                    trace_id=trace_id,
                    event_type=event_type,
                    count=len(executions),
                    execution_ids=[str(e.id) for e in executions],
                )

                # Update trigger_log with execution info
                if len(executions) == 1:
                    trigger_log.workflow_execution = executions[0]
                    await trigger_log.asave(update_fields=["workflow_execution"])

                # 审计：飞书 webhook 自动触发工作流（系统行为，actor=None）
                await AuditService.aemit(
                    action=taxonomy.ACTION_FEISHU_SYNC_TRIGGERED,
                    actor=None,
                    target_type="trigger_log",
                    target_id=trigger_log.id,
                    target_repr=trigger_log.work_item_name or event_type,
                    metadata={
                        "event_type": event_type,
                        "project_id": str(project.id) if project else None,
                        "execution_count": len(executions),
                        "execution_ids": [str(e.id) for e in executions],
                    },
                    source="feishu_webhook",
                )
            else:
                # TRIG-03 / D-03：无匹配工作流不再恒 ACCEPTED，落 IGNORED + 可查原因。
                trigger_log.status = TriggerLogStatus.IGNORED
                trigger_log.error_message = f"无匹配工作流（event_type={event_type}）"
                await trigger_log.asave(update_fields=["status", "error_message"])

        except Exception as e:
            logger.error(
                "workflow_dispatch_failed",
                event_type=event_type,
                error=str(e),
            )
            # TRIG-03 / D-03 / ASVS V7：dispatch 异常落 ERROR + 仅人类可读摘要，
            # str(e)[:2000] 截断防 TextField 膨胀（不拼接 payload/凭证/node 输出值）。
            trigger_log.status = TriggerLogStatus.ERROR
            trigger_log.error_message = str(e)[:2000]
            await trigger_log.asave(update_fields=["status", "error_message"])

    async def _fetch_and_update_work_item(self, project, work_item_id, work_item_type, trigger_log):
        """Fetch work item details and update trigger log."""
        try:
            feishu_client = create_feishu_client_for_project(project)
            work_item_info = await feishu_client.get_work_item(
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

            await trigger_log.asave()

            return work_item_info
        except Exception as e:
            logger.error("work_item_fetch_failed", error=str(e))
            trigger_log.error_message = str(e)
            await trigger_log.asave()
            return None

    def _schedule_delivery_upsert(self, project, work_item_id, work_item_type) -> None:
        """后台投递 delivery upsert（操作态事实源，与 knowledge 投影并存，INV-3）。

        沿用"webhook 只投三元组 ID、正文经 plugin token 后台权威回源"范式：webhook
        主响应不被后台 upsert 阻塞/影响（best-effort，脱离请求生命周期）。三元组不全
        （缺 work_item_id / work_item_type）则跳过投递并 warning，不抛、不构造身份。
        """
        if not work_item_id or not work_item_type:
            logger.warning(
                "delivery_upsert_skip_incomplete_identity",
                work_item_id=work_item_id,
                work_item_type=work_item_type,
            )
            return

        # lazy import 防循环（delivery → feishu 反向依赖）
        from delivery.services import WorkItemIdentity, WorkItemService
        from services.background_runner import run_in_background

        identity = WorkItemIdentity(
            feishu_project_key=project.feishu_project_key,
            work_item_type=work_item_type,
            work_item_id=int(work_item_id),
        )
        run_in_background(
            lambda: WorkItemService().upsert(identity, source="feishu_webhook", fetch=True),
            name=f"delivery-upsert:{project.feishu_project_key}:{work_item_type}:{work_item_id}",
            initiated_by_user_id="system",  # CTX-02：飞书 webhook 系统触发
        )

    async def _handle_workitem_create(self, project, payload, trigger_log):
        """处理工作项创建事件。"""
        work_item_id = payload.get("id")
        work_item_type = payload.get("work_item_type_key", "story")

        if not work_item_id:
            logger.warning("workitem_create_missing_id")
            return

        await self._fetch_and_update_work_item(project, work_item_id, work_item_type, trigger_log)
        logger.info("workitem_create_processed", work_item_id=work_item_id)

        from knowledge import ingestion  # lazy import 防循环

        await ingestion.aschedule_ingestion(
            ingestion.IngestionRequest(
                "feishu_work_item",
                f"{project.feishu_project_key}:{work_item_type}:{work_item_id}",
                "feishu_workitem_create",
            )
        )

        # delivery 操作态 upsert（与上方 knowledge 投影并存，INV-3）。
        # canonical 身份只接受真实 type：不复用上面给 knowledge/fetch 的 "story" 兜底，
        # 缺 work_item_type_key 时传 "" 让 _schedule_delivery_upsert 跳过——占位类型会把
        # 同一工作项分裂成两个 canonical 实体，违背 INV-1（CR-01）。
        self._schedule_delivery_upsert(project, work_item_id, payload.get("work_item_type_key", ""))

    async def _handle_workitem_status(self, project, payload, trigger_log):
        """处理工作项状态变更事件。"""
        work_item_id = payload.get("id")
        work_item_type = payload.get("work_item_type_key", "story")
        cur_status = payload.get("cur_work_item_status", {})
        pre_status = payload.get("pre_work_item_status", {})

        if not work_item_id:
            logger.warning("workitem_status_missing_id")
            return

        cur_state_key = cur_status.get("state_key", "")
        pre_state_key = pre_status.get("state_key", "")

        logger.info(
            "workitem_status_changed",
            work_item_id=work_item_id,
            from_state=pre_state_key,
            to_state=cur_state_key,
        )

        await self._fetch_and_update_work_item(project, work_item_id, work_item_type, trigger_log)

        await self._check_and_resume_suspended_workflows(
            project=project,
            work_item_id=str(work_item_id),
            event_type="WorkitemStatusEvent",
            payload=payload,
        )

        from knowledge import ingestion  # lazy import 防循环

        await ingestion.aschedule_ingestion(
            ingestion.IngestionRequest(
                "feishu_work_item",
                f"{project.feishu_project_key}:{work_item_type}:{work_item_id}",
                "feishu_workitem_status",
            )
        )

        # delivery 操作态 upsert（与上方 knowledge 投影并存，INV-3）。
        # canonical 身份只接受真实 type（缺 work_item_type_key 传 "" 走跳过分支，
        # 避免占位类型分裂实体，违背 INV-1，CR-01）。
        self._schedule_delivery_upsert(project, work_item_id, payload.get("work_item_type_key", ""))

    async def _handle_workflow_node_status(self, project, payload, trigger_log):
        """处理工作项节点流转事件。"""
        work_item_id = payload.get("id")
        status_change_type = payload.get("status_change_type", "")

        if not work_item_id:
            return

        logger.info(
            "workflow_node_status", work_item_id=work_item_id, status_change_type=status_change_type
        )

    def _schedule_comment_append(self, project, payload) -> None:
        """后台 append 评论事件（CMT-01，append-only 事件流，与 approval/knowledge 并存）。

        沿用 ``_schedule_delivery_upsert`` 范式：webhook 只投三元组 + 评论文本，后台经
        ``CommentEventService.append_webhook_comment`` 单一写入收口落库（INV-6），webhook
        主响应不被阻塞（best-effort，脱离请求生命周期）。三元组不全（缺 work_item_id /
        work_item_type_key）则跳过 + warning，不抛、不构造身份（沿用 INV-1 占位类型分裂防护）。
        缺 canonical work_item 由 service 内跳过 + warning（不建 WorkItem）。

        payload 仅取可得字段（comment_id/author/created_at/thread_parent_id），缺失留空/None，
        不臆造 edited/deleted 信号（CONTEXT Grey Area 3）。
        """
        work_item_id = payload.get("id")
        # canonical 身份只接受真实 type：缺 work_item_type_key 跳过（占位类型分裂实体违背 INV-1）
        work_item_type = payload.get("work_item_type_key", "")
        comment = payload.get("comment", "")

        if not work_item_id or not work_item_type or not comment:
            logger.warning(
                "comment_append_skip_incomplete_identity",
                work_item_id=work_item_id,
                work_item_type=work_item_type,
                has_comment=bool(comment),
            )
            return

        # lazy import 防循环（delivery → feishu 反向依赖，同 _schedule_delivery_upsert）
        from delivery.services import CommentEventService, WorkItemIdentity
        from services.background_runner import run_in_background

        identity = WorkItemIdentity(
            feishu_project_key=project.feishu_project_key,
            work_item_type=work_item_type,
            work_item_id=int(work_item_id),
        )
        # payload 可得字段——不提供则空/None，不臆造
        # 飞书评论 webhook payload 的「评论 id」真实键名尚未经真实 payload 校验
        # （PF-11 需 live-Feishu 人工 UAT 确认）。按候选键有序探测取首个非空值，避免
        # 单一硬编码键与真实 payload 不匹配时整条评论被静默丢弃（WR-01）。
        # 注意：顶层 ``id`` 是 work_item_id（见上 work_item_id = payload.get("id")），
        # 故**不**纳入候选，以免把工作项 id 误当评论 id 写脏去重锚。
        comment_id = ""
        for _cid_key in ("comment_id", "comment_id_str", "comm_id"):
            _cid = payload.get(_cid_key)
            if _cid:
                comment_id = str(_cid)
                break
        if not comment_id:
            # 显式暴露字段名不匹配（区别于 service 内 comment_event_skip_missing_id），
            # 便于生产侧发现 webhook 接线失效；仍投递（service 会跳过），不崩溃。
            logger.warning("comment_append_missing_comment_id", work_item_id=work_item_id)
        author = str(payload.get("operator_id") or payload.get("author") or "")
        created_at = payload.get("create_time") or payload.get("created_at")
        thread_parent_id = str(
            payload.get("reply_comment_id") or payload.get("thread_parent_id") or ""
        )

        run_in_background(
            lambda: CommentEventService().append_webhook_comment(
                identity,
                comment_id=comment_id,
                body=comment,
                author=author,
                thread_parent_id=thread_parent_id,
                created_at=created_at,
                source="feishu_webhook",
            ),
            name=f"comment-append:{project.feishu_project_key}:{work_item_type}:{work_item_id}",
            initiated_by_user_id="system",  # CTX-02：飞书 webhook 系统触发
        )

    async def _handle_workitem_comment(self, project, payload, trigger_log):
        """处理工作项评论事件。"""
        work_item_id = payload.get("id")
        comment = payload.get("comment", "")

        if not work_item_id or not comment:
            return

        # approval 语义复用 29-02 classify_approval_semantic 作单一判定来源，
        # 避免关键词在 webhook 与 service 两处漂移（CONTEXT Grey Area 3）。
        from delivery.services import classify_approval_semantic

        semantic = classify_approval_semantic(comment)
        is_approved = semantic == "approve"
        is_rejected = semantic == "reject"

        if is_approved or is_rejected:
            logger.info(
                "workitem_comment_approval",
                work_item_id=work_item_id,
                approved=is_approved,
                rejected=is_rejected,
            )

            from feishu.approval import FeishuApprovalHandler

            handler = FeishuApprovalHandler()
            try:
                approved = is_approved and not is_rejected
                result = await handler.on_approval_comment(
                    work_item_id=str(work_item_id),
                    approved=approved,
                    comment=comment,
                    approver=None,
                )
                if result:
                    logger.info(
                        "feishu_approval_processed_via_webhook",
                        work_item_id=work_item_id,
                        approved=approved,
                    )
                else:
                    logger.warning(
                        "feishu_approval_no_matching_execution",
                        work_item_id=work_item_id,
                    )
            except Exception as e:
                logger.error(
                    "feishu_approval_handler_error",
                    work_item_id=work_item_id,
                    error=str(e),
                )

        # CMT-01：在保留既有 approval 处理（及 knowledge 投影，INV-3）的同时，
        # **追加**后台 append CommentEvent 事件流（approval 与否皆记录评论事件）。
        self._schedule_comment_append(project, payload)

    async def _handle_workitem_update(self, project, payload, trigger_log):
        """处理工作项字段修改事件。"""
        work_item_id = payload.get("id")
        # 不默认 "story"：三元组是实体 natural key，占位类型会把同一工作项
        # 分裂成两个实体（WR-04）——缺失时跳过摄取投递，仅 warning。
        work_item_type = payload.get("work_item_type_key", "")
        changed_fields = payload.get("changed_fields", []) or []

        if not work_item_id:
            return

        logger.info(
            "workitem_fields_updated", work_item_id=work_item_id, field_count=len(changed_fields)
        )

        await self._check_and_resume_suspended_workflows(
            project=project,
            work_item_id=str(work_item_id),
            event_type="WorkitemUpdateEvent",
            payload=payload,
        )

        if not work_item_type:
            # 与 workflow_plan "三字段齐备才建锚" 同款防线：缺类型不构造身份 key
            logger.warning(
                "workitem_update_missing_type_key_skip_ingestion", work_item_id=work_item_id
            )
            return

        from knowledge import ingestion  # lazy import 防循环

        await ingestion.aschedule_ingestion(
            ingestion.IngestionRequest(
                "feishu_work_item",
                f"{project.feishu_project_key}:{work_item_type}:{work_item_id}",
                "feishu_workitem_update",
            )
        )

        # delivery 操作态 upsert（与上方 knowledge 投影并存，INV-3）；
        # 缺 work_item_type 已在上方 early-return 跳过（与 ingestion 同款防线）
        self._schedule_delivery_upsert(project, work_item_id, work_item_type)

    async def _check_and_resume_suspended_workflows(
        self,
        project,
        work_item_id: str,
        event_type: str,
        payload: dict,
    ) -> None:
        """检查并唤醒匹配的挂起工作流"""

        from workflows.conditions import evaluate_condition
        from workflows.models.execution import (
            WorkflowEventSubscription,
        )

        try:
            subscriptions = WorkflowEventSubscription.objects.filter(
                is_active=True,
                project_key=project.feishu_project_key,
                work_item_id=work_item_id,
                event_type=event_type,
            ).select_related("workflow_execution", "node_execution")

            fields = await self._get_current_fields(project, work_item_id, payload)

            async for sub in subscriptions:
                if evaluate_condition(sub.condition_expression, fields):
                    logger.info(
                        "subscription_matched",
                        subscription_id=str(sub.id),
                        work_item_id=work_item_id,
                        execution_id=str(sub.workflow_execution_id),
                    )

                    sub.mark_matched(payload)

                    await self._resume_node_execution(sub, fields)

        except Exception as e:
            logger.error(
                "resume_suspended_workflows_error",
                work_item_id=work_item_id,
                error=str(e),
            )

    async def _get_current_fields(self, project, work_item_id: str, payload: dict) -> dict:
        """获取当前字段值（优先从 payload 获取，否则调用 API）"""
        if "fields" in payload:
            return payload["fields"]

        changed_fields = payload.get("changed_fields", [])
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

        try:
            feishu_client = create_feishu_client_for_project(project)
            work_item = await feishu_client.get_work_item(
                project_key=project.feishu_project_key or "",
                work_item_id=work_item_id,
                work_item_type=payload.get("work_item_type_key", "story"),
            )
            return work_item.fields if work_item else {}
        except Exception as e:
            logger.warning("work_item_fields_fetch_failed", error=str(e))
            return {}

    async def _resume_node_execution(self, subscription, matched_fields: dict) -> None:
        """恢复节点执行"""
        from django.utils import timezone

        from workflows.engine.scheduler import WorkflowEngine
        from workflows.models.execution import ExecutionStatus, NodeExecutionStatus

        node_execution = subscription.node_execution
        workflow_execution = subscription.workflow_execution

        if workflow_execution.status == ExecutionStatus.SUSPENDED:
            workflow_execution.status = ExecutionStatus.RUNNING
            await workflow_execution.asave(update_fields=["status"])

        node_execution.status = NodeExecutionStatus.COMPLETED
        node_execution.completed_at = timezone.now()
        node_execution.output_data = {
            "matched": True,
            "field_value": matched_fields,
            "wait_duration": (timezone.now() - subscription.created_at).total_seconds(),
        }
        await node_execution.asave(update_fields=["status", "completed_at", "output_data"])

        workflow_execution.completed_nodes += 1
        await workflow_execution.asave(update_fields=["completed_nodes"])

        engine = WorkflowEngine()
        await engine._continue_after_node(workflow_execution, node_execution)

        logger.info(
            "node_resumed",
            node_execution_id=str(node_execution.id),
            execution_id=str(workflow_execution.id),
        )


# ============ Config Views ============


async def _require_space_admin(request, project) -> Response | None:
    """空间配置写操作守卫：仅空间管理员或系统管理员（#11/#12）。

    通过返回 None；否则返回 403 Response。
    """
    is_admin = await sync_to_async(PermissionService.has_project_access)(
        request.user, project, ProjectRole.ADMIN
    )
    if not is_admin:
        return Response(
            {"detail": "仅空间管理员可操作此配置"}, status=status.HTTP_403_FORBIDDEN
        )
    return None


async def _require_space_member(request, project) -> Response | None:
    """空间读操作守卫：需为空间成员（viewer+）或系统管理员。"""
    has_access = await sync_to_async(PermissionService.has_project_access)(
        request.user, project
    )
    if not has_access:
        return Response(
            {"detail": "无权访问此空间"}, status=status.HTTP_403_FORBIDDEN
        )
    return None


class FeishuConfigView(APIView):
    """Manage Feishu configuration for a space."""

    async def get(self, request, space_id):
        project = await aget_object_or_404(Project, id=space_id)
        denied = await _require_space_member(request, project)
        if denied is not None:
            return denied
        data = FeishuConfigSerializer(project).data
        logger.info(
            "feishu_config_view_get",
            space_id=str(project.id),
            space_name=project.name,
            space_key=data.get("project_key") or "",
            plugin_id_prefix=_mask_identifier(data.get("plugin_id")),
            has_plugin_secret=bool(data.get("has_plugin_secret")),
            user_key_prefix=_mask_identifier(data.get("user_key")),
        )
        return Response(data)

    async def put(self, request, space_id):
        project = await aget_object_or_404(Project, id=space_id)
        denied = await _require_space_admin(request, project)
        if denied is not None:
            return denied
        serializer = FeishuConfigCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        project.feishu_plugin_id = serializer.validated_data["plugin_id"]
        project.feishu_plugin_secret_encrypted = encrypt_value(
            serializer.validated_data["plugin_secret"]
        )
        project.feishu_user_key = serializer.validated_data.get("user_key", "")
        await project.asave()

        return Response(FeishuConfigSerializer(project).data)

    async def delete(self, request, space_id):
        project = await aget_object_or_404(Project, id=space_id)
        denied = await _require_space_admin(request, project)
        if denied is not None:
            return denied
        project.feishu_plugin_id = None
        project.feishu_plugin_secret_encrypted = None
        project.feishu_user_key = None
        await project.asave()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FeishuConfigTestView(APIView):
    """Test Feishu configuration."""

    async def post(self, request, space_id):
        project = await aget_object_or_404(Project, id=space_id)
        denied = await _require_space_admin(request, project)
        if denied is not None:
            return denied

        if not project.has_feishu_config():
            return Response(
                {
                    "success": False,
                    "message": "飞书配置不完整，请填写插件 ID 和插件 Secret",
                    "plugin_token_valid": False,
                    "space_accessible": False,
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
                    "space_accessible": False,
                }
            )

        logger.info(
            "feishu_config_test_started",
            space_id=str(project.id),
            space_name=project.name,
            space_key=project.feishu_project_key or "",
            using_temp_plugin_id=bool(test_plugin_id),
            using_temp_plugin_secret=bool(test_plugin_secret),
            using_temp_user_key=bool(test_user_key),
            plugin_id_prefix=_mask_identifier(plugin_id),
            user_key_prefix=_mask_identifier(user_key),
        )

        try:
            client = FeishuClient(
                plugin_id=plugin_id,
                plugin_secret=plugin_secret,
                project_key=project.feishu_project_key,
                user_key=user_key,
            )
            test_result = await client.test_connection(project.feishu_project_key)
            logger.info(
                "feishu_config_test_finished",
                space_id=str(project.id),
                success=bool(test_result.get("success")),
                plugin_token_valid=bool(test_result.get("plugin_token_valid")),
                space_accessible=bool(test_result.get("space_accessible")),
                message=test_result.get("message", ""),
            )
            return Response(test_result)
        except Exception as e:
            logger.error(
                "feishu_config_test_failed",
                space_id=str(project.id),
                error=str(e),
            )
            return Response(
                {
                    "success": False,
                    "message": f"测试失败: {str(e)}",
                    "plugin_token_valid": False,
                    "space_accessible": False,
                }
            )


class RefreshWebhookTokenView(APIView):
    """Refresh webhook token for a space."""

    async def post(self, request, space_id):
        project = await aget_object_or_404(Project, id=space_id)
        denied = await _require_space_admin(request, project)
        if denied is not None:
            return denied
        project.feishu_webhook_token = generate_webhook_token()
        await project.asave()
        return Response(
            WebhookTokenSerializer({"webhook_token": project.feishu_webhook_token}).data
        )


class UpdateWebhookTokenView(APIView):
    """Update webhook token with custom value."""

    async def put(self, request, space_id):
        project = await aget_object_or_404(Project, id=space_id)
        denied = await _require_space_admin(request, project)
        if denied is not None:
            return denied
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
        await project.asave()
        return Response(
            WebhookTokenSerializer({"webhook_token": project.feishu_webhook_token}).data
        )


# ============ Log Views ============


class TriggerLogListView(APIView):
    """List trigger logs."""

    async def get(self, request):
        queryset = TriggerLog.objects.select_related("project").all()

        # Filter by space
        space_id = request.query_params.get("space_id")
        if space_id:
            queryset = queryset.filter(project_id=space_id)

        # Filter by event type
        event_type = request.query_params.get("event_type")
        if event_type:
            queryset = queryset.filter(event_type=event_type)

        # Filter by status
        log_status = request.query_params.get("status")
        if log_status:
            queryset = queryset.filter(status=log_status)

        # Get total count before pagination
        total = await queryset.acount()

        # Pagination
        limit = int(request.query_params.get("limit", 50))
        offset = int(request.query_params.get("offset", 0))
        items = [item async for item in queryset[offset : offset + limit]]

        serializer = TriggerLogSerializer(items, many=True)
        # KEEP: TriggerLogSerializer.get_execution_status 触发 workflow_executions 反向查询
        data = await sync_to_async(lambda: serializer.data)()
        return Response({"items": data, "total": total})


class TriggerLogDetailView(APIView):
    """Get trigger log detail."""

    async def get(self, request, log_id):
        log = await aget_object_or_404(TriggerLog, id=log_id)
        serializer = TriggerLogDetailSerializer(log)
        # KEEP: TriggerLogDetailSerializer.get_workflow_executions 触发反向 FK 查询
        data = await sync_to_async(lambda: serializer.data)()
        return Response(data)


class TriggerLogRawView(APIView):
    """Get raw trigger log data."""

    async def get(self, request, log_id):
        log = await aget_object_or_404(TriggerLog, id=log_id)

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

    async def delete(self, request, log_id):
        log = await aget_object_or_404(TriggerLog, id=log_id)
        await log.adelete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TriggerLogRetryView(APIView):
    """Retry processing a trigger log."""

    async def post(self, request, log_id):
        log = await aget_object_or_404(TriggerLog, id=log_id)

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

        # Remove from processed events to allow re-processing (DB 级别)
        header = data.get("header", {})
        event_uuid = header.get("uuid")
        if event_uuid:
            await ProcessedEvent.objects.filter(event_id=event_uuid).adelete()

        original_log_id = str(log.id)
        original_event_type = log.event_type
        original_work_item = log.work_item_name
        raw_request_body = log.webhook_raw_request
        await log.adelete()

        # Re-process the webhook
        webhook_view = FeishuWebhookView()

        # Create a mock request with the original body
        from django.http import HttpRequest
        from rest_framework.request import Request

        mock_http_request = HttpRequest()
        mock_http_request.method = "POST"
        mock_http_request._body = raw_request_body.encode("utf-8")
        mock_http_request.content_type = "application/json"
        mock_request = Request(mock_http_request)

        try:
            response = await webhook_view.post(mock_request)
            # 审计：人工重试飞书触发（actor=操作者，区别于自动 webhook）
            await AuditService.aemit(
                action=taxonomy.ACTION_FEISHU_SYNC_TRIGGERED,
                actor=request.user,
                target_type="trigger_log",
                target_id=original_log_id,
                target_repr=original_work_item or original_event_type,
                metadata={
                    "event_type": original_event_type,
                    "retry": True,
                    "original_log_id": original_log_id,
                },
                source="api",
            )
            return Response(
                {
                    "status": "retried",
                    "original_log_id": original_log_id,
                    "result": response.data,
                }
            )
        except Exception as e:
            logger.error("trigger_log_retry_failed", error=str(e))
            return Response(
                {"detail": f"重试失败: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
