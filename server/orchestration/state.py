from __future__ import annotations

import enum
from typing import Any, TypedDict


class RunPhase(str, enum.Enum):
    """编排运行阶段枚举。"""

    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING = "waiting"
    # initial implementation：等待用户对 ask_clarification 的回答。
    WAITING_CLARIFICATION = "waiting_clarification"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    ERROR = "error"


class WorkflowState(TypedDict, total=False):
    """LangGraph 编排 graph state — authoritative source。

    编排语义字段（initial implementation）：run_id / phase / blocking_tasks / user_message / final_answer
    SDK 运行结果字段（initial implementation）：accumulated_thinking / tool_calls / result_metadata / agent_session_id
    协商字段（initial implementation）：pending_clarification

    所有字段为 JSON 可序列化类型，支持 checkpoint 持久化。
    DB 模型（Message, AgentSession, OrchestrationRun）是此 state 的投影。
    """

    # 编排语义（initial implementation）
    run_id: str
    phase: str  # RunPhase.value — 用 str 保持 JSON 序列化兼容
    blocking_tasks: list[dict[str, Any]]
    user_message: str
    user_parts: list[dict[str, Any]]
    final_answer: str

    # Blocking task 循环（initial implementation）
    blocking_results: list[dict[str, Any]]
    wait_execute_loops: int

    # SDK 运行结果（initial implementation）
    accumulated_thinking: list[str]
    tool_calls: list[dict[str, Any]]
    # parts contract：chat_runner PartsCollector 收集的有序 parts
    # 数组（Anthropic content blocks 风格），强同源派生 content / tool_calls；
    # 通过 conversation_service → finalize 落到 Message.parts JSONField。
    parts: list[dict[str, Any]]
    result_metadata: dict[str, Any]
    agent_session_id: str

    # initial implementation：协商暂停 payload
    # 形如 {"clarification_id": str, "question": str, "options": list,
    #        "allow_freeform": bool, "triggering_message_id": str}
    # interrupt() 时由 wait_clarification_node 透传给前端 / endpoint。
    pending_clarification: dict[str, Any]
