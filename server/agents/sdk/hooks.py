"""SDK Hook 持久化模块：PostToolUse 和 Stop 回调。

通过 SDK 原生 hooks 机制驱动 ToolCallLog 写入和 AgentSession 状态更新。
Hook 回调中 DB 写入失败仅记录日志，不影响 SDK 主流程。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Union

import structlog
from claude_agent_sdk.types import (
    AsyncHookJSONOutput,
    HookContext,
    PostToolUseFailureHookInput,
    PostToolUseHookInput,
    PreCompactHookInput,
    PreToolUseHookInput,
    StopHookInput,
    SubagentStopHookInput,
    SyncHookJSONOutput,
    UserPromptSubmitHookInput,
)
from django.utils import timezone

from agents.core.events import TOOL_USE_RESULT, AgentEvent
from agents.models import AgentSession, ToolCallLog

logger = structlog.get_logger(__name__)

# SDK hook 输入类型联合
HookInput = Union[
    PreToolUseHookInput,
    PostToolUseHookInput,
    PostToolUseFailureHookInput,
    UserPromptSubmitHookInput,
    StopHookInput,
    SubagentStopHookInput,
    PreCompactHookInput,
]

# SDK hook 输出类型
HookOutput = AsyncHookJSONOutput | SyncHookJSONOutput

# SDK hook 回调类型
HookCallback = Callable[
    [HookInput, str | None, HookContext],
    Awaitable[HookOutput],
]


def create_post_tool_use_hook(
    session: AgentSession,
    event_callback: Callable[[AgentEvent], Awaitable[None]] | None = None,
) -> HookCallback:
    """创建 PostToolUse hook 回调。

    每次工具调用完成后：
    1. 写入 ToolCallLog 记录
    2. 通过 event_callback 发送 TOOL_USE_RESULT 事件到队列

    Args:
        session: AgentSession 实例，用于关联 ToolCallLog
        event_callback: 可选的事件回调，用于发送 TOOL_USE_RESULT 到 SSE 队列

    Returns:
        符合 SDK hook 签名的 async 回调函数
    """

    async def hook(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> HookOutput:
        # 从 input_data 提取字段（PostToolUseHookInput 是 TypedDict）
        data: dict[str, Any] = dict(input_data)
        tool_name: str = data.get("tool_name", "")
        tool_input: dict[str, Any] = data.get("tool_input", {})
        tool_response: Any = data.get("tool_response")
        tool_id: str = data.get("tool_use_id", tool_use_id or "")

        now = timezone.now()

        # 判断工具执行是否成功
        is_error = False
        if isinstance(tool_response, dict):
            is_error = bool(tool_response.get("is_error", False))

        # 1. 写入 ToolCallLog
        try:
            iteration = session.increment_tool_calls()
            await ToolCallLog.objects.acreate(
                session=session,
                tool_name=tool_name,
                tool_call_id=tool_id,
                arguments=tool_input,
                result_success=not is_error,
                result_output=tool_response,
                result_error="" if not is_error else str(tool_response),
                started_at=now,
                completed_at=now,
                duration_ms=0,  # SDK 未提供精确计时
                iteration=iteration,
            )
            logger.debug(
                "tool_call_logged",
                tool_name=tool_name,
                tool_use_id=tool_id,
                session_id=session.session_id,
                iteration=iteration,
            )
        except Exception:
            logger.exception(
                "tool_call_log_write_failed",
                tool_name=tool_name,
                tool_use_id=tool_id,
                session_id=session.session_id,
            )

        # 2. 发送 TOOL_USE_RESULT 事件（保留结构化结果，供 graph 识别 blocking marker）
        if event_callback is not None:
            try:
                event = AgentEvent(
                    type=TOOL_USE_RESULT,
                    data={
                        "tool_name": tool_name,
                        "tool_call_id": tool_id,
                        "success": not is_error,
                        "input": tool_input,
                        "result": tool_response,
                    },
                )
                await event_callback(event)
            except Exception:
                logger.exception(
                    "tool_use_result_event_failed",
                    tool_name=tool_name,
                )

        return {}

    return hook


def create_stop_hook(
    session: AgentSession,
) -> HookCallback:
    """创建 Stop hook 回调。

    SDK 运行结束时更新 AgentSession 为 completed 状态。

    Args:
        session: AgentSession 实例

    Returns:
        符合 SDK hook 签名的 async 回调函数
    """

    async def hook(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> HookOutput:
        try:
            session.status = AgentSession.Status.COMPLETED
            await session.asave(update_fields=["status", "updated_at"])
            logger.info(
                "session_completed_via_stop_hook",
                session_id=session.session_id,
            )
        except Exception:
            logger.exception(
                "session_update_failed",
                session_id=session.session_id,
            )

        return {}

    return hook
