"""编码完成自动提炼 learning case（v0.17.0 Phase 101 / LOOP-03）。

三链路（workflow / Chat / MCP）编码成功完成后 best-effort 提炼一条可复用的
``McpLearningCase`` 并走 Phase 100 统一入图通路。**锚点接线在 101-03，本模块只提供
公共入口** ``aextract_learning_case``。

管线顺序（每步不过即返回 ``None``，全程 fail-soft 绝不上抛）：

1. kill switch：``SettingKeys.LEARNING_CASE_AUTO_EXTRACT``（默认开，可秒关止血）；
2. 状态门：仅成功完成（``completed``）的任务提炼，失败/取消不产正向 case；
3. 幂等：``source_session_id``（= ``SubAgentSession.session_id`` + 可选后缀）unique 查重，
   回调重入 / 并发只产一条（并发窗口由 ``IntegrityError`` 兜底）；
4. LLM 提炼：完整镜像 ``initiatives/services/memory_distill.py`` 范式——
   ``use_call_source("learning_case_extraction")`` + ``build_chat_model``（streaming=False）
   + ``arecord_llm_usage``（成功/异常两路都记，best-effort）+ 缺凭证/异常返回 None；
5. 质量门（P2 mem0 97.8% 垃圾率前车之鉴，与功能同 plan 落地）：最小信息量 + 去模板断言，
   不过门走显式 REJECT 路径记 ``learning_case_rejected`` 事件且不入库；
6. 脱敏：四字段全过 ``redact_secrets_in_text``（Security Mistakes——提炼产物入库前必过）;
7. 入库 ``McpLearningCase.acreate``（run=None）→ 8. ``aschedule_ingestion`` 入图（INV-6）。

测试 mock 点：patch ``mcp_tools.learning_case_extraction._acall_llm``。
"""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any

import structlog
from django.db import IntegrityError
from langchain_core.messages import HumanMessage

from agents.call_source import CallSource, use_call_source
from common.logging import redact_secrets_in_text
from interactions.ledger import arecord_llm_usage, parse_upstream_status
from mcp_tools.models import McpLearningCase
from services.provider_config import (
    ProviderConfigService,
    ProviderMissingError,
    aget_legacy_anthropic_config,
)
from system.models import SettingKeys
from system.settings_service import aget_bool_setting

logger = structlog.get_logger(__name__)

__all__ = ["aextract_for_session", "aextract_learning_case", "apersist_extracted_case"]

_COMPONENT = "mcp_tools"
_EXTRACT_MODEL_FALLBACK = "claude-sonnet-4-20250514"
# 状态门成功集合：与 SubAgentSession.Status.COMPLETED 对齐（失败/取消不产正向 case）。
_SUCCESS_STATUSES = {"completed"}
# 质量门：problem/solution 最小信息量（去空白后字符数）。
_MIN_FIELD_LEN = 30
# 去模板断言：solution 以占位废话开头视为模板产物。单字 "无"/"略" 不进 startswith
# 判定——会误杀 "无需改动…"/"无论走哪条链路…" 等完全正常的 solution 开头（101 IN-01）；
# 纯 "无"/"略" 之类超短模板产物已被 _MIN_FIELD_LEN 长度门先行拦截，无漏网。
_TEMPLATE_PREFIXES = ("暂无", "N-A", "N/A", "TODO", "待补充")

_EXTRACT_PROMPT = (
    "你是工程经验提炼助手。请阅读以下一次编码任务的需求与执行产出，提炼**一条可复用的"
    "工程经验**，输出**一段 JSON**（不要输出任何其他文字），包含五个键，值均为中文：\n"
    '{{"title": "...", "problem": "...", "root_cause": "...", "solution": "...", '
    '"outcome": "..."}}\n\n'
    "要求：\n"
    "- 提炼可复用的工程经验而非复述任务日志或 diff；\n"
    "- problem 描述**一类问题**（何种场景下会遇到什么），而非本次任务的标题；\n"
    "- solution 写**做法与原因**（怎么做、为什么这样做），供未来相似任务参考；\n"
    "- root_cause 写问题的技术根因；outcome 用一个短词概括结果（如 success）。\n\n"
    "任务材料：\n{task_material}"
)


async def aextract_learning_case(
    *,
    session_id: str,
    task_status: str,
    requirement_text: str = "",
    text_output: str = "",
    branch_name: str = "",
    pr_url: str = "",
    modified_files: list[str] | None = None,
    repositories: list[str] | None = None,
    work_item_type: str = "",
    work_item_id: int | None = None,
    plan_summary: str = "",
    initiated_by_user_id: str | None = None,
    source: str = "auto_extract",
    idempotency_suffix: str = "",
) -> McpLearningCase | None:
    """编码完成自动提炼公共入口（LOOP-03，best-effort，绝不上抛）。

    - ``session_id``：幂等键 = ``SubAgentSession.session_id``；
    - ``task_status``：上游任务终态，仅 ``completed`` 进提炼；
    - ``idempotency_suffix``：LOOP-05 PR review 沉淀复用时传 ``":pr_review"``；
    - 返回落库的 ``McpLearningCase``，任何一步不过 / 异常返回 ``None``。
    """
    try:
        return await _aextract(
            session_id=session_id,
            task_status=task_status,
            requirement_text=requirement_text,
            text_output=text_output,
            branch_name=branch_name,
            pr_url=pr_url,
            modified_files=modified_files or [],
            repositories=repositories or [],
            work_item_type=work_item_type,
            work_item_id=work_item_id,
            plan_summary=plan_summary,
            initiated_by_user_id=initiated_by_user_id,
            source=source,
            idempotency_suffix=idempotency_suffix,
        )
    except Exception as exc:  # noqa: BLE001 — 兜底 fail-soft：沉淀绝不反噬主流程
        logger.warning(
            "learning_case_extraction_failed",
            session_id=f"{session_id}{idempotency_suffix}",
            error=redact_secrets_in_text(str(exc)),
            error_type=type(exc).__name__,
            category="caller",
            component=_COMPONENT,
            initiated_by_user_id=initiated_by_user_id or "system",
        )
        return None


async def aextract_for_session(
    session_id: str,
    *,
    requirement_text: str = "",
    work_item_type: str = "",
    work_item_id: int | None = None,
    pr_url: str = "",
    initiated_by_user_id: str | None = None,
) -> None:
    """三链路共用的提炼便捷入口（101-03 锚点侧样板收敛）。

    经 ``session_id`` 反查 ``SubAgentSession``（status 做状态门入参）+ 关联
    ``TaskResult``（text_output/branch/pr_url/modified_files 标量取，无则各字段空），
    组装后转调 :func:`aextract_learning_case`。设计为在 ``run_in_background``
    后台任务里跑：全程兜底 try/except，任何异常只记日志、绝不上抛。
    """
    try:
        from subagent.models import SubAgentSession, TaskResult  # lazy import 防循环

        session = (
            await SubAgentSession.objects.filter(session_id=session_id)
            .values("id", "status")
            .afirst()
        )
        if session is None:
            _log_skipped(session_id, "session_not_found")
            return
        task_result = (
            await TaskResult.objects.filter(session_id=session["id"])
            .values("text_output", "branch_name", "pr_url", "modified_files")
            .afirst()
        ) or {}
        await aextract_learning_case(
            session_id=session_id,
            task_status=str(session["status"]),
            requirement_text=requirement_text,
            text_output=str(task_result.get("text_output") or ""),
            branch_name=str(task_result.get("branch_name") or ""),
            pr_url=pr_url or str(task_result.get("pr_url") or ""),
            modified_files=list(task_result.get("modified_files") or []),
            work_item_type=work_item_type,
            work_item_id=work_item_id,
            initiated_by_user_id=initiated_by_user_id,
        )
    except Exception as exc:  # noqa: BLE001 — 后台任务兜底：提炼绝不反噬主流程
        logger.warning(
            "learning_case_extraction_failed",
            session_id=session_id,
            error=redact_secrets_in_text(str(exc)),
            error_type=type(exc).__name__,
            category="caller",
            component=_COMPONENT,
            initiated_by_user_id=initiated_by_user_id or "system",
        )


async def _aextract(
    *,
    session_id: str,
    task_status: str,
    requirement_text: str,
    text_output: str,
    branch_name: str,
    pr_url: str,
    modified_files: list[str],
    repositories: list[str],
    work_item_type: str,
    work_item_id: int | None,
    plan_summary: str,
    initiated_by_user_id: str | None,
    source: str,
    idempotency_suffix: str,
) -> McpLearningCase | None:
    started = perf_counter()
    key = f"{session_id}{idempotency_suffix}"

    # 1. kill switch（默认开，可秒关止血——P2 止血阀）。
    enabled = await aget_bool_setting(SettingKeys.LEARNING_CASE_AUTO_EXTRACT, default=True)
    if not enabled:
        _log_skipped(key, "disabled")
        return None

    # 2. 状态门：失败/取消任务不提炼（不产正向 case）。
    if task_status not in _SUCCESS_STATUSES:
        _log_skipped(key, "status_gate", task_status=task_status)
        return None

    # 3. 幂等：同一 session 重入只产一条（回调重入自驱前科，T-101-02-02）。
    if await McpLearningCase.objects.filter(source_session_id=key).aexists():
        _log_skipped(key, "duplicate")
        return None

    # 4. LLM 提炼（幂等检查之后才烧 token）。
    material = _build_material(
        requirement_text=requirement_text,
        plan_summary=plan_summary,
        text_output=text_output,
        branch_name=branch_name,
        pr_url=pr_url,
        modified_files=modified_files,
    )
    raw = await _acall_llm(material)
    if not raw:
        _log_skipped(key, "llm_unavailable")
        return None
    parsed = _parse_json(raw)
    if parsed is None:
        _log_rejected(key, "json_parse_failed", initiated_by_user_id)
        return None

    # 5-9. 质量门→脱敏→入库→入图→收尾事件（可复用序列，LOOP-05 review 沉淀同路径）。
    return await apersist_extracted_case(
        parsed,
        session_key=key,
        session_id=session_id,
        source=source,
        pr_url=pr_url,
        branch_name=branch_name,
        modified_files=modified_files,
        repositories=repositories,
        work_item_type=work_item_type,
        work_item_id=work_item_id,
        initiated_by_user_id=initiated_by_user_id,
        started=started,
    )


async def apersist_extracted_case(
    parsed: dict[str, Any],
    *,
    session_key: str,
    session_id: str,
    source: str,
    pr_url: str = "",
    branch_name: str = "",
    modified_files: list[str] | None = None,
    repositories: list[str] | None = None,
    work_item_type: str = "",
    work_item_id: int | None = None,
    initiated_by_user_id: str | None = None,
    started: float | None = None,
) -> McpLearningCase | None:
    """质量门→脱敏→入库→入图 可复用低层入口（101-04 拆分决策）。

    拆分理由（LOOP-05）：``pr_review_capture`` 自带 review LLM 调用，若复用
    :func:`aextract_learning_case` 会二次烧 token（其 LLM 提炼步不可绕过）；
    故把 LLM 之后的"质量门→脱敏→入库→入图→收尾事件"拆为本函数，review 模块
    LLM 后直接调它——幂等/质量门/脱敏/入库/入图全部复用、不重复 LLM 调用。

    - ``session_key``：完整幂等键（含后缀，如 ``{sid}:pr_review``），入库前
      先查重（幂等检查在 persist 前做）；
    - ``parsed``：LLM 产物 dict（title/problem/root_cause/solution/outcome）。
    """
    started = perf_counter() if started is None else started
    key = session_key
    modified_files = modified_files or []
    repositories = repositories or []

    # 幂等：persist 前查重（供直调路径；aextract 主链在 LLM 前已查过一次，双查无害）。
    if await McpLearningCase.objects.filter(source_session_id=key).aexists():
        _log_skipped(key, "duplicate")
        return None

    # 5. 质量门（与提炼功能同 plan，绝不"先跑通后补"）。
    reject_reason = _admission_gate(parsed)
    if reject_reason is not None:
        _log_rejected(key, reject_reason, initiated_by_user_id)
        return None

    # 6. 脱敏：提炼产物入库前四字段必过（T-101-02-01）。
    title = redact_secrets_in_text(str(parsed.get("title") or "").strip())
    problem = redact_secrets_in_text(str(parsed.get("problem") or "").strip())
    root_cause = redact_secrets_in_text(str(parsed.get("root_cause") or "").strip())
    solution = redact_secrets_in_text(str(parsed.get("solution") or "").strip())
    outcome = str(parsed.get("outcome") or "").strip() or "success"

    # 7. 入库（run=None：自动提炼无 InteractionRun）。IntegrityError = 并发重入兜底。
    try:
        case = await McpLearningCase.objects.acreate(
            run=None,
            source_session_id=key,
            title=title[:240] or "LearningCase",
            problem=problem,
            root_cause=root_cause,
            solution=solution,
            outcome=outcome[:80],
            work_item_type=work_item_type,
            work_item_id=work_item_id,
            repositories=repositories,
            files=modified_files,
            branches=[branch_name] if branch_name else [],
            mr_urls=[pr_url] if pr_url else [],
            source_links={"session_id": session_id, "pr_url": pr_url, "source": source},
            embedding_text="\n".join([title, problem, solution]),
        )
    except IntegrityError:
        _log_skipped(key, "duplicate")
        return None

    # 8. 入图：Phase 100 统一摄取通路（INV-6；内建 on_commit + 异常全吞）。
    from knowledge import ingestion  # lazy import 防循环（learning_case_service.py 同款）

    await ingestion.aschedule_ingestion(
        ingestion.IngestionRequest("learning_case", str(case.id), "learning_case_auto_extracted"),
        initiated_by_user_id=initiated_by_user_id or "system",
    )

    # 9. 收尾事件（caller：一次可归因的自动沉淀）。
    logger.info(
        "learning_case_extraction_completed",
        session_id=key,
        case_id=str(case.id),
        duration_ms=int((perf_counter() - started) * 1000),
        category="caller",
        component=_COMPONENT,
        initiated_by_user_id=initiated_by_user_id or "system",
    )
    return case


def _log_skipped(key: str, reason: str, **extra: Any) -> None:
    """跳过事件（sampling：高频跳过不刷 caller）。"""
    logger.info(
        "learning_case_extraction_skipped",
        session_id=key,
        reason=reason,
        category="sampling",
        component=_COMPONENT,
        **extra,
    )


def _log_rejected(key: str, reason: str, initiated_by_user_id: str | None) -> None:
    """显式 REJECT 路径：质量门不过记事件计数，不入库（ROADMAP 成功标准 3）。"""
    logger.warning(
        "learning_case_rejected",
        session_id=key,
        reason=reason,
        category="caller",
        component=_COMPONENT,
        initiated_by_user_id=initiated_by_user_id or "system",
    )


def _build_material(
    *,
    requirement_text: str,
    plan_summary: str,
    text_output: str,
    branch_name: str,
    pr_url: str,
    modified_files: list[str],
) -> str:
    """拼装提炼输入料（text_output 截断 ~6000 字符，与 memory_distill 限额一致）。"""
    sections: list[str] = []
    if requirement_text.strip():
        sections.append(f"【任务需求】\n{requirement_text.strip()}")
    if plan_summary.strip():
        sections.append(f"【方案摘要】\n{plan_summary.strip()}")
    if text_output.strip():
        sections.append(f"【执行产出】\n{text_output.strip()[:6000]}")
    meta: list[str] = []
    if branch_name:
        meta.append(f"分支：{branch_name}")
    if pr_url:
        meta.append(f"PR：{pr_url}")
    if modified_files:
        meta.append("改动文件：" + ", ".join(modified_files[:50]))
    if meta:
        sections.append("【元信息】\n" + "\n".join(meta))
    return "\n\n".join(sections)


def _parse_json(raw: str) -> dict[str, Any] | None:
    """解析 LLM 输出的 JSON（剥 ```json 围栏）；解析失败返回 None（进 REJECT）。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[: -len("```")]
    text = text.strip()
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _admission_gate(parsed: dict[str, Any]) -> str | None:
    """最小信息量 + 去模板质量门（P2）。返回 reject reason 或 None（通过）。"""
    problem = str(parsed.get("problem") or "").strip()
    solution = str(parsed.get("solution") or "").strip()
    if len(problem) < _MIN_FIELD_LEN:
        return "problem_too_short"
    if len(solution) < _MIN_FIELD_LEN:
        return "solution_too_short"
    if problem == solution:
        return "problem_equals_solution"
    if solution.startswith(_TEMPLATE_PREFIXES):
        return "solution_template"
    return None


async def _acall_llm(task_material: str) -> str | None:
    """单轮 LLM 提炼（call_source=learning_case_extraction，LOGGING-SPEC §4.1）。

    完整镜像 ``memory_distill._acall_llm``：缺凭证/异常 fail-soft 返回 None；
    成功/异常两路都经 ``arecord_llm_usage`` 上报（best-effort）。
    测试 mock 点：patch 本函数即可绕过真实 provider。
    """
    call_source = CallSource.LEARNING_CASE_EXTRACTION.value
    try:
        resolved = await ProviderConfigService.aresolve_or_error()
    except Exception:  # noqa: BLE001 — 解析异常 fail-soft
        return None
    if isinstance(resolved, ProviderMissingError):
        logger.warning(
            "learning_case_extraction_llm_skipped",
            reason="no_credential",
            call_source=call_source,
            component=_COMPONENT,
            category="sampling",
        )
        return None

    from agents.llm_factory import build_chat_model

    legacy = await aget_legacy_anthropic_config()
    model = legacy.get("default_model") or _EXTRACT_MODEL_FALLBACK
    prompt = _EXTRACT_PROMPT.format(task_material=task_material)

    _start = perf_counter()
    ttft_ms: int | None = None
    try:
        with use_call_source(call_source):
            chat_model = build_chat_model(resolved, model, max_output_tokens=1024, streaming=False)
            ai_msg = await chat_model.ainvoke([HumanMessage(content=prompt)])
        ttft_ms = int((perf_counter() - _start) * 1000)
    except Exception as exc:  # noqa: BLE001 — LLM 失败 fail-soft + 上游错误码留痕
        await _record_usage(
            resolved,
            model,
            ttft_ms=None,
            upstream_status_code=parse_upstream_status(exc),
        )
        logger.warning(
            "learning_case_extraction_llm_failed",
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
            call_source=CallSource.LEARNING_CASE_EXTRACTION.value,
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
