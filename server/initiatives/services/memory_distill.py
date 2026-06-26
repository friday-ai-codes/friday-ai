"""MemoryDistiller —— 从成员会话提炼项目记忆草稿（MEM-04）。

LLM 读成员会话消息 → 提炼一条候选记忆 → **脱敏** → ``MemoryService.create_draft``
（pending，**绝不自动写 active**）。是**新增 LLM 调用**：

- ``call_source="memory_distill"``（LOGGING-SPEC §4.1，Phase 80 新增）；
- 收尾经 ``arecord_llm_usage`` 上报请求/token/TTFT/上游错误码（best-effort，绝不反噬）；
- **成员校验 fail-closed**（仅项目成员可触发蒸馏，MEM-02）；
- 整体 fail-soft：LLM 缺凭证/异常 → 返回 ``None``，不抛、不产草稿。

LLM 调用经 ``agents.llm_factory.build_chat_model`` 统一 seam（测试 mock 点 = ``_acall_llm``）。

Phase 86 复用：``distill_hook_writeback`` 为 IDE stop hook active 直写前的可选精炼
（``call_source="ide_hook_distill"``，best-effort，失败回退原始 content），复用同一 LLM seam。
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

import structlog
from langchain_core.messages import HumanMessage

from agents.call_source import CallSource, use_call_source
from common.logging import redact_secrets_in_text
from initiatives.models import ProjectMember
from initiatives.services.memory_service import MemoryPermissionError, MemoryService
from interactions.ledger import arecord_llm_usage, parse_upstream_status
from services.provider_config import (
    ProviderConfigService,
    ProviderMissingError,
    aget_legacy_anthropic_config,
)

logger = structlog.get_logger(__name__)

__all__ = ["MemoryDistiller"]

_COMPONENT = "initiatives"
_DISTILL_MODEL_FALLBACK = "claude-sonnet-4-20250514"

_DISTILL_PROMPT = (
    "你是项目记忆提炼助手。请阅读以下项目成员会话片段，提炼出**一条**值得沉淀为项目"
    "长期记忆的关键结论/决策/约束（自由文本，简洁，单条，不超过 200 字）。"
    "若无值得沉淀的内容，只输出 NONE。只输出记忆正文或 NONE，不要解释。\n\n"
    "会话片段：\n{conversation_text}"
)

# Phase 86：IDE stop hook 组织上下文 + 用户改动 → 精炼一条记忆条目（active 直写前可选蒸馏）。
_HOOK_DISTILL_PROMPT = (
    "你是项目记忆提炼助手。以下是一次 IDE 编码会话结束时组织的上下文与用户改动摘要，"
    "请提炼出**一条**值得沉淀为项目长期记忆的关键结论/决策/约束（自由文本，简洁，单条，"
    "不超过 200 字）。若无值得沉淀的内容，只输出 NONE。只输出记忆正文或 NONE，不要解释。\n\n"
    "会话上下文：\n{conversation_text}"
)


class MemoryDistiller:
    """从成员会话蒸馏记忆草稿（MEM-04）。"""

    async def distill_to_draft(
        self,
        *,
        project_id: Any,
        conversation_text: str,
        proposed_by: Any,
        source_conversation_id: Any = None,
        initiated_by_user_id: Any = None,
    ) -> Any:
        """从会话文本蒸馏记忆草稿（pending）。返回 ``ProjectMemoryDraft`` 或 ``None``。

        成员校验 fail-closed（非成员抛 ``MemoryPermissionError``）；LLM/脱敏失败 fail-soft
        返回 ``None``（绝不自动写 active 记忆）。
        """
        # MEM-02：仅项目成员可触发蒸馏（fail-closed）。
        is_member = await self._is_member(project_id, proposed_by)
        if not is_member:
            raise MemoryPermissionError("仅项目成员可从会话蒸馏记忆草稿")

        candidate = await self._acall_llm(conversation_text)
        if not candidate:
            return None
        candidate = candidate.strip()
        if not candidate or candidate.upper() == "NONE":
            logger.info(
                "memory_distill_no_candidate",
                project_id=str(project_id),
                component=_COMPONENT,
                category="sampling",
            )
            return None

        # 入库前脱敏不可绕过（create_draft 内部还会再脱敏一次，双保险）。
        redacted = redact_secrets_in_text(candidate)
        draft = await MemoryService().create_draft(
            project_id=project_id,
            content=redacted,
            proposed_by=proposed_by,
            source_conversation_id=source_conversation_id,
            initiated_by_user_id=initiated_by_user_id,
            _skip_member_check=True,  # 成员校验已在上方完成
        )
        logger.info(
            "memory_distill_draft_created",
            project_id=str(project_id),
            draft_id=str(draft.id),
            component=_COMPONENT,
            category="caller",
        )
        return draft

    @staticmethod
    async def _is_member(project_id: Any, user: Any) -> bool:
        uid = getattr(user, "id", None)
        if uid is None:
            return False
        return await ProjectMember.objects.filter(
            project_id=project_id, user_id=uid
        ).aexists()

    async def distill_hook_writeback(self, *, text: str) -> str | None:
        """IDE stop hook active 直写前的可选精炼（Phase 86，call_source=ide_hook_distill）。

        组织上下文 + 用户改动 → **一条**精炼记忆条目（脱敏后返回）。**纯 best-effort**：
        LLM 缺凭证/异常/无候选（NONE）→ 返回 ``None``（调用方回退原始 content，绝不反噬编码）。
        不做成员校验（active 写回入口 ``record_hook_writeback`` 已成员校验 + 入库再脱敏）。
        """
        candidate = await self._acall_llm(
            text,
            prompt_template=_HOOK_DISTILL_PROMPT,
            call_source=CallSource.IDE_HOOK_DISTILL.value,
        )
        if not candidate:
            return None
        candidate = candidate.strip()
        if not candidate or candidate.upper() == "NONE":
            return None
        # 蒸馏产物入库前脱敏不可绕过（active 写回入口还会再脱敏一次，双保险）。
        return redact_secrets_in_text(candidate)

    async def _acall_llm(
        self,
        conversation_text: str,
        *,
        prompt_template: str = _DISTILL_PROMPT,
        call_source: str = CallSource.MEMORY_DISTILL.value,
    ) -> str | None:
        """单轮 LLM 提炼（默认 call_source=memory_distill；hook 蒸馏传 ide_hook_distill）。
        失败 fail-soft 返回 None。

        测试 mock 点：patch 本方法即可绕过真实 provider。
        """
        try:
            resolved = await ProviderConfigService.aresolve_or_error()
        except Exception:  # noqa: BLE001 — 解析异常 fail-soft
            return None
        if isinstance(resolved, ProviderMissingError):
            logger.warning(
                "memory_distill_skipped",
                reason="no_credential",
                call_source=call_source,
                component=_COMPONENT,
                category="sampling",
            )
            return None

        from agents.llm_factory import build_chat_model

        legacy = await aget_legacy_anthropic_config()
        model = legacy.get("default_model") or _DISTILL_MODEL_FALLBACK
        prompt = prompt_template.format(conversation_text=conversation_text[:6000])

        _start = perf_counter()
        ttft_ms: int | None = None
        try:
            with use_call_source(call_source):
                chat_model = build_chat_model(
                    resolved, model, max_output_tokens=512, streaming=False
                )
                ai_msg = await chat_model.ainvoke([HumanMessage(content=prompt)])
            ttft_ms = int((perf_counter() - _start) * 1000)
        except Exception as exc:  # noqa: BLE001 — LLM 失败 fail-soft + 上游错误码留痕
            await self._record_usage(
                resolved,
                model,
                ttft_ms=None,
                upstream_status_code=parse_upstream_status(exc),
                call_source=call_source,
            )
            logger.warning(
                "memory_distill_llm_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                call_source=call_source,
                component=_COMPONENT,
                category="sampling",
            )
            return None

        usage = self._extract_usage(ai_msg)
        await self._record_usage(
            resolved,
            model,
            ttft_ms=ttft_ms,
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            duration_ms=int((perf_counter() - _start) * 1000),
            call_source=call_source,
        )
        return self._extract_text(ai_msg)

    @staticmethod
    def _extract_text(ai_msg: Any) -> str:
        content = getattr(ai_msg, "content", "")
        if isinstance(content, list):
            parts = [
                str(b.get("text", ""))
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            return "".join(parts)
        return str(content) if content else ""

    @staticmethod
    def _extract_usage(ai_msg: Any) -> dict[str, int]:
        usage = getattr(ai_msg, "usage_metadata", None)
        if not isinstance(usage, dict):
            return {}
        return {
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
        }

    @staticmethod
    async def _record_usage(
        resolved: Any,
        model: str,
        *,
        ttft_ms: int | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        duration_ms: int | None = None,
        upstream_status_code: int | None = None,
        call_source: str = CallSource.MEMORY_DISTILL.value,
    ) -> None:
        try:
            await arecord_llm_usage(
                call_source=call_source,
                provider=str(getattr(resolved, "provider_type", "")),
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                ttft_ms=ttft_ms,
                duration_ms=duration_ms,
                upstream_status_code=upstream_status_code,
                failure_type=str(upstream_status_code)
                if upstream_status_code is not None
                else "",
                source="initiatives",
            )
        except Exception:  # noqa: BLE001 — 观测绝不反噬主流程
            pass
