from __future__ import annotations
from typing import Any
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from orchestration.checkpointer import get_checkpointer
from orchestration.state import RunPhase, WorkflowState
def planning_node(state: WorkflowState) -> dict[str, Any]:
 """接收用户消息，决定执行策略。Phase 骨架仅推进 phase。"""
 return {"phase": RunPhase.EXECUTING.value}
def executing_node(state: WorkflowState) -> dict[str, Any]:
 """执行节点。Phase 骨架根据 blocking_tasks 决定阶段转换。
 Phase 将在此节点接入 Agent SDK 调用。
 """
 if state.get("blocking_tasks"):
 return {"phase": RunPhase.WAITING.value}
 return {
 "phase": RunPhase.FINALIZING.value,
 "final_answer": f"Processed: {state.get('user_message', '')}",
 }
def waiting_node(state: WorkflowState) -> dict[str, Any]:
 """等待阻塞任务完成。
 interrupt 暂停 graph 并将 blocking_tasks 作为 payload 保存。
 resume 值（BlockingTaskResult）作为 interrupt 的返回值传入。
 不在 interrupt 前放置副作用 — 避免 resume 时重放。
 """
 result = interrupt(state.get("blocking_tasks", ))
 output = ""
 if isinstance(result, dict):
 output = str(result.get("output", ""))
 return {
 "phase": RunPhase.FINALIZING.value,
 "final_answer": output,
 "blocking_tasks":,
 }
def finalizing_node(state: WorkflowState) -> dict[str, Any]:
 """收尾节点，标记 workflow 完成。"""
 return {"phase": RunPhase.COMPLETED.value}
def route_after_executing(state: WorkflowState) -> str:
 """条件路由：有 blocking_tasks 走 waiting，否则走 finalizing。"""
 if state.get("blocking_tasks"):
 return "waiting"
 return "finalizing"
def build_graph -> StateGraph:
 """构建编排 StateGraph builder。
 拓扑: START → planning → executing → (conditional) → finalizing → END
 ↘ waiting ↗
 """
 builder: StateGraph = StateGraph(WorkflowState)
 builder.add_node("planning", planning_node)
 builder.add_node("executing", executing_node)
 builder.add_node("waiting", waiting_node)
 builder.add_node("finalizing", finalizing_node)
 builder.add_edge(START, "planning")
 builder.add_edge("planning", "executing")
 builder.add_conditional_edges("executing", route_after_executing)
 builder.add_edge("waiting", "finalizing")
 builder.add_edge("finalizing", END)
 return builder
async def get_compiled_graph -> Any:
 """编译 graph 并绑定持久化 checkpointer（生产用 AsyncSqliteSaver）。"""
 checkpointer = await get_checkpointer
 return build_graph.compile(checkpointer=checkpointer)
