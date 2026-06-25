"""孤儿编排运行（zombie run）恢复 — 从 LangGraph checkpoint 兜底落库。

背景
----
``conversation_service.send_message_stream`` 把 graph 跑在独立 ``asyncio.Task``
里，graph 完成后才在 ``await graph_task`` 之后做最后两件事：把
``OrchestrationRun`` 置 COMPLETED/ERROR + 调 ``finalize_conversation`` 把
assistant 消息落库。

问题：这「收尾」既可能跟在在线 SSE 消费循环后，也可能（用户切走页面、SSE 断开）
跑在一个游离的 ``asyncio.create_task(_background_finalize())`` 里。两者都依赖
**当前进程 / 当前请求存活**。开发态 ``uvicorn --reload`` 热重载、或进程退出，
会在「graph 已写完终态 checkpoint」与「Django 落库」之间把 task 杀掉：

- LangGraph checkpoint 是逐节点增量落盘的 → 终态（``final_answer`` / ``parts`` /
  ``tool_calls`` / ``phase=completed``）已经安全持久化在 ``orchestration_checkpoints.db``。
- 但 Django 这边的 assistant 消息从未创建，``OrchestrationRun`` 卡在
  ``finalizing/running``，``Conversation`` 卡在 ``running``。

结果：前端 runtime 轮询永远看到 ``running`` + ``finalizing`` → 一直显示
「正在整理回答…」+ 空气泡，而真正的答案被孤立在 checkpoint 里。

本模块提供 ``recover_orphaned_run``：检测「graph 已到终态但 DB 未收尾」的孤儿
run，从 checkpoint 重建终态并复用 ``finalize_conversation`` 落库。幂等、可被
runtime 查询路径与管理命令复用。
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import structlog
from django.utils import timezone

from orchestration.models import OrchestrationRun

logger = structlog.get_logger(__name__)

# graph 已 END 且 phase 落到这些值 → 说明 graph 完整跑完，只差 DB 收尾。
_TERMINAL_PHASES = {
    OrchestrationRun.Phase.COMPLETED,
    OrchestrationRun.Phase.ERROR,
    OrchestrationRun.Phase.FINALIZING,
}

# 默认最小年龄：刚创建的 run 可能正被在线收尾路径处理，留一个窗口避免与之竞争
# （正常路径从 graph END 到落库是亚秒级；这里给足冗余）。
_DEFAULT_MIN_AGE_SECONDS = 15


async def recover_orphaned_run(
    orch_run: OrchestrationRun,
    *,
    min_age_seconds: int = _DEFAULT_MIN_AGE_SECONDS,
) -> bool:
    """检测并恢复孤儿 run。

    判定「孤儿」的充要条件（全部满足）：
    1. ``OrchestrationRun.status`` 仍是 RUNNING / WAITING（未收尾）。
    2. checkpoint 里 graph 已 **END**（``snapshot.next`` 为空）且 ``phase`` 为终态
       —— 区分「真正还在跑 / 合法 interrupt 等待」与「跑完但没落库」。
    3. run 已超过 ``min_age_seconds`` —— 避让在线收尾路径，防竞态双写。

    满足后：claim run（原子置终态，rowcount 充当互斥锁，避免并发轮询重复落库）→
    从 checkpoint state 重建 ``final_answer`` / ``parts`` / ``tool_calls`` /
    ``thinking`` / ``result_metadata`` → 复用 ``finalize_conversation`` 落库。

    Returns:
        是否执行了恢复（True 表示本次把孤儿 run 收尾了）。
    """
    if orch_run.status not in {
        OrchestrationRun.Status.RUNNING,
        OrchestrationRun.Status.WAITING,
    }:
        return False

    # 年龄闸：太新的 run 让在线收尾路径先处理，避免竞态。
    if orch_run.created_at > timezone.now() - timedelta(seconds=min_age_seconds):
        return False

    # lazy import：避免与 conversation_service / graph 的循环依赖。
    from orchestration.graph import get_compiled_graph

    try:
        graph = await get_compiled_graph()
        snapshot = await graph.aget_state(
            {"configurable": {"thread_id": orch_run.thread_id}}
        )
    except Exception:
        logger.warning(
            "recover_orphaned_run_aget_state_failed",
            run_id=str(orch_run.run_id),
            thread_id=orch_run.thread_id,
            exc_info=True,
        )
        return False

    # snapshot.next 非空 → graph 仍有 pending 节点（执行中 / interrupt 等待） → 不是孤儿。
    if snapshot is None or snapshot.next:
        return False

    state: dict[str, Any] = dict(snapshot.values or {})
    phase = state.get("phase")
    if phase not in _TERMINAL_PHASES:
        return False

    is_error = phase == OrchestrationRun.Phase.ERROR
    terminal_status = (
        OrchestrationRun.Status.ERROR if is_error else OrchestrationRun.Status.COMPLETED
    )
    terminal_phase = (
        OrchestrationRun.Phase.ERROR if is_error else OrchestrationRun.Phase.COMPLETED
    )

    # Claim：原子地把 run 从 RUNNING/WAITING 翻到终态。rowcount==1 才算抢到所有权，
    # 防并发 runtime 轮询同时进入恢复造成重复落库。exclude(INTERRUPTED) 多保险一层。
    claimed = (
        await OrchestrationRun.objects.filter(
            id=orch_run.id,
            status__in=[OrchestrationRun.Status.RUNNING, OrchestrationRun.Status.WAITING],
        )
        .exclude(status=OrchestrationRun.Status.INTERRUPTED)
        .aupdate(status=terminal_status, phase=terminal_phase)
    )
    if not claimed:
        return False

    try:
        await _finalize_from_state(orch_run, state, is_error=is_error)
    except Exception:
        logger.exception(
            "recover_orphaned_run_finalize_failed",
            run_id=str(orch_run.run_id),
            conversation_id=str(orch_run.conversation_id),
        )
        # 落库失败：run 已置终态（不再 active），避免前端永久 stuck；
        # 但消息可能缺失，记日志供排查。不回滚 claim（回滚会再次 active 死循环）。
        return False

    logger.info(
        "recover_orphaned_run_recovered",
        run_id=str(orch_run.run_id),
        conversation_id=str(orch_run.conversation_id),
        phase=phase,
        final_answer_len=len(state.get("final_answer") or ""),
        tool_calls=len(state.get("tool_calls") or []),
        parts=len(state.get("parts") or []),
    )
    return True


async def _finalize_from_state(
    orch_run: OrchestrationRun,
    state: dict[str, Any],
    *,
    is_error: bool,
) -> None:
    """从 checkpoint state 重建并复用 ``finalize_conversation`` 落库。"""
    from chat.finalize import finalize_conversation
    from chat.models import Conversation, Message

    conversation = await Conversation.objects.select_related("space").aget(
        id=orch_run.conversation_id,
    )
    conv_id_str = str(conversation.id)

    # 幂等：已有该 run 之后的 assistant 消息 → 在线路径其实落库成功只是没改 run 状态，
    # 不重复创建（claim 已把 run 修成终态即可）。
    already_persisted = await Message.objects.filter(
        conversation_id=conversation.id,
        role=Message.Role.ASSISTANT,
        created_at__gte=orch_run.created_at,
    ).aexists()
    if already_persisted:
        await Conversation.objects.filter(
            id=conversation.id,
        ).exclude(status=Conversation.Status.INTERRUPTED).aupdate(
            status=Conversation.Status.ERROR
            if is_error
            else Conversation.Status.COMPLETED,
            updated_at=timezone.now(),
        )
        return

    # AgentSession：优先用 state 里的 id，回退到本对话最近一条；finalize 内部对
    # AgentSession 更新已 try/except，缺失不致命，但签名要求传对象。
    agent_session = await _resolve_agent_session(state, conv_id_str)
    if agent_session is None:
        raise RuntimeError(f"no AgentSession resolvable for conversation {conv_id_str}")

    # 最近一条 user 消息 —— 供标题生成。
    last_user = (
        await Message.objects.filter(
            conversation_id=conversation.id,
            role=Message.Role.USER,
        )
        .order_by("-created_at")
        .afirst()
    )
    user_message = last_user.content if last_user else ""

    result_metadata = dict(state.get("result_metadata") or {})
    if is_error:
        result_metadata.setdefault("status", "error")
    else:
        result_metadata.setdefault("status", "completed")

    await finalize_conversation(
        conversation=conversation,
        assistant_msg_id=uuid.uuid4(),
        final_content=state.get("final_answer", "") or "",
        accumulated_thinking=list(state.get("accumulated_thinking") or []),
        tool_calls=list(state.get("tool_calls") or []),
        result_metadata=result_metadata,
        agent_session=agent_session,
        session_id=agent_session.session_id,
        model=conversation.model,
        user_message=user_message,
        # 后台恢复无 SSE 通道，也不再补发 push（用户此前已看过流式过程）。
        notification_user_id=None,
        publish_title_event=False,
        parts=[p for p in (state.get("parts") or []) if isinstance(p, dict)],
    )

    # 收尾后清掉 streaming_snapshot，避免 runtime 轮询又拉到陈旧快照。
    from orchestration.graph import _clear_streaming_snapshot

    await _clear_streaming_snapshot(str(orch_run.run_id))


async def _resolve_agent_session(state: dict[str, Any], conv_id_str: str) -> Any:
    """解析 AgentSession：state.agent_session_id 优先，回退到本对话最近一条。"""
    from agents.models import AgentSession

    raw_id = state.get("agent_session_id")
    if raw_id not in (None, ""):
        try:
            return await AgentSession.objects.aget(id=int(raw_id))
        except (AgentSession.DoesNotExist, ValueError, TypeError):
            pass

    return (
        await AgentSession.objects.filter(
            metadata__conversation_id=conv_id_str,
        )
        .order_by("-id")
        .afirst()
    )
