"""Web Push 服务。"""
from __future__ import annotations
import asyncio
import base64
import json
from dataclasses import dataclass
from typing import Any
import structlog
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.conf import settings
from django.utils import timezone
from py_vapid import Vapid01
from pywebpush import WebPushException, webpush
from system.models import SettingKeys, SystemSetting
from .models import ChatPushSubscription
logger = structlog.get_logger(__name__)
def _b64url_encode(raw: bytes) -> str:
 return base64.urlsafe_b64encode(raw).decode.rstrip("=")
@dataclass
class WebPushConfig:
 public_key: str
 private_key_pem: str
 subject: str
class ChatPushService:
 """聊天 Web Push 能力。"""
 @staticmethod
 async def aget_or_create_vapid_config -> WebPushConfig:
 public_setting = await SystemSetting.objects.filter(
 key=SettingKeys.WEB_PUSH_VAPID_PUBLIC_KEY,
 ).afirst
 private_setting = await SystemSetting.objects.filter(
 key=SettingKeys.WEB_PUSH_VAPID_PRIVATE_KEY,
 ).afirst
 subject_setting = await SystemSetting.objects.filter(
 key=SettingKeys.WEB_PUSH_VAPID_SUBJECT,
 ).afirst
 if public_setting and public_setting.value and private_setting and private_setting.value:
 subject = (
 subject_setting.value
 if subject_setting and subject_setting.value
 else getattr(settings, "WEB_PUSH_VAPID_SUBJECT", "mailto:friday-ai@localhost")
 )
 return WebPushConfig(
 public_key=public_setting.value,
 private_key_pem=private_setting.value,
 subject=subject,
 )
 vapid = Vapid01
 vapid.generate_keys
 public_key = _b64url_encode(
 vapid.public_key.public_bytes(
 Encoding.X962,
 PublicFormat.UncompressedPoint,
 )
 )
 private_key_pem = vapid.private_pem.decode
 subject = getattr(settings, "WEB_PUSH_VAPID_SUBJECT", "mailto:friday-ai@localhost")
 await SystemSetting.objects.aupdate_or_create(
 key=SettingKeys.WEB_PUSH_VAPID_PUBLIC_KEY,
 defaults={
 "value": public_key,
 "description": "聊天 Web Push VAPID 公钥",
 },
 )
 await SystemSetting.objects.aupdate_or_create(
 key=SettingKeys.WEB_PUSH_VAPID_PRIVATE_KEY,
 defaults={
 "value": private_key_pem,
 "description": "聊天 Web Push VAPID 私钥",
 "is_encrypted": True,
 },
 )
 await SystemSetting.objects.aupdate_or_create(
 key=SettingKeys.WEB_PUSH_VAPID_SUBJECT,
 defaults={
 "value": subject,
 "description": "聊天 Web Push VAPID Subject",
 },
 )
 logger.info("web_push_vapid_generated")
 return WebPushConfig(
 public_key=public_key,
 private_key_pem=private_key_pem,
 subject=subject,
 )
 @staticmethod
 async def asave_subscription(
 *,
 user_id: str,
 endpoint: str,
 p256dh: str,
 auth: str,
 user_agent: str = "",
 ) -> ChatPushSubscription:
 subscription, _ = await ChatPushSubscription.objects.aupdate_or_create(
 endpoint=endpoint,
 defaults={
 "user_id": user_id,
 "p256dh": p256dh,
 "auth": auth,
 "user_agent": user_agent,
 "is_active": True,
 },
 )
 return subscription
 @staticmethod
 async def adeactivate_subscription(*, user_id: str, endpoint: str) -> int:
 updated = await ChatPushSubscription.objects.filter(
 user_id=user_id,
 endpoint=endpoint,
 is_active=True,
 ).aupdate(
 is_active=False,
 updated_at=timezone.now,
 )
 return updated
 @staticmethod
 async def anotify_deep_analysis_complete(
 *,
 user_id: str | None,
 conversation_id: str,
 conversation_title: str,
 answer_preview: str,
 ) -> int:
 if not user_id:
 return 0
 subscriptions = [
 sub async for sub in ChatPushSubscription.objects.filter(
 user_id=user_id,
 is_active=True,
 )
 ]
 if not subscriptions:
 return 0
 config = await ChatPushService.aget_or_create_vapid_config
 payload = json.dumps(
 {
 "title": "深度分析完成",
 "body": f"「{conversation_title}」已完成。{answer_preview[:80]}",
 "icon": "/vite.svg",
 "tag": f"deep-analysis-{conversation_id}",
 "url": f"/chat?conversation={conversation_id}",
 "conversationId": conversation_id,
 },
 ensure_ascii=False,
 )
 delivered = 0
 for subscription in subscriptions:
 try:
 await asyncio.to_thread(
 webpush,
 subscription_info={
 "endpoint": subscription.endpoint,
 "keys": {
 "p256dh": subscription.p256dh,
 "auth": subscription.auth,
 },
 },
 data=payload,
 vapid_private_key=config.private_key_pem,
 vapid_claims={"sub": config.subject},
 ttl=3600,
 )
 subscription.last_used_at = timezone.now
 await subscription.asave(update_fields=["last_used_at", "updated_at"])
 delivered += 1
 except WebPushException as exc:
 response = getattr(exc, "response", None)
 status_code = getattr(response, "status_code", None)
 logger.warning(
 "web_push_send_failed",
 endpoint=subscription.endpoint[:80],
 status_code=status_code,
 error=str(exc),
 )
 if status_code in {404, 410}:
 subscription.is_active = False
 await subscription.asave(update_fields=["is_active", "updated_at"])
 except Exception:
 logger.exception(
 "web_push_send_error",
 endpoint=subscription.endpoint[:80],
 )
 return delivered
