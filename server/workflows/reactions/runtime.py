"""Reaction 运行时（Chassis v2 · P0）。

消费投影后的 ``Signal``，匹配 ``WorkflowReaction`` 配置，**幂等地**执行横切
副作用并留痕到 ``ReactionExecution``。核心保证：

- 幂等：同一 ``(execution, host_node, signal, reaction)`` 只执行一次；信号重放
  命中已有 ``ReactionExecution`` 即短路（修复现状 notify/doc 每跑必副作用）。
- 永不反噬主流程：执行体 best-effort，失败记 ``ReactionExecution.failed`` 可查，
  但不抛回主交付链路（non_blocking 语义）。
- 可扩展：target 执行器走注册表，P4 接入 UI 配置后无需改 runtime 核心。

观测：结构化 started/completed/failed + duration_ms，category=caller，
component=reaction_runtime；绑定触发用户由调用方上下文承载（best-effort）。
"""

import time
from typing import Any, Awaitable, Callable

import structlog
from asgiref.sync import sync_to_async
from django.db import IntegrityError

from workflows.models.reaction import (
    ReactionBlockingMode,
    ReactionExecution,
    ReactionExecutionStatus,
    WorkflowReaction,
)
from workflows.reactions.signal import Signal

logger = structlog.get_logger(__name__)

# target_type -> async executor(reaction, execution, signal) -> dict(response)
ReactionExecutor = Callable[[WorkflowReaction, Any, Signal], Awaitable[dict]]
_EXECUTORS: dict[str, ReactionExecutor] = {}


def register_executor(target_type: str) -> Callable[[ReactionExecutor], ReactionExecutor]:
    """注册一个 target 执行器。"""

    def _wrap(fn: ReactionExecutor) -> ReactionExecutor:
        _EXECUTORS[target_type] = fn
        return fn

    return _wrap


def build_idempotency_key(
    *, execution_id: str, host_node_id: str | None, signal_name: str, reaction_id: str
) -> str:
    """幂等键：execution + host_node + signal + reaction。"""
    return f"{execution_id}:{host_node_id or '*'}:{signal_name}:{reaction_id}"


@sync_to_async
def _match_reactions(workflow_id: Any, signal: Signal) -> list[WorkflowReaction]:
    """匹配该信号的启用反应：宿主节点匹配 或 工作流级（host_node 为空）。"""
    from django.db import models as dj_models

    qs = WorkflowReaction.objects.filter(
        workflow_id=workflow_id,
        signal_name=signal.name,
        enabled=True,
    )
    # node-scope 信号：仅匹配 host_node == subject 或工作流级反应。
    if signal.scope == "node_execution" and signal.subject_id:
        qs = qs.filter(
            dj_models.Q(host_node_id=signal.subject_id)
            | dj_models.Q(host_node__isnull=True)
        )
    return list(qs)


async def dispatch(signal: Signal, execution: Any) -> list[ReactionExecution]:
    """对一个信号分发所有匹配反应（幂等、fail-soft）。

    Returns:
        本次实际执行（或短路）的 ReactionExecution 列表。
    """
    workflow_id = getattr(execution, "workflow_id", None)
    if workflow_id is None:
        return []

    reactions = await _match_reactions(workflow_id, signal)
    results: list[ReactionExecution] = []
    for reaction in reactions:
        # gate 不走订阅式反应（由 DAG 节点承载），这里跳过。
        if reaction.blocking_mode == ReactionBlockingMode.GATE:
            continue
        result = await _dispatch_one(reaction, execution, signal)
        if result is not None:
            results.append(result)
    return results


async def _dispatch_one(
    reaction: WorkflowReaction, execution: Any, signal: Signal
) -> ReactionExecution | None:
    execution_id = str(getattr(execution, "id", ""))
    # 幂等键用「触发信号的发出主体」(signal.subject_id)，而非 reaction.host_node：
    # 工作流级反应（host_node 为空）会被多个不同节点触发，各自应独立去重；
    # 对绑定 host_node 的反应，subject 恒等于 host_node，语义一致。
    host_node_id = getattr(reaction, "host_node_id", None)
    subject = signal.subject_id or (str(host_node_id) if host_node_id else None)
    idem = build_idempotency_key(
        execution_id=execution_id,
        host_node_id=subject,
        signal_name=signal.name,
        reaction_id=str(reaction.id),
    )

    log = logger.bind(
        component="reaction_runtime",
        category="caller",
        reaction_id=str(reaction.id),
        target_type=reaction.target_type,
        signal=signal.name,
        execution_id=execution_id,
        idempotency_key=idem,
    )

    # 幂等：唯一约束 + 先查后建，命中已有记录即短路（不重复副作用）。
    existing = await ReactionExecution.objects.filter(
        reaction=reaction,
        workflow_execution_id=execution_id,
        idempotency_key=idem,
    ).afirst()
    if existing is not None:
        log.info("reaction_skipped_idempotent", status=existing.status)
        return existing

    try:
        record = await ReactionExecution.objects.acreate(
            reaction=reaction,
            workflow_execution_id=execution_id,
            idempotency_key=idem,
            status=ReactionExecutionStatus.PENDING,
            triggered_signal=signal.name,
            attempts=0,
        )
    except IntegrityError:
        # 并发竞态：另一路已创建同键记录 → 短路。
        log.info("reaction_skipped_race")
        return await ReactionExecution.objects.filter(
            reaction=reaction,
            workflow_execution_id=execution_id,
            idempotency_key=idem,
        ).afirst()

    log.info("reaction_started")
    await _execute_with_retry(reaction, execution, signal, record, log)
    return record


async def _execute_with_retry(
    reaction: WorkflowReaction,
    execution: Any,
    signal: Signal,
    record: ReactionExecution,
    log: Any,
) -> None:
    import asyncio

    executor = _EXECUTORS.get(reaction.target_type)
    if executor is None:
        record.attempts = 1
        await record.amark_failed(f"未注册的 target_type: {reaction.target_type}")
        log.warning("reaction_executor_missing")
        return

    max_attempts = reaction.max_attempts
    backoff = reaction.backoff_seconds
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        started = time.monotonic()
        try:
            response = await executor(reaction, execution, signal)
            record.attempts = attempt
            await record.amark_delivered(response or {})
            log.info(
                "reaction_completed",
                attempt=attempt,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return
        except Exception as exc:  # noqa: BLE001 — best-effort，绝不反噬主流程
            last_error = str(exc)
            log.warning(
                "reaction_attempt_failed",
                attempt=attempt,
                error=last_error,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            if attempt < max_attempts and backoff > 0:
                await asyncio.sleep(backoff)

    record.attempts = max_attempts
    await record.amark_failed(last_error)
    log.error("reaction_failed", attempts=max_attempts, error=last_error)


# ---- 内置 target 执行器 ----------------------------------------------------
# P0 提供 webhook + 飞书 IM 通知两个真实执行器；P4 接入 UI 配置后扩充
# （feishu_doc_create / writeback 等）。


@register_executor("alert")
async def _exec_alert(reaction: WorkflowReaction, execution: Any, signal: Signal) -> dict:
    """告警占位执行器：仅记录（系统告警链路另有 SystemAlertRule）。"""
    logger.info(
        "reaction_alert_noop",
        component="reaction_runtime",
        category="caller",
        reaction_id=str(reaction.id),
        signal=signal.name,
    )
    return {"noop": True}


@register_executor("webhook")
async def _exec_webhook(reaction: WorkflowReaction, execution: Any, signal: Signal) -> dict:
    """POST 反应配置中的 webhook（含 SSRF 防护 + 协议白名单）。"""
    import ipaddress
    import json
    from urllib.parse import urlparse

    import httpx

    config = reaction.config or {}
    url = config.get("url")
    if not url:
        raise ValueError("webhook 反应缺少 url")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"不支持的协议: {parsed.scheme}")
    hostname = parsed.hostname or ""
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise ValueError("禁止访问内网地址")
    except ValueError as exc:
        if "禁止访问内网地址" in str(exc):
            raise
        if hostname in ("localhost",) or hostname.endswith(".local"):
            raise ValueError("禁止访问内网地址") from None

    body = {
        "signal": signal.name,
        "execution_id": str(getattr(execution, "id", "")),
        "payload": signal.payload,
    }
    headers = config.get("headers", {}) or {}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, headers=headers, content=json.dumps(body, ensure_ascii=False))
        if resp.status_code >= 400:
            raise RuntimeError(f"webhook 返回错误状态码: {resp.status_code}")
    return {"status_code": resp.status_code}


@register_executor("notify_feishu_im")
async def _exec_notify_feishu_im(
    reaction: WorkflowReaction, execution: Any, signal: Signal
) -> dict:
    """发送飞书 IM 卡片通知（复用 FeishuIMService）。"""
    from services.feishu_im import FeishuIMService

    config = reaction.config or {}
    chat_id = config.get("chat_id")
    if not chat_id:
        raise ValueError("飞书通知反应缺少 chat_id")

    space = await sync_to_async(lambda: getattr(execution, "space", None))()
    im_service = await FeishuIMService.create(space)
    content = config.get("content") or f"工作流信号：{signal.name}"
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "工作流反应通知"},
            "template": "red" if signal.name.endswith(".failed") else "blue",
        },
        "elements": [{"tag": "markdown", "content": str(content)[:2000]}],
    }
    message_id = await im_service.send_card(
        receive_id=chat_id, receive_id_type="chat_id", card=card
    )
    return {"message_id": message_id}
