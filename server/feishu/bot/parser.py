"""Normalize inbound Feishu IM payloads into a stable bot message shape."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

_BOT_MENTION_RE = re.compile(r"@[^\s]+")


@dataclass(slots=True)
class InboundLarkMessage:
    """Normalized Feishu inbound message."""

    event_id: str
    chat_id: str
    chat_type: str
    message_id: str
    sender_open_id: str
    sender_type: str
    sender_is_bot: bool
    message_type: str
    normalized_text: str
    mentioned_bot: bool
    has_effective_body: bool
    quote_message_id: str
    parent_id: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)


def _loads_content(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if not content:
        return {}
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return {"text": content}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {"value": content}


def _clean_text(text: str) -> str:
    text = _BOT_MENTION_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_text_and_mentions(message_type: str, content: dict[str, Any]) -> tuple[str, bool, list[dict[str, Any]]]:
    if message_type == "text":
        text = str(content.get("text", ""))
        mentions = content.get("mentions", [])
        return text, bool(mentions), []

    if message_type == "post":
        texts: list[str] = []
        mentioned = False
        attachments: list[dict[str, Any]] = []
        for lang_content in content.values():
            if not isinstance(lang_content, dict):
                continue
            for para in lang_content.get("content", []):
                for elem in para:
                    tag = elem.get("tag", "")
                    if tag == "text":
                        texts.append(str(elem.get("text", "")))
                    elif tag == "at":
                        mentioned = True
                    elif tag in {"img", "media", "file"}:
                        attachments.append({
                            "tag": tag,
                            "file_key": elem.get("file_key", ""),
                            "image_key": elem.get("image_key", ""),
                            "name": elem.get("file_name", "") or elem.get("title", ""),
                        })
        return " ".join(texts), mentioned, attachments

    if message_type == "image":
        return "", False, [{
            "tag": "image",
            "image_key": content.get("image_key", ""),
            "name": content.get("file_name", "") or "image",
        }]

    if message_type == "file":
        return str(content.get("file_name", "")), False, [{
            "tag": "file",
            "file_key": content.get("file_key", ""),
            "name": content.get("file_name", ""),
        }]

    if message_type == "audio":
        return "", False, [{"tag": "audio", "file_key": content.get("file_key", "")}]

    fallback = str(content.get("text", "") or content)
    return fallback, False, []


def _extract_mentions(raw_message: dict[str, Any], content: dict[str, Any]) -> bool:
    mentions = raw_message.get("mentions") or content.get("mentions") or []
    if mentions:
        return True
    return False


def extract_message_attachments(raw_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """从原始飞书 payload 恢复规范化附件列表。"""
    message = raw_payload.get("event", {}).get("message", {})
    content = _loads_content(message.get("content", {}))
    _, _, attachments = _extract_text_and_mentions(
        str(message.get("message_type", "text")),
        content,
    )
    return attachments


def normalize_im_message(raw_payload: dict[str, Any]) -> InboundLarkMessage:
    """Normalize webhook or websocket IM payload."""

    header = raw_payload.get("header", {})
    event = raw_payload.get("event", {})
    message = event.get("message", {})
    sender = event.get("sender", {})

    content = _loads_content(message.get("content", {}))
    text, mentioned_from_body, attachments = _extract_text_and_mentions(
        message.get("message_type", "text"),
        content,
    )

    normalized_text = _clean_text(text)

    quote_message_id = (
        message.get("parent_id")
        or message.get("root_id")
        or content.get("quote_message_id")
        or content.get("parent_id")
        or ""
    )

    sender_type = str(sender.get("sender_type") or sender.get("tenant_key") or "")
    sender_open_id = str(sender.get("sender_id", {}).get("open_id", ""))
    sender_is_bot = sender_type == "bot" or bool(sender.get("sender_id", {}).get("union_id")) and sender_open_id == ""

    mentioned_bot = mentioned_from_body or _extract_mentions(message, content)
    has_effective_body = bool(normalized_text or attachments)

    return InboundLarkMessage(
        event_id=str(header.get("event_id", "")),
        chat_id=str(message.get("chat_id", "")),
        chat_type=str(message.get("chat_type", "")),
        message_id=str(message.get("message_id", "")),
        sender_open_id=sender_open_id,
        sender_type=sender_type,
        sender_is_bot=sender_is_bot,
        message_type=str(message.get("message_type", "text")),
        normalized_text=normalized_text,
        mentioned_bot=mentioned_bot,
        has_effective_body=has_effective_body,
        quote_message_id=str(quote_message_id),
        parent_id=str(message.get("parent_id", "") or content.get("parent_id", "")),
        attachments=attachments,
        raw_payload=raw_payload,
    )
