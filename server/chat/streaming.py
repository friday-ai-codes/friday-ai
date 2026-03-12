"""SSE 流式输出工具模块。
提供 AgentEvent 到 SSE 格式的转换函数。
SSE 协议：每个事件以 "data: " 前缀 + JSON + 双换行结束。
"""
from __future__ import annotations
import json
from agents.core.events import AgentEvent
def format_sse(event: AgentEvent, message_id: str = "") -> str:
 """将 AgentEvent 格式化为 SSE data 行。
 Args:
 event: AgentEvent 事件
 message_id: 关联的消息 ID（前端用于断线恢复）
 Returns:
 SSE 格式字符串 "data: {...}\\n\\n"
 """
 payload: dict = {"type": event.type, **event.data}
 if message_id:
 payload["message_id"] = message_id
 return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
def format_keepalive -> str:
 """SSE keepalive 注释行（不被 EventSource 解析为事件）。"""
 return ": keepalive\n\n"
