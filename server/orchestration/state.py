from __future__ import annotations
import enum
from typing import Any, TypedDict
class RunPhase(str, enum.Enum):
 """编排运行阶段枚举。"""
 PLANNING = "planning"
 EXECUTING = "executing"
 WAITING = "waiting"
 FINALIZING = "finalizing"
 COMPLETED = "completed"
 ERROR = "error"
class WorkflowState(TypedDict, total=False):
 """LangGraph 编排 graph state — authoritative source。
 编排语义字段（Phase）：run_id / phase / blocking_tasks / user_message / final_answer
 SDK 运行结果字段（Phase）：accumulated_thinking / tool_calls / result_metadata / agent_session_id
 所有字段为 JSON 可序列化类型，支持 checkpoint 持久化。
 DB 模型（Message, AgentSession, OrchestrationRun）是此 state 的投影。
 """
 # 编排语义（Phase）
 run_id: str
 phase: str # RunPhase.value — 用 str 保持 JSON 序列化兼容
 blocking_tasks: list[dict[str, Any]]
 user_message: str
 final_answer: str
 # Blocking task 循环（Phase）
 blocking_results: list[dict[str, Any]]
 wait_execute_loops: int
 # SDK 运行结果（Phase）
 accumulated_thinking: list[str]
 tool_calls: list[dict[str, Any]]
 result_metadata: dict[str, Any]
 agent_session_id: str
