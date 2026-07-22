"""PR 创建成功后可选轻量 review 沉淀（v0.17.0 Phase 101 / LOOP-05）。

范围锁定"能跑通 + 沉淀"（CONTEXT Out of Scope 锁定）：**不做评审 UI、不做规则
引擎、不回写 review 意见到 PR**。锚点由 101-04 在 workflow（``coding.py``
完工闭环块）与 chat（``coding_graph.py`` PR 成功分支）各接一处调度。

管线（全程 fail-soft，外层兜底 try/except 记 ``pr_review_capture_failed``）：

1. 开关：``SettingKeys.PR_REVIEW_CAPTURE``（**默认关**）——关闭时零 LLM 调用；
2. 幂等：``{session_id}:pr_review`` 查重前置（重入不烧 token，复用 101-02 幂等键）；
3. diff 摘要：复用 ``merge_request_service.summarize_branch``（仓库缺失/异常 skip）；
4. LLM review：镜像 memory_distill 范式（``use_call_source(pr_review_capture)`` +
   ``build_chat_model(streaming=False)`` + ``arecord_llm_usage`` 成功/异常双路 +
   fail-soft None）；prompt 基底 = ``REVIEW_SYSTEM_PROMPT``（只 import 不修改——
   migration replay 依赖其字节级一致）+ 追加中文沉淀指令；
5. 沉淀：review 产物组装为 problem（需求/变更上下文）+ solution（review 结论与
   建议）+ outcome="review"，经 ``learning_case_extraction.apersist_extracted_case``
   入库——**复用幂等/质量门/脱敏/入库/入图、不重复 LLM 调用**（101-04 拆分决策，
   见该函数 docstring）。

测试 mock 点：patch ``mcp_tools.pr_review_capture._acall_llm`` /
``mcp_tools.pr_review_capture.summarize_branch`` /
``mcp_tools.pr_review_capture.apersist_extracted_case``。
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from agents.call_source import CallSource, use_call_source
from common.logging import redact_secrets_in_text
from interactions.ledger import arecord_llm_usage, parse_upstream_status
from mcp_tools.learning_case_extraction import apersist_extracted_case
from mcp_tools.merge_request_service import summarize_branch
from services.provider_config import (
    ProviderConfigService,
    ProviderMissingError,
    aget_legacy_anthropic_config,
)
from system.models import SettingKeys
from system.settings_service import aget_bool_setting

logger = structlog.get_logger(__name__)

__all__ = ["acapture_pr_review"]

_COMPONENT = "mcp_tools"
_REVIEW_MODEL_FALLBACK = "claude-sonnet-4-20250514"
_IDEMPOTENCY_SUFFIX = ":pr_review"
# 变更材料截断上限（与 memory_distill / learning_case_extraction 限额一致）。
_MATERIAL_LIMIT = 6000

# 追加在 REVIEW_SYSTEM_PROMPT 之后的沉淀指令（常量本体只 import 不修改）。
_CAPTURE_SUFFIX = (
    "\n\n补充要求：在上述 JSON 之后另起一行，用 200 字以内的中文总结"
    "「本次变更最值得沉淀的 1 条经验/风险」。"
)


async def acapture_pr_review(
    *,
    repository_id: str,
    source_branch: str,
    target_branch: str,
    pr_url: str,
    session_id: str,
    requirement_text: str = "",
    work_item_type: str = "",
    work_item_id: int | None = None,
    initiated_by_user_id: str | None = None,
) -> None:
    """PR 创建成功锚点的可选轻量 review 沉淀入口（best-effort，绝不上抛）。

    - ``session_id``：幂等键源（实际键 = ``{session_id}:pr_review``）；
    - 开关默认关：``learning_case.pr_review_enabled`` 未开启时零 LLM 调用。
    """
    started = perf_counter()
    key = f"{session_id}{_IDEMPOTENCY_SUFFIX}"
    try:
        # 1. 开关（默认关，零成本）。
        enabled = await aget_bool_setting(SettingKeys.PR_REVIEW_CAPTURE, default=False)
        if not enabled:
            _log_skipped(key, "disabled")
            return

        # 2. 幂等前置：重入不烧 token（persist 内还有一道兜底查重）。
        from mcp_tools.models import McpLearningCase  # lazy import 防循环

        if await McpLearningCase.objects.filter(source_session_id=key).aexists():
            _log_skipped(key, "duplicate")
            return

        # 3. diff 摘要（复用 summarize_branch；仓库缺失/平台异常 → skip）。
        from repositories.models import Repository  # lazy import 防循环

        repo = await Repository.objects.filter(id=repository_id).afirst()
        if repo is None:
            _log_skipped(key, "repository_missing", repository_id=str(repository_id))
            return
        try:
            summary = await summarize_branch(
                repository=repo,
                source_branch=source_branch,
                target_branch=target_branch or repo.default_branch,
                max_files=30,
                trace=None,
            )
        except Exception as exc:  # noqa: BLE001 — diff 摘要失败 skip（fail-soft）
            _log_skipped(key, "diff_summary_failed", error=redact_secrets_in_text(str(exc)))
            return

        # 4. LLM review（call_source=pr_review_capture，101-02 已登记）。
        material = _build_material(
            requirement_text=requirement_text,
            source_branch=source_branch,
            target_branch=target_branch or repo.default_branch,
            summary=summary,
        )
        raw = await _acall_llm(material)
        if not raw:
            _log_skipped(key, "llm_unavailable")
            return

        # 5. 沉淀：组装 problem/solution/outcome 走 LOOP-03 入库路径
        #    （质量门→脱敏→入库→入图全部复用，不重复 LLM 调用）。
        files = summary.get("files") or []
        file_names = ", ".join(str(f.get("path") or "") for f in files[:10])
        problem = (
            f"PR 变更 review：{requirement_text.strip() or '（无需求文本）'}；"
            f"分支 {source_branch} → {target_branch or repo.default_branch}"
            f"（仓库 {repo.name}），变更文件 {len(files)} 个"
            + (f"：{file_names}" if file_names else "")
        )
        parsed = {
            "title": f"PR Review: {repo.name} {source_branch}",
            "problem": problem,
            "root_cause": "",
            "solution": raw.strip(),
            "outcome": "review",
        }
        case = await apersist_extracted_case(
            parsed,
            session_key=key,
            session_id=session_id,
            source="pr_review",
            pr_url=pr_url,
            branch_name=source_branch,
            repositories=[repo.name],
            work_item_type=work_item_type,
            work_item_id=work_item_id,
            initiated_by_user_id=initiated_by_user_id,
            started=started,
        )
        if case is None:
            return

        logger.info(
            "pr_review_capture_completed",
            case_id=str(case.id),
            pr_url=pr_url,
            duration_ms=int((perf_counter() - started) * 1000),
            category="caller",
            component=_COMPONENT,
            initiated_by_user_id=initiated_by_user_id or "system",
        )
    except Exception as exc:  # noqa: BLE001 — 兜底 fail-soft：review 沉淀绝不反噬主流程
        logger.warning(
            "pr_review_capture_failed",
            session_id=key,
            pr_url=pr_url,
            error=redact_secrets_in_text(str(exc)),
            error_type=type(exc).__name__,
            category="caller",
            component=_COMPONENT,
            initiated_by_user_id=initiated_by_user_id or "system",
        )


def _log_skipped(key: str, reason: str, **extra: Any) -> None:
    """跳过事件（sampling：默认关/重入等高频跳过不刷 caller）。"""
    logger.info(
        "pr_review_capture_skipped",
        session_id=key,
        reason=reason,
        category="sampling",
        component=_COMPONENT,
        **extra,
    )


def _build_material(
    *,
    requirement_text: str,
    source_branch: str,
    target_branch: str,
    summary: dict[str, Any],
) -> str:
    """拼装 review 输入料（requirement + files/risks/test_suggestions，截断 ~6000 字符）。"""
    sections: list[str] = []
    if requirement_text.strip():
        sections.append(f"【任务需求】\n{requirement_text.strip()}")
    sections.append(f"【分支】\n{source_branch} → {target_branch}")
    files = summary.get("files") or []
    if files:
        file_lines = "\n".join(
            f"- {f.get('path')} ({f.get('change_type')}, "
            f"+{f.get('additions')}/-{f.get('deletions')})"
            for f in files[:30]
        )
        sections.append(f"【变更文件】\n{file_lines}")
    risks = summary.get("risks") or []
    if risks:
        sections.append("【风险】\n" + "\n".join(f"- {r}" for r in risks))
    tests = summary.get("test_suggestions") or []
    if tests:
        sections.append("【测试建议】\n" + "\n".join(f"- {t}" for t in tests))
    return "\n\n".join(sections)[:_MATERIAL_LIMIT]


async def _acall_llm(material: str) -> str | None:
    """单轮 LLM review（call_source=pr_review_capture，LOGGING-SPEC §4.1）。

    完整镜像 ``learning_case_extraction._acall_llm`` / ``memory_distill`` 范式：
    缺凭证/异常 fail-soft 返回 None；成功/异常两路都经 ``arecord_llm_usage`` 上报
    （best-effort）。system 基底 = ``REVIEW_SYSTEM_PROMPT``（只 import 不修改）。
    测试 mock 点：patch 本函数即可绕过真实 provider。
    """
    # 只 import 不修改：migration replay 依赖该常量字节级一致（code_review.py docstring）。
    from workflows.nodes.ai.code_review import REVIEW_SYSTEM_PROMPT

    call_source = CallSource.PR_REVIEW_CAPTURE.value
    try:
        resolved = await ProviderConfigService.aresolve_or_error()
    except Exception:  # noqa: BLE001 — 解析异常 fail-soft
        return None
    if isinstance(resolved, ProviderMissingError):
        logger.warning(
            "pr_review_capture_llm_skipped",
            reason="no_credential",
            call_source=call_source,
            component=_COMPONENT,
            category="sampling",
        )
        return None

    from agents.llm_factory import build_chat_model

    legacy = await aget_legacy_anthropic_config()
    model = legacy.get("default_model") or _REVIEW_MODEL_FALLBACK

    _start = perf_counter()
    ttft_ms: int | None = None
    try:
        with use_call_source(call_source):
            chat_model = build_chat_model(resolved, model, max_output_tokens=1024, streaming=False)
            ai_msg = await chat_model.ainvoke(
                [
                    SystemMessage(content=REVIEW_SYSTEM_PROMPT + _CAPTURE_SUFFIX),
                    HumanMessage(content=material),
                ]
            )
        ttft_ms = int((perf_counter() - _start) * 1000)
    except Exception as exc:  # noqa: BLE001 — LLM 失败 fail-soft + 上游错误码留痕
        await _record_usage(
            resolved,
            model,
            ttft_ms=None,
            upstream_status_code=parse_upstream_status(exc),
        )
        logger.warning(
            "pr_review_capture_llm_failed",
            error=redact_secrets_in_text(str(exc)),
            error_type=type(exc).__name__,
            call_source=call_source,
            component=_COMPONENT,
            category="sampling",
        )
        return None

    usage = _extract_usage(ai_msg)
    await _record_usage(
        resolved,
        model,
        ttft_ms=ttft_ms,
        prompt_tokens=usage.get("input_tokens", 0),
        completion_tokens=usage.get("output_tokens", 0),
        duration_ms=int((perf_counter() - _start) * 1000),
    )
    return _extract_text(ai_msg)


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


def _extract_usage(ai_msg: Any) -> dict[str, int]:
    usage = getattr(ai_msg, "usage_metadata", None)
    if not isinstance(usage, dict):
        return {}
    return {
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
    }


async def _record_usage(
    resolved: Any,
    model: str,
    *,
    ttft_ms: int | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    duration_ms: int | None = None,
    upstream_status_code: int | None = None,
) -> None:
    try:
        await arecord_llm_usage(
            call_source=CallSource.PR_REVIEW_CAPTURE.value,
            provider=str(getattr(resolved, "provider_type", "")),
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            ttft_ms=ttft_ms,
            duration_ms=duration_ms,
            upstream_status_code=upstream_status_code,
            failure_type=str(upstream_status_code) if upstream_status_code is not None else "",
            source="mcp_tools",
        )
    except Exception:  # noqa: BLE001 — 观测绝不反噬主流程
        pass
