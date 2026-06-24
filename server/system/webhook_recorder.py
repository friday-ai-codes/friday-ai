"""入站 webhook 原始留痕统一收口（LOG-07）。

把飞书 / Git push / 容器回调等各入口的**原始** payload + 请求头在入库前统一脱敏，
写入 ``InboundWebhookEvent``，供"出事时谁触发的、原始可回放"的下钻查看（71-05）。

设计要点（per 71-CONTEXT LOG-07 + LOGGING-SPEC §1.5）：

- **入库前必经脱敏**（脱敏不可绕过）：``headers`` 经 ``redact_for_ledger`` 结构化脱敏；
  ``raw_body`` 若为 dict / list 经 ``redact_for_ledger`` 后 ``json.dumps``；若为字符串则
  尝试 ``json.loads`` 后走结构化脱敏（命中字段名命门），失败再用 ``redact_secrets_in_text``
  字符串兜底。过大 body 截断（``_MAX_BODY_CHARS``）防 ``TextField`` 膨胀（T-71-05-04）。
- **best-effort 绝不反噬业务**（T-71-05-05）：整体 try/except 吞掉留痕异常，失败仅 warning，
  绝不打断 webhook 主流程。
- ``record_inbound_webhook`` 为异步收口（单条本地 insert，开销极低，异步入口直接 ``await``，
  确定可测）；``record_inbound_webhook_bg`` 为同步上下文 / 需脱离请求生命周期时的后台派发包装。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import structlog

from common.logging import redact_secrets_in_text
from interactions.redaction import redact_for_ledger

from .models import InboundWebhookEvent

logger = structlog.get_logger(__name__)

# raw_body 入库上限（字符）：截断防 TextField 膨胀 + DoS（T-71-05-04）。
_MAX_BODY_CHARS = 64 * 1024

# 已知 webhook 种类（与 InboundWebhookEvent.kind / 71-CONTEXT 对齐）。
KIND_FEISHU = "feishu"
KIND_WORKFLOW = "workflow"
KIND_GIT_PUSH = "git_push"
KIND_CONTAINER_CALLBACK = "container_callback"


def client_ip(request: Any) -> str:
    """从请求 META 提取来源 IP（X-Forwarded-For 优先，回退 REMOTE_ADDR）。

    best-effort：任何异常回退空串，绝不反噬主流程。兼容 DRF ``Request`` 与
    Django ``HttpRequest``（二者均有 ``.META``）。
    """
    try:
        meta = getattr(request, "META", {}) or {}
        forwarded = str(meta.get("HTTP_X_FORWARDED_FOR", "") or "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return str(meta.get("REMOTE_ADDR", "") or "")
    except Exception:  # noqa: BLE001 — 取 IP 绝不反噬业务
        return ""


def _redact_headers(headers: Mapping[str, Any] | None) -> dict[str, Any]:
    """请求头入库前结构化脱敏（Authorization / token 等字段名命中即整值替换）。"""
    if not headers:
        return {}
    try:
        return redact_for_ledger(dict(headers))
    except Exception:  # noqa: BLE001 — 脱敏失败保守返回空，绝不落明文
        return {}


def _redact_body(raw_body: Any) -> str:
    """原始 body 入库前脱敏 + 截断，统一返回字符串。

    dict / list → ``redact_for_ledger`` 后 ``json.dumps``；字符串先尝试 JSON 解析走
    结构化脱敏（命中字段名命门），失败再 ``redact_secrets_in_text`` 字符串兜底。
    """
    try:
        if isinstance(raw_body, (dict, list)):
            text = json.dumps(redact_for_ledger(raw_body), ensure_ascii=False)
        else:
            raw_str = str(raw_body or "")
            parsed: Any = None
            try:
                parsed = json.loads(raw_str)
            except Exception:  # noqa: BLE001 — 非 JSON 字符串走文本兜底
                parsed = None
            if isinstance(parsed, (dict, list)):
                text = json.dumps(redact_for_ledger(parsed), ensure_ascii=False)
            else:
                text = redact_secrets_in_text(raw_str)
    except Exception:  # noqa: BLE001 — 脱敏失败保守置空，绝不落明文
        return ""
    if len(text) > _MAX_BODY_CHARS:
        text = text[:_MAX_BODY_CHARS]
    return text


async def record_inbound_webhook(
    *,
    kind: str,
    raw_body: Any,
    headers: Mapping[str, Any] | None = None,
    source_ip: str = "",
    user_id: str = "system",
    verified: bool = False,
    correlation: dict[str, Any] | None = None,
) -> None:
    """脱敏后把一条入站 webhook 原始留痕写入 ``InboundWebhookEvent``（异步收口）。

    **入库前必经脱敏**（headers / raw_body 各自脱敏 + 截断）。整体 best-effort：
    任何异常仅 warning 后吞掉，绝不反噬 webhook 主流程（T-71-05-05）。

    Args:
        kind: webhook 种类（feishu / workflow / git_push / container_callback）。
        raw_body: 原始请求体（dict / list / str / bytes-decoded）。
        headers: 原始请求头（脱敏后入库）。
        source_ip: 来源 IP（``client_ip`` 提取）。
        user_id: 触发用户 id（无则 ``"system"``）。
        verified: 是否已通过签名 / token 校验。
        correlation: 关联键（event_uuid / repository_id / session_id 等，不复制正文）。
    """
    try:
        await InboundWebhookEvent.objects.acreate(
            kind=str(kind or "")[:32],
            source_ip=str(source_ip or "")[:64],
            headers=_redact_headers(headers),
            raw_body=_redact_body(raw_body),
            user_id=str(user_id or "system")[:64],
            verified=bool(verified),
            correlation=correlation or {},
        )
        logger.info(
            "inbound_webhook_recorded",
            category="caller",
            component="webhook_recorder",
            kind=kind,
            verified=bool(verified),
        )
    except Exception:  # noqa: BLE001 — 留痕 best-effort，绝不反噬 webhook 主流程
        logger.warning(
            "inbound_webhook_record_failed",
            category="sampling",
            component="webhook_recorder",
            kind=kind,
        )


def record_inbound_webhook_bg(
    *,
    kind: str,
    raw_body: Any,
    headers: Mapping[str, Any] | None = None,
    source_ip: str = "",
    user_id: str = "system",
    verified: bool = False,
    correlation: dict[str, Any] | None = None,
) -> None:
    """同步上下文 / 需脱离请求生命周期的后台派发包装（沿用 feishu 后台投递范式）。

    把 ``record_inbound_webhook`` 调度到常驻后台 worker（``run_in_background``），避免
    阻塞 webhook 响应。best-effort：派发失败仅 warning。
    """
    try:
        from services.background_runner import run_in_background

        run_in_background(
            lambda: record_inbound_webhook(
                kind=kind,
                raw_body=raw_body,
                headers=headers,
                source_ip=source_ip,
                user_id=user_id,
                verified=verified,
                correlation=correlation,
            ),
            name=f"inbound-webhook:{kind}",
            initiated_by_user_id=user_id or "system",
        )
    except Exception:  # noqa: BLE001 — 后台派发失败绝不反噬业务
        logger.warning(
            "inbound_webhook_bg_schedule_failed",
            category="sampling",
            component="webhook_recorder",
            kind=kind,
        )


__all__ = [
    "KIND_CONTAINER_CALLBACK",
    "KIND_FEISHU",
    "KIND_GIT_PUSH",
    "KIND_WORKFLOW",
    "client_ip",
    "record_inbound_webhook",
    "record_inbound_webhook_bg",
]
