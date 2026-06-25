"""系统告警通知三通道分发出口（ALERT-03）。

给 74-02 评估器一个干净的"产生 firing/resolved 事件后调一次
``notify_channels`` 即完成多通道通知"的单一出口：按 ``rule.channels`` 子集分发
**EMAIL（Django SMTP）/ 飞书（复用 FeishuIMService）/ webhook（httpx POST + SSRF
防护）** 三通道，各通道独立 best-effort——任一通道失败不影响其它通道，更绝不反噬
评估主流程（最高优先级，T-74-03-03/04）。

安全契约（不可绕过）：
- 邮件 / webhook / 飞书正文与所有异常 str 入外发/日志前必经
  ``redact_secrets_in_text`` 脱敏（T-74-03-01，纵深防御）；邮件失败日志只记收件人
  数量、绝不记明文地址。
- webhook URL 经 scheme 白名单 + ``_is_internal_host`` 拦截内网/loopback/link-local
  /localhost/.local（逐字复用 ``workflows.hooks.builtin.AlertRuleHook`` 范式，
  T-74-03-02）。
- 各通道 + 最外层均 try/except 兜底，绝不把异常冒泡回评估器；通知失败仅 warning。
"""

from __future__ import annotations

import ipaddress
import json
import time
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog
from asgiref.sync import sync_to_async

from common.logging import redact_secrets_in_text
from system.models import SettingKeys
from system.settings_service import aget_bool_setting, aget_setting

logger = structlog.get_logger(__name__)

# severity → 飞书卡片 header template（P0 最高 → red）。
_SEVERITY_TEMPLATE = {"P0": "red", "P1": "orange", "P2": "blue"}

# httpx / 飞书外发超时（秒），防挂起拖垮评估线程（T-74-03-03）。
_HTTP_TIMEOUT = 10


async def notify_channels(event: Any, channels: list[str]) -> dict[str, str]:
    """单一分发出口：按 ``channels`` 子集分发三通道并回写 AlertEvent。

    Args:
        event: 74-01 ``AlertEvent`` 实例。
        channels: ``rule.channels`` 子集（``email`` / ``feishu`` / ``webhook``）。

    Returns:
        ``{"email": <status>, "feishu": <status>, "webhook": <status>}``（供测试断言）；
        最外层兜底异常时返回空 dict。任何情况下绝不抛回评估器。
    """
    started = time.perf_counter()
    channels = channels or []
    email_status = "pending"
    feishu_ok = False
    webhook_ok = False

    try:
        if "email" in channels:
            email_status = await _send_email(event)
        if "feishu" in channels:
            feishu_ok = await _send_feishu(event)
        if "webhook" in channels:
            webhook_ok = await _send_webhook(event)

        # 汇总实际成功的通道（webhook/feishu 仅 True 才计入）。
        notified: list[str] = []
        if "email" in channels and email_status == "sent":
            notified.append("email")
        if feishu_ok:
            notified.append("feishu")
        if webhook_ok:
            notified.append("webhook")

        # 回写 AlertEvent（整段独立 try/except，回写失败仅 warning 不反噬）。
        try:
            update_fields = ["notified_channels"]
            event.notified_channels = notified
            # 仅选了 email 才回写 email_sent（否则保留 74-01 默认 pending）。
            if "email" in channels:
                event.email_sent = email_status
                update_fields.append("email_sent")
            await event.asave(update_fields=update_fields)
        except Exception as exc:  # noqa: BLE001 — 回写失败绝不反噬评估
            logger.warning(
                "alert_notify_persist_failed",
                category="caller",
                component="alerting",
                source="scheduler",
                event_id=getattr(event, "id", None),
                error=redact_secrets_in_text(str(exc)),
            )

        logger.info(
            "alert_notified",
            category="caller",
            component="alerting",
            source="scheduler",
            event_id=getattr(event, "id", None),
            severity=getattr(event, "severity", ""),
            channels=channels,
            notified=notified,
            email_status=email_status,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

        return {
            "email": email_status,
            "feishu": "sent" if feishu_ok else "skipped",
            "webhook": "sent" if webhook_ok else "skipped",
        }
    except Exception as exc:  # noqa: BLE001 — 通知绝不反噬评估（最外层兜底）
        logger.warning(
            "alert_notify_failed",
            category="caller",
            component="alerting",
            source="scheduler",
            event_id=getattr(event, "id", None),
            error=redact_secrets_in_text(str(exc)),
        )
        return {}


async def _send_email(event: Any) -> str:
    """EMAIL 通道：走 Django SMTP，按 severity 发邮件。

    Returns:
        ``"sent"`` / ``"skipped"``（未开启/未配置/无收件人）/ ``"failed"``（发送异常）。
        绝不抛——SMTP 未配置或失败都不算评估失败。
    """
    try:
        from django.conf import settings

        enabled = await aget_bool_setting(SettingKeys.ALERT_EMAIL_ENABLED, False)
        host = getattr(settings, "EMAIL_HOST", "")
        if not enabled or not host:
            # 未开启 / SMTP 未配置 → 降级 skipped，不算失败。
            return "skipped"

        recipients = _parse_recipients(
            await aget_setting(SettingKeys.ALERT_EMAIL_RECIPIENTS, "")
        )
        if not recipients:
            return "skipped"

        subject = f"[{getattr(event, 'severity', '')}] {getattr(event, 'title_zh', '') or '系统告警'}"
        body = redact_secrets_in_text(_build_text_body(event))

        from django.core.mail import send_mail

        await sync_to_async(send_mail, thread_sensitive=True)(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            recipients,
            fail_silently=False,
        )
        return "sent"
    except Exception as exc:  # noqa: BLE001 — 邮件失败绝不反噬评估
        # 只记收件人数量，绝不记明文地址；异常文本脱敏。
        logger.warning(
            "alert_email_failed",
            category="caller",
            component="alerting",
            source="scheduler",
            event_id=getattr(event, "id", None),
            severity=getattr(event, "severity", ""),
            error=redact_secrets_in_text(str(exc)),
        )
        return "failed"


async def _send_feishu(event: Any) -> bool:
    """飞书通道：复用 ``FeishuIMService`` 系统默认凭证发卡片。

    Returns:
        成功 True；未配置 chat_id / 发送异常 → False（绝不抛、绝不反噬）。
    """
    try:
        chat_id = await aget_setting(SettingKeys.ALERT_FEISHU_CHAT_ID, "")
        if not chat_id:
            return False

        from services.feishu_im import FeishuIMService

        im = await FeishuIMService.create(None)
        severity = getattr(event, "severity", "")
        template = _SEVERITY_TEMPLATE.get(severity, "blue")
        title = getattr(event, "title_zh", "") or "系统告警"
        content = redact_secrets_in_text(_build_text_body(event))
        # 镜像 AlertRuleHook._send_feishu 的 card dict 结构，不引新依赖。
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"系统告警：{title}"},
                "template": template,
            },
            "elements": [{"tag": "markdown", "content": content}],
        }
        await im.send_card(receive_id=chat_id, receive_id_type="chat_id", card=card)
        return True
    except Exception as exc:  # noqa: BLE001 — 飞书失败绝不反噬评估
        logger.warning(
            "alert_feishu_failed",
            category="caller",
            component="alerting",
            source="scheduler",
            event_id=getattr(event, "id", None),
            error=redact_secrets_in_text(str(exc)),
        )
        return False


async def _send_webhook(event: Any) -> bool:
    """webhook 通道：httpx POST 脱敏 payload，含 SSRF 防护。

    Returns:
        2xx/3xx 成功 True；未配置 / SSRF 拦截 / >=400 / 异常 → False（绝不反噬）。
    """
    try:
        url = await aget_setting(SettingKeys.ALERT_WEBHOOK_URL, "")
        if not url:
            return False

        # SSRF 防护：scheme 白名单 + 内网地址拦截（逐字复用 AlertRuleHook 范式）。
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            logger.warning(
                "alert_webhook_failed",
                category="caller",
                component="alerting",
                source="scheduler",
                event_id=getattr(event, "id", None),
                error=f"unsupported scheme: {parsed.scheme}",
            )
            return False
        if _is_internal_host(parsed.hostname or ""):
            logger.warning(
                "alert_webhook_failed",
                category="caller",
                component="alerting",
                source="scheduler",
                event_id=getattr(event, "id", None),
                error="internal host blocked (SSRF)",
            )
            return False

        payload = json.dumps(
            {
                "event": "system_alert",
                "severity": getattr(event, "severity", ""),
                "title": getattr(event, "title_zh", ""),
                "rule_info": getattr(event, "rule_info", {}),
                "target": getattr(event, "target", {}),
                "status": getattr(event, "status", ""),
                "started_at": _isoformat(getattr(event, "started_at", None)),
            },
            ensure_ascii=False,
            default=str,
        )
        redacted = redact_secrets_in_text(payload)

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(url, content=redacted)
        if resp.status_code >= 400:
            logger.warning(
                "alert_webhook_failed",
                category="caller",
                component="alerting",
                source="scheduler",
                event_id=getattr(event, "id", None),
                status_code=resp.status_code,
            )
            return False
        return True
    except Exception as exc:  # noqa: BLE001 — webhook 失败绝不反噬评估
        logger.warning(
            "alert_webhook_failed",
            category="caller",
            component="alerting",
            source="scheduler",
            event_id=getattr(event, "id", None),
            error=redact_secrets_in_text(str(exc)),
        )
        return False


# === 内部 helper ===


def _parse_recipients(raw: str) -> list[str]:
    """解析收件人配置：兼容逗号分隔与 JSON 列表，逐项 strip 去空。"""
    if not raw:
        return []
    raw = raw.strip()
    parsed: list[str] | None = None
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                parsed = [str(item) for item in data]
        except (ValueError, TypeError):
            parsed = None
    if parsed is None:
        parsed = raw.split(",")
    return [item.strip() for item in parsed if item and item.strip()]


def _build_text_body(event: Any) -> str:
    """构造纯文本正文（简洁，per 74-CONTEXT 倾向纯文本）。"""
    rule_info = getattr(event, "rule_info", {}) or {}
    expr = rule_info.get("expr", "") if isinstance(rule_info, dict) else ""
    lines = [
        getattr(event, "title_zh", "") or "系统告警",
        f"级别: {getattr(event, 'severity', '')}",
        f"状态: {getattr(event, 'status', '')}",
    ]
    if expr:
        lines.append(f"规则: {expr}")
    current = getattr(event, "current_value", None)
    if current is not None:
        lines.append(f"当前值: {current}")
    started_at = _isoformat(getattr(event, "started_at", None))
    if started_at:
        lines.append(f"开始时间: {started_at}")
    return "\n".join(lines)


def _isoformat(value: Any) -> str:
    """安全 isoformat：None / 无 isoformat 方法回退 str。"""
    if value is None:
        return ""
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)


def _is_internal_host(hostname: str) -> bool:
    """SSRF 内网地址判定（与 AlertRuleHook._is_internal_host 同源逻辑）。

    拦截 private / loopback / link-local IP 与 localhost / ``.local`` 主机名。
    """
    try:
        ip = ipaddress.ip_address(hostname)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return hostname in ("localhost",) or hostname.endswith(".local")
