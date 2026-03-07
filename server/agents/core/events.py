"""AgentLoop 运行时事件定义。
AgentEvent 是 AgentLoop 在执行过程中发射的结构化事件，
用于 SSE 流式输出和实时监控。事件通过 on_event 回调传递。
"""
from dataclasses import dataclass, field
from typing import Any
# 事件类型常量
TEXT_DELTA = "text_delta"
TOOL_USE_START = "tool_use_start"
TOOL_USE_RESULT = "tool_use_result"
MESSAGE_COMPLETE = "message_complete"
THINKING = "thinking"
ERROR = "error"
TITLE_GENERATED = "title_generated"
@dataclass
class AgentEvent:
 """AgentLoop 运行时事件。
 Attributes:
 type: 事件类型（使用上方常量）
 data: 事件附加数据
 """
 type: str
 data: dict[str, Any] = field(default_factory=dict)
