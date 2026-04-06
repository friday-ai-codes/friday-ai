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
 只存编排语义，不存消息历史或工具调用细节。
 DB 模型（Message, AgentSession, OrchestrationRun）是此 state 的投影。
 """
 run_id: str
 phase: str # RunPhase.value — 用 str 保持 JSON 序列化兼容
 blocking_tasks: list[dict[str, Any]]
 user_message: str
 final_answer: str
