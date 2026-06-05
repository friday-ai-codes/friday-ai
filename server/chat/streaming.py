"""SSE 流式输出工具模块。

提供 AgentEvent 到 SSE 格式的转换函数。
SSE 协议：每个事件以 "data: " 前缀 + JSON + 双换行结束。
"""

from __future__ import annotations

import json

from agents.core.events import AgentEvent


def format_sse(event: AgentEvent, message_id: str = "", run_id: str = "") -> str:
    """将 AgentEvent 格式化为 SSE data 行。

    Args:
        event: AgentEvent 事件
        message_id: 关联的消息 ID（前端用于断线恢复）
        run_id: OrchestrationRun.run_id（work item: 事件稳定标识，便于排查和去重）

    Returns:
        SSE 格式字符串 "data: {...}\\n\\n"
    """
    payload: dict = {"type": event.type, **event.data}
    if message_id:
        payload["message_id"] = message_id
    if run_id:
        payload["run_id"] = run_id
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def format_keepalive() -> str:
    """SSE keepalive 注释行（不被 EventSource 解析为事件）。

    使用 SSE 协议的注释行格式 `": keepalive\\n\\n"`。
    浏览器 EventSource API 和手动 ReadableStream 解析均会跳过
    以冒号开头的注释行，因此不会被误解析为 data 事件。
    """
    return ": keepalive\n\n"
