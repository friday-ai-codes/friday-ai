"""社区模块摘要 LLM helper（Phase 125 / MOD-03）。

落点纪律（D-12）
================
本模块与 ``community.py`` / ``loader`` 同类：持 LLM 调用，**不进**包根
``__all__`` barrel。调用点必须经 ``use_call_source(CallSource.MODULE_SUMMARY)``
（D-09，已在 125-01 双登记）。

输入纪律（D-10 / T-125-02）
==========================
默认只喂成员元数据（路径 / 符号名 / 类型 / 度数启发式），**不喂源码正文**。
产出存 JSON 文本（``key_files`` / ``entry_points`` / ``responsibility``），
消费端统一走 ``render_module_summary``。
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

# 与 community.MIN_COMMUNITY_SIZE 对齐；调用方也保证，这里再断言一次。
MIN_SUMMARY_MEMBERS = 5
MAX_PROMPT_MEMBERS = 40


def _safe_inline(value: Any, *, limit: int = 200) -> str:
    """半可信字段消毒：去换行、截断，防 prompt/日志注入。"""
    text = redact_secrets_in_text(str(value or ""))
    text = text.replace("\n", " ").replace("\r", " ").strip()
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return str(content or "")


def _parse_summary_json(text: str) -> dict[str, Any] | None:
    candidates: list[str] = re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    candidates.append(text)
    for block in candidates:
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _fallback_fields_from_text(text: str) -> dict[str, Any]:
    """解析失败时的文本兜底：整段作 responsibility，列表字段留空。"""
    cleaned = redact_secrets_in_text((text or "").strip())
    return {
        "key_files": [],
        "entry_points": [],
        "responsibility": cleaned[:800] if cleaned else "",
    }


def _normalize_summary(raw: Mapping[str, Any]) -> dict[str, Any]:
    def _str_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            s = _safe_inline(item, limit=240)
            if s:
                out.append(s)
        return out[:40]

    responsibility = _safe_inline(raw.get("responsibility"), limit=800)
    return {
        "key_files": _str_list(raw.get("key_files")),
        "entry_points": _str_list(raw.get("entry_points")),
        "responsibility": responsibility,
    }


def build_module_summary_prompt(
    members: Sequence[Mapping[str, Any]],
    *,
    community: Mapping[str, Any] | None = None,
) -> str:
    """构建元数据-only prompt（不含源码正文，T-125-02）。"""
    ranked = sorted(
        members,
        key=lambda m: (-int(m.get("degree") or 0), str(m.get("file_path") or ""), str(m.get("name") or "")),
    )[:MAX_PROMPT_MEMBERS]

    lines: list[str] = [
        "根据下列符号社区成员元数据，归纳该模块的关键文件、入口与职责。",
        "只输出 JSON：{\"key_files\":[...],\"entry_points\":[...],\"responsibility\":\"...\"}",
        "不要输出源码，不要编造未给出的路径。",
        "",
        "成员（file_path / name / symbol_type / degree）：",
    ]
    for m in ranked:
        lines.append(
            "- {file_path} | {name} | {symbol_type} | degree={degree}".format(
                file_path=_safe_inline(m.get("file_path"), limit=160),
                name=_safe_inline(m.get("name"), limit=80),
                symbol_type=_safe_inline(m.get("symbol_type"), limit=40),
                degree=int(m.get("degree") or 0),
            )
        )
    if community:
        key = _safe_inline(community.get("community_key"), limit=64)
        count = int(community.get("member_count") or len(members))
        if key:
            lines.append("")
            lines.append(f"community_key={key}; member_count={count}")
    return "\n".join(lines)


def render_module_summary(summary: str) -> str:
    """将落库 JSON（或纯文本）渲染为稳定 markdown，供消费端单一入口。"""
    text = (summary or "").strip()
    if not text:
        return ""
    parsed = _parse_summary_json(text)
    if parsed is None:
        return redact_secrets_in_text(text)

    data = _normalize_summary(parsed)
    parts: list[str] = ["## 模块摘要"]
    key_files = data["key_files"]
    entry_points = data["entry_points"]
    responsibility = data["responsibility"]
    if key_files:
        parts.append("### 关键文件")
        parts.extend(f"- {_safe_inline(f)}" for f in key_files)
    if entry_points:
        parts.append("### 入口")
        parts.extend(f"- {_safe_inline(e)}" for e in entry_points)
    if responsibility:
        parts.append("### 职责")
        parts.append(responsibility)
    return "\n".join(parts).strip()


def _system_prompt() -> str:
    return (
        "你是代码仓库模块摘要助手。根据符号社区成员的文件路径、符号名、类型与度数，"
        "输出该模块的关键文件、入口点与职责叙述。"
        "只输出 JSON 对象，字段为 key_files（字符串数组）、entry_points（字符串数组）、"
        "responsibility（短段落）。不要输出 Markdown 代码块以外的解释，不要编造源码。"
    )


async def agenerate_module_summary(
    members: Sequence[Mapping[str, Any]],
    community: Mapping[str, Any] | None = None,
    *,
    provider_credential_id: str | None = None,
    model: str | None = None,
) -> str | None:
    """单轮 LLM 生成模块摘要 JSON 文本；失败返回 ``None``（不抛）。

    规模 &lt; ``MIN_SUMMARY_MEMBERS`` 直接返回 None（D-04/D-11）。
    """
    started = time.monotonic()
    member_count = len(members)
    community_key = ""
    if community:
        community_key = str(community.get("community_key") or "")

    try:
        logger.info(
            "code_graph_module_summary_started",
            category="sampling",
            component="code_graph",
            member_count=member_count,
            community_key=community_key or None,
        )
    except Exception:  # noqa: BLE001
        pass

    if member_count < MIN_SUMMARY_MEMBERS:
        try:
            logger.info(
                "code_graph_module_summary_completed",
                category="sampling",
                component="code_graph",
                member_count=member_count,
                community_key=community_key or None,
                skipped="size_below_threshold",
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001
            pass
        return None

    from langchain_core.messages import HumanMessage, SystemMessage

    from agents.call_source import CallSource, use_call_source
    from agents.llm_concurrency import acquire_llm_slot
    from agents.llm_factory import build_chat_model
    from services.provider_config import ProviderConfigService, ProviderMissingError

    try:
        if provider_credential_id:
            resolved = await ProviderConfigService.aresolve_or_error(
                node_config={"provider_credential_id": provider_credential_id}
            )
            if isinstance(resolved, ProviderMissingError):
                raise RuntimeError(str(resolved))
        else:
            resolved = await ProviderConfigService.aresolve()

        model_name = (model or "").strip() or (getattr(resolved, "extra", None) or {}).get(
            "default_model", ""
        )
        if not model_name:
            raise RuntimeError("no_default_model")

        model_obj = build_chat_model(resolved, model_name, streaming=False)
        # temperature=0 若模型支持则绑定；不支持则忽略。
        try:
            model_obj = model_obj.bind(temperature=0)
        except Exception:  # noqa: BLE001
            pass

        messages = [
            SystemMessage(content=_system_prompt()),
            HumanMessage(content=build_module_summary_prompt(members, community=community)),
        ]
        cred_id = str(getattr(resolved, "credential_id", "") or provider_credential_id or "")
        max_c = int(getattr(resolved, "max_concurrency", 0) or 0)
        with use_call_source(CallSource.MODULE_SUMMARY):
            async with acquire_llm_slot(cred_id, max_c):
                response = await model_obj.ainvoke(messages)
    except Exception as exc:  # noqa: BLE001 — fail-soft
        try:
            logger.warning(
                "code_graph_module_summary_failed",
                category="sampling",
                component="code_graph",
                member_count=member_count,
                community_key=community_key or None,
                error=redact_secrets_in_text(str(exc)),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001
            pass
        return None

    try:
        raw_text = _content_to_text(getattr(response, "content", response))
        parsed = _parse_summary_json(raw_text)
        if parsed is None:
            normalized = _fallback_fields_from_text(raw_text)
        else:
            normalized = _normalize_summary(parsed)
        if not normalized.get("responsibility") and not normalized.get("key_files"):
            raise RuntimeError("empty_summary_payload")
        summary_json = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    except Exception as exc:  # noqa: BLE001
        try:
            logger.warning(
                "code_graph_module_summary_failed",
                category="sampling",
                component="code_graph",
                member_count=member_count,
                community_key=community_key or None,
                error=redact_secrets_in_text(str(exc)),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001
            pass
        return None

    # D-01/D-06：把模型与生成时间写回可变 community，供落库复用。
    if isinstance(community, dict):
        try:
            from django.utils import timezone

            community["summary_model"] = str(model_name or "")[:128] or None
            community["summary_generated_at"] = timezone.now()
        except Exception:  # noqa: BLE001 — 元数据失败不丢摘要正文
            pass

    try:
        logger.info(
            "code_graph_module_summary_completed",
            category="sampling",
            component="code_graph",
            member_count=member_count,
            community_key=community_key or None,
            summary_model=str(model_name or "") or None,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
    except Exception:  # noqa: BLE001
        pass
    return summary_json


__all__ = [
    "MIN_SUMMARY_MEMBERS",
    "agenerate_module_summary",
    "build_module_summary_prompt",
    "render_module_summary",
]
