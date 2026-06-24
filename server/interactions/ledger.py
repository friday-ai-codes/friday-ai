"""Interaction Ledger 写入 helper —— work-item 全部工具调用复用的唯一写入入口。

写入契约（contract..05 / contract）：

- **顶层 run 同步必成功**：``create_interaction_run`` 不包 try/except，写库失败直接抛出，
  保证每次外部调用都可追踪（contract）。
- **子事件 best-effort**：``record_event`` / ``record_tool_call`` / ``record_model_usage``
  写库失败被捕获、降级为 structlog warning、返回 ``None``，绝不阻塞外部主请求
  （威胁 security mitigation-04）。
- **脱敏永在写库前**：所有 payload / raw_request / tool input·output 在 ``create`` 之前
  必经 ``redact_for_ledger``（contract / contract）。``token_fingerprint`` 必须是
  ``hash_token`` 的结果，调用方绝不传明文。
- **同步/异步双入口**（Pitfall 2）：同步认证类直接调同步实现；adrf 异步视图调用
  ``acreate_*`` / ``arecord_*`` 包装（内部 ``sync_to_async``，沿用 runners/views.py 范式）。
  禁止在同步函数里写 ``acreate``，也禁止在 async 视图直接调同步 ORM。
- **seq 应用层分配**：``record_event`` 用 ``run.events.count()`` 作为 seq（首版串行假设，
  RESEARCH Open Question 2；并发场景后续加 unique_together(run, seq)）。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from .models import (
    InteractionEvent,
    InteractionRun,
    ModelUsageRecord,
    RetrievalTrace,
    ToolCallRecord,
)
from .redaction import redact_for_ledger

logger = structlog.get_logger(__name__)

# 上游 provider 错误码：429/529 单列（与 common.request_metrics 口径一致）。
_UPSTREAM_SINGLE_CODES = frozenset({429, 529})


def parse_upstream_status(exc: BaseException) -> int | None:
    """从 provider 异常提取数值 HTTP 状态码（T-72-02-01 缓解）。

    **只取数值码**：anthropic/openai/httpx 异常常把 status 放在
    ``status_code`` / ``http_status`` / ``code`` 属性或 ``.response.status_code``。
    绝不把异常 message / 响应体落库（若需记文本另经 ``redact_secrets_in_text``）。
    取不到返回 ``None``。best-effort：任何异常都回退 None，绝不反噬主流程。
    """
    try:
        for attr in ("status_code", "http_status", "code"):
            val = getattr(exc, attr, None)
            try:
                if val is not None:
                    ival = int(val)
                    if 100 <= ival <= 599:
                        return ival
            except (TypeError, ValueError):
                continue
        resp = getattr(exc, "response", None)
        if resp is not None:
            code = getattr(resp, "status_code", None)
            try:
                if code is not None:
                    ival = int(code)
                    if 100 <= ival <= 599:
                        return ival
            except (TypeError, ValueError):
                pass
    except Exception:  # noqa: BLE001 — 解析绝不反噬主流程
        return None
    return None


# === 同步核心实现 ===


def create_interaction_run(
    *,
    token_fingerprint: str,
    source: str,
    request_id: str = "",
    raw_request: dict[str, Any] | None = None,
    status: str = InteractionRun.Status.RUNNING,
    agent_session: Any = None,
    orchestration_run: Any = None,
) -> InteractionRun:
    """同步创建顶层 InteractionRun（contract，必成功，不吞异常）。

    ``token_fingerprint`` 必须是 ``hash_token`` 结果（sha256 hex），绝不传明文
    （contract）。``raw_request`` 写库前必经 ``redact_for_ledger``。
    """
    return InteractionRun.objects.create(
        token_fingerprint=token_fingerprint,
        source=source,
        request_id=request_id,
        status=status,
        raw_request=redact_for_ledger(raw_request or {}),
        agent_session=agent_session,
        orchestration_run=orchestration_run,
    )


def record_event(
    run: InteractionRun,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    parent_event: InteractionEvent | None = None,
) -> InteractionEvent | None:
    """记录一条交互事件（contract，best-effort）。

    payload 写库前必经 ``redact_for_ledger``；seq 由应用层用 ``run.events.count()``
    分配。写库失败降级 warning、返回 None，不阻塞主请求。
    """
    try:
        seq = run.events.count()
        return InteractionEvent.objects.create(
            run=run,
            event_type=event_type,
            payload=redact_for_ledger(payload or {}),
            parent_event=parent_event,
            seq=seq,
        )
    except Exception as exc:  # noqa: BLE001 —— best-effort，吞掉一切写库异常
        logger.warning(
            "ledger_event_write_failed",
            event_type=event_type,
            error=str(exc),
        )
        return None


def record_tool_call(
    run: InteractionRun,
    *,
    tool_name: str,
    input: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    status: str = "",
    duration_ms: int | None = None,
    error: str = "",
    retry_index: int = 0,
    parent_event: InteractionEvent | None = None,
) -> ToolCallRecord | None:
    """记录一次工具调用明细（contract，best-effort）。

    ``input`` / ``output`` 写库前必经 ``redact_for_ledger``。写库失败降级返回 None。
    """
    try:
        return ToolCallRecord.objects.create(
            run=run,
            tool_name=tool_name,
            input=redact_for_ledger(input or {}),
            output=redact_for_ledger(output or {}),
            status=status,
            duration_ms=duration_ms,
            error=error,
            retry_index=retry_index,
            parent_event=parent_event,
        )
    except Exception as exc:  # noqa: BLE001 —— best-effort
        logger.warning(
            "ledger_tool_call_write_failed",
            tool_name=tool_name,
            error=str(exc),
        )
        return None


def record_retrieval_trace(
    run: InteractionRun,
    *,
    kind: str,
    payload: dict[str, Any] | None = None,
    tool_call: ToolCallRecord | None = None,
) -> RetrievalTrace | None:
    """记录一条检索证据（work item，best-effort）。"""
    try:
        seq = run.retrieval_traces.count()
        return RetrievalTrace.objects.create(
            run=run,
            tool_call=tool_call,
            kind=kind,
            payload=redact_for_ledger(payload or {}),
            seq=seq,
        )
    except Exception as exc:  # noqa: BLE001 —— best-effort
        logger.warning(
            "ledger_retrieval_trace_write_failed",
            kind=kind,
            error=str(exc),
        )
        return None


def record_model_usage(
    run: InteractionRun,
    *,
    provider: str,
    model: str,
    prompt_version: str = "",
    system_prompt_version: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    cost_estimate: Decimal | None = None,
    duration_ms: int | None = None,
    failure_type: str = "",
    parent_event: InteractionEvent | None = None,
) -> ModelUsageRecord | None:
    """记录一次模型用量明细（contract，best-effort）。

    成功或失败（``failure_type``）都留痕，不覆盖。写库失败降级返回 None。
    """
    try:
        return ModelUsageRecord.objects.create(
            run=run,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            system_prompt_version=system_prompt_version,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_estimate=cost_estimate,
            duration_ms=duration_ms,
            failure_type=failure_type,
            parent_event=parent_event,
        )
    except Exception as exc:  # noqa: BLE001 —— best-effort
        logger.warning(
            "ledger_model_usage_write_failed",
            provider=provider,
            model=model,
            error=str(exc),
        )
        return None


def _record_llm_usage(
    *,
    run: InteractionRun | None = None,
    call_source: str = "",
    provider: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cost_estimate: Decimal | None = None,
    duration_ms: int | None = None,
    ttft_ms: int | None = None,
    upstream_status_code: int | None = None,
    failure_type: str = "",
    user_id: str | None = None,
    source: str = "",
) -> ModelUsageRecord | None:
    """run 可选的单一 LLM 用量同步写入实现（per RATE-02 / SLA-03 / SLA-04，best-effort）。

    - ``run`` 为 ``None`` 时独立成行（非 MCP 的 chat/workflow/容器 LLM 调用）；传
      ``InteractionRun`` 实例则与 MCP 路径同源关联，向后兼容。
    - ``user_id`` 缺省从 Phase 71 ``structlog.contextvars`` 取（无则 ``system``），
      绝不取客户端输入（T-72-02-04）。
    - ``call_source`` 经 ``CallSource.normalize`` 受控（非法值回退安全默认）。
    - **脱敏契约**：只记 token 计数 + 数值上游码 + 受控标签，**绝不**落 prompt/
      completion 明文或上游响应体（T-72-02-01/02）。
    - ``total_tokens`` 缺省时按 input+output 兜底；``cache_*`` 暂并入 total（
      ModelUsageRecord 无独立 cache 列，留待 Phase 73）。
    - 写库异常 → warning + return None，绝不反噬 LLM 主流程（T-72-02-05）。
    """
    try:
        if user_id is None:
            ctx = structlog.contextvars.get_contextvars()
            user_id = str(ctx.get("user_id", "system") or "system")
        # CallSource 在此 lazy import，避免 interactions ↔ agents 顶层耦合。
        from agents.call_source import CallSource

        effective_total = total_tokens or (
            prompt_tokens + completion_tokens + cache_read_tokens + cache_write_tokens
        )
        return ModelUsageRecord.objects.create(
            run=run,
            call_source=CallSource.normalize(call_source),
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=effective_total,
            cost_estimate=cost_estimate,
            duration_ms=duration_ms,
            ttft_ms=ttft_ms,
            upstream_status_code=upstream_status_code,
            failure_type=failure_type,
            user_id=user_id,
            source=source,
        )
    except Exception as exc:  # noqa: BLE001 —— best-effort，观测绝不反噬 LLM
        logger.warning(
            "ledger_llm_usage_write_failed",
            call_source=call_source,
            provider=provider,
            model=model,
            error=str(exc),
        )
        return None


# === 异步入口（adrf 视图复用；内部 sync_to_async 包装同步实现，Pitfall 2）===


async def acreate_interaction_run(
    *,
    token_fingerprint: str,
    source: str,
    request_id: str = "",
    raw_request: dict[str, Any] | None = None,
    status: str = InteractionRun.Status.RUNNING,
    agent_session: Any = None,
    orchestration_run: Any = None,
) -> InteractionRun:
    """``create_interaction_run`` 的异步包装（异步视图调用）。"""
    return await sync_to_async(create_interaction_run)(
        token_fingerprint=token_fingerprint,
        source=source,
        request_id=request_id,
        raw_request=raw_request,
        status=status,
        agent_session=agent_session,
        orchestration_run=orchestration_run,
    )


async def arecord_event(
    run: InteractionRun,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    parent_event: InteractionEvent | None = None,
) -> InteractionEvent | None:
    """``record_event`` 的异步包装。"""
    return await sync_to_async(record_event)(
        run, event_type, payload, parent_event=parent_event
    )


async def arecord_tool_call(
    run: InteractionRun,
    *,
    tool_name: str,
    input: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    status: str = "",
    duration_ms: int | None = None,
    error: str = "",
    retry_index: int = 0,
    parent_event: InteractionEvent | None = None,
) -> ToolCallRecord | None:
    """``record_tool_call`` 的异步包装。"""
    return await sync_to_async(record_tool_call)(
        run,
        tool_name=tool_name,
        input=input,
        output=output,
        status=status,
        duration_ms=duration_ms,
        error=error,
        retry_index=retry_index,
        parent_event=parent_event,
    )


async def arecord_retrieval_trace(
    run: InteractionRun,
    *,
    kind: str,
    payload: dict[str, Any] | None = None,
    tool_call: ToolCallRecord | None = None,
) -> RetrievalTrace | None:
    """``record_retrieval_trace`` 的异步包装。"""
    return await sync_to_async(record_retrieval_trace)(
        run,
        kind=kind,
        payload=payload,
        tool_call=tool_call,
    )


async def arecord_model_usage(
    run: InteractionRun,
    *,
    provider: str,
    model: str,
    prompt_version: str = "",
    system_prompt_version: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    cost_estimate: Decimal | None = None,
    duration_ms: int | None = None,
    failure_type: str = "",
    parent_event: InteractionEvent | None = None,
) -> ModelUsageRecord | None:
    """``record_model_usage`` 的异步包装。"""
    return await sync_to_async(record_model_usage)(
        run,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        system_prompt_version=system_prompt_version,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cost_estimate=cost_estimate,
        duration_ms=duration_ms,
        failure_type=failure_type,
        parent_event=parent_event,
    )


async def arecord_llm_usage(
    *,
    run: InteractionRun | None = None,
    call_source: str = "",
    provider: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cost_estimate: Decimal | None = None,
    duration_ms: int | None = None,
    ttft_ms: int | None = None,
    upstream_status_code: int | None = None,
    failure_type: str = "",
    user_id: str | None = None,
    source: str = "",
) -> ModelUsageRecord | None:
    """``_record_llm_usage`` 的异步包装（run 可选的单一 LLM 写入入口，best-effort）。

    供 chat_runner / langchain_runner / 容器回调（72-03）复用：每次 LLM 调用收尾
    （或异常解析上游码）调一次，落一行可聚合 ``ModelUsageRecord``。内部 sync_to_async
    不阻塞事件循环（T-72-02-05），写库失败返回 None 绝不反噬主流程。
    """
    return await sync_to_async(_record_llm_usage)(
        run=run,
        call_source=call_source,
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        cost_estimate=cost_estimate,
        duration_ms=duration_ms,
        ttft_ms=ttft_ms,
        upstream_status_code=upstream_status_code,
        failure_type=failure_type,
        user_id=user_id,
        source=source,
    )
