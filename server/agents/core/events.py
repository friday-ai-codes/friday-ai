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
DOC_SUMMARY = "doc_summary"
DOC_ERROR = "doc_error"
# parts contract：Anthropic content blocks 风格的 parts 事件
# （双轨期与旧 text_delta / thinking / tool_use_* 共存，不替代）。
# payload schema 见 streaming parts contract 表格，前端按 useChatPartsProtocol flag 二选一消费。
PART_STARTED = "part_started"
PART_DELTA = "part_delta"
PART_COMPLETED = "part_completed"
# ─── implementation 决策注 (v18.1-work item G3 gap closure) ───
# 以下三个常量 (CODING_PROGRESS / AWAITING_PR_REVIEW / CONFLICT_CHECK) 在 v18.1
# 生产代码中均无 AgentEvent(type=...) 发射点 —— 全代码 grep 零命中。
#
# work item 最终采用 ConversationRuntime 快照轮询路径投递编码中间产出
# (详见 project docs),
# 前端默认每 2 秒轮询 GET /api/chat/conversations/{id}/runtime/,
# 错误退避 4 秒,感知延迟 ≤ 2s 正常 / ≤ 4s 错误。
# 编码执行在 Runner 容器,回调时 SSE 流已关闭 —— SSE push 与 Runner
# 容器生命周期根本不兼容 (论证见 server/chat/coding_events.py 顶部 docstring)。
#
# 保留这些常量的原因:
#   1) test_sse_event_contract.py 以 ALL_EVENT_TYPES 作为前后端 SSEEvent
#      类型联合的权威源,删除会破坏契约并造成前端类型回归
#   2) 若未来重新评估升级到真正的 SSE push,无需额外 schema 迁移
#
# 注意: events.py 中不存在 AWAITING_COMMIT_CONFIRM 常量 —— ROADMAP 旧版本
# 与 v18.1-work item.md 对该常量名的引用为笔误,implementation 不新增。
CODING_PROGRESS = "coding_progress"
CODING_COMPLETE = "coding_complete"
CODING_FAILED = "coding_failed"
AWAITING_PR_REVIEW = "awaiting_pr_review"
CONFLICT_CHECK = "conflict_check"

# 编排过程事件（Phase 110-01，OBS-01）：承载 ConvergenceSessionEvent 的统一信封
# {event, session_id, work_item_id?, ts, payload}，由 ConvergenceSessionService._emit_event
# 在持久化之后 best-effort fan-out 到当前 chat graph 的 custom 流。
# 与 PHASE_TRANSITION 是两套概念：后者是 LangGraph 的 chat 级阶段
# （executing / waiting / finalizing），前者是编排的 stage key。裁决 D-2 明确不复用——
# 挤进 phase_transition 会制造「同一通道两种语义」的新债。
PROCESS_EVENT = "process_event"

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
    DOC_SUMMARY,
    DOC_ERROR,
    CODING_PROGRESS,
    CODING_COMPLETE,
    CODING_FAILED,
    AWAITING_PR_REVIEW,
    CONFLICT_CHECK,
    # parts contract：parts 双轨期新事件
    PART_STARTED,
    PART_DELTA,
    PART_COMPLETED,
    # Phase 110-01：编排过程事件
    PROCESS_EVENT,
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
