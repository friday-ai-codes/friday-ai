"""AgentLoop 运行时事件定义。
AgentEvent 是 AgentLoop 在执行过程中发射的结构化事件，
用于 SSE 流式输出和实时监控。事件通过 on_event 回调传递。
"""
from dataclasses import dataclass, field
from typing import Any
# 事件类型常量 — SSE data 行中的事件类型
# 前端 SSEEvent.type 联合类型必须与此处保持一一对应
TEXT_DELTA = "text_delta"
TOOL_USE_START = "tool_use_start"
TOOL_USE_RESULT = "tool_use_result"
MESSAGE_COMPLETE = "message_complete"
THINKING = "thinking"
ERROR = "error"
TITLE_GENERATED = "title_generated"
BUDGET_WARNING = "budget_warning"
DEEP_ANALYSIS_PROGRESS = "deep_analysis_progress"
PHASE_TRANSITION = "phase_transition"
TASK_PROGRESS = "task_progress"
# 所有 SSE data 事件类型集合（用于契约测试验证前后端一致性）
ALL_EVENT_TYPES: frozenset[str] = frozenset({
 TEXT_DELTA,
 TOOL_USE_START,
 TOOL_USE_RESULT,
 MESSAGE_COMPLETE,
 THINKING,
 ERROR,
 TITLE_GENERATED,
 BUDGET_WARNING,
 DEEP_ANALYSIS_PROGRESS,
 PHASE_TRANSITION,
 TASK_PROGRESS,
})
# 连接级事件类型 — 不走 SSE data 行，通过 SSE 注释行发送
KEEPALIVE = "keepalive"
@dataclass
class AgentEvent:
 """AgentLoop 运行时事件。
 Attributes:
 type: 事件类型（使用上方常量）
 data: 事件附加数据
 """
 type: str
 data: dict[str, Any] = field(default_factory=dict)
