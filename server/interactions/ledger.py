"""Interaction Ledger 写入 helper —— work-item 全部工具调用复用的唯一写入入口。
写入契约（..05 / ）：
- **顶层 run 同步必成功**：``create_interaction_run`` 不包 try/except，写库失败直接抛出，
 保证每次外部调用都可追踪。
- **子事件 best-effort**：``record_event`` / ``record_tool_call`` / ``record_model_usage``
 写库失败被捕获、降级为 structlog warning、返回 ``None``，绝不阻塞外部主请求
 （威胁 T-）。
- **脱敏永在写库前**：所有 payload / raw_request / tool input·output 在 ``create`` 之前
 必经 ``redact_for_ledger``。``token_fingerprint`` 必须是
 ``hash_token`` 的结果，调用方绝不传明文。
- **同步/异步双入口**（Pitfall 2）：同步认证类直接调同步实现；adrf 异步视图调用
 ``acreate_*`` / ``arecord_*`` 包装（内部 ``sync_to_async``，沿用 runners/views.py 范式）。
 禁止在同步函数里写 ``acreate``，也禁止在 async 视图直接调同步 ORM。
- **seq 应用层分配**：``record_event`` 用 ``run.events.count`` 作为 seq（首版串行假设，
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
 ToolCallRecord,
)
from .redaction import redact_for_ledger
logger = structlog.get_logger(__name__)
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
 """同步创建顶层 InteractionRun（，必成功，不吞异常）。
 ``token_fingerprint`` 必须是 ``hash_token`` 结果（sha256 hex），绝不传明文
 。``raw_request`` 写库前必经 ``redact_for_ledger``。
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
 """记录一条交互事件（，best-effort）。
 payload 写库前必经 ``redact_for_ledger``；seq 由应用层用 ``run.events.count``
 分配。写库失败降级 warning、返回 None，不阻塞主请求。
 """
 try:
 seq = run.events.count
 return InteractionEvent.objects.create(
 run=run,
 event_type=event_type,
 payload=redact_for_ledger(payload or {}),
 parent_event=parent_event,
 seq=seq,
 )
 except Exception as exc: # noqa: BLE001 —— best-effort，吞掉一切写库异常
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
 """记录一次工具调用明细（，best-effort）。
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
 except Exception as exc: # noqa: BLE001 —— best-effort
 logger.warning(
 "ledger_tool_call_write_failed",
 tool_name=tool_name,
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
 """记录一次模型用量明细（，best-effort）。
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
 except Exception as exc: # noqa: BLE001 —— best-effort
 logger.warning(
 "ledger_model_usage_write_failed",
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
