from __future__ import annotations
from typing import Any
import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamWriter, interrupt
from agents.core.events import THINKING, TOOL_USE_RESULT, TOOL_USE_START
from agents.sdk.runner import SDKAgentRunner, SdkRunnerConfig
from orchestration.checkpointer import get_checkpointer
from orchestration.state import RunPhase, WorkflowState
logger = structlog.get_logger(__name__)
async def planning_node(state: WorkflowState) -> dict[str, Any]:
 """接收用户消息，决定执行策略。Phase 仅推进 phase。"""
 return {"phase": RunPhase.EXECUTING.value}
async def executing_node(
 state: WorkflowState,
 config: RunnableConfig,
 writer: StreamWriter,
) -> dict[str, Any]:
 """驱动 SDKAgentRunner 并通过 StreamWriter 桥接流式事件。
 从 config["configurable"] 获取运行时参数，在节点内部构建
 SdkRunnerConfig + SDKAgentRunner，运行 stream 并将每个
 AgentEvent 推送给外层 astream(stream_mode="custom") 消费者。
 """
 if state.get("blocking_tasks"):
 return {"phase": RunPhase.WAITING.value}
 cfg = config.get("configurable", {})
 api_key = cfg.get("api_key", "")
 if not api_key:
 return {
 "phase": RunPhase.ERROR.value,
 "result_metadata": {"error": "api_key 未配置"},
 }
 agent_session = None
 agent_session_id = cfg.get("agent_session_id", "")
 if agent_session_id:
 from agents.models import AgentSession
 try:
 agent_session = await AgentSession.objects.aget(id=agent_session_id)
 except AgentSession.DoesNotExist:
 pass
 sdk_config = SdkRunnerConfig(
 system_prompt=cfg.get("system_prompt", ""),
 model=cfg.get("model", ""),
 project_id=cfg.get("project_id", ""),
 session_id=cfg.get("session_id", ""),
 conversation_id=cfg.get("conversation_id", ""),
 api_key=api_key,
 api_base_url=cfg.get("api_base_url", ""),
 max_turns=30,
 timeout_seconds=0,
 agent_session=agent_session,
 max_budget_usd=cfg.get("max_budget_usd"),
 )
 runner = SDKAgentRunner(sdk_config)
 accumulated_thinking: list[str] =
 tool_calls_by_id: dict[str, dict[str, Any]] = {}
 try:
 async for event in runner.stream(state.get("user_message", "")):
 writer({"type": event.type, "data": event.data})
 if event.type == THINKING:
 thinking_text = event.data.get("thinking", "")
 if thinking_text:
 accumulated_thinking.append(thinking_text)
 elif event.type == TOOL_USE_START:
 tool_id = str(event.data.get("tool_call_id", ""))
 if tool_id and tool_id not in tool_calls_by_id:
 tool_calls_by_id[tool_id] = {
 "id": tool_id,
 "name": event.data.get("tool_name", ""),
 "input": event.data.get("input", {}),
 "result": None,
 "status": "done",
 }
 elif event.type == TOOL_USE_RESULT:
 tool_id = str(event.data.get("tool_call_id", ""))
 if tool_id:
 entry = tool_calls_by_id.setdefault(
 tool_id,
 {
 "id": tool_id,
 "name": event.data.get("tool_name", ""),
 "input": {},
 "result": None,
 "status": "done",
 },
 )
 if event.data.get("tool_name"):
 entry["name"] = event.data["tool_name"]
 if "result" in event.data:
 entry["result"] = event.data["result"]
 except Exception:
 logger.exception(
 "executing_node_sdk_error",
 session_id=cfg.get("session_id", ""),
 )
 result = runner.result
 return {
 "phase": RunPhase.ERROR.value,
 "final_answer": (result.final_answer if result else None) or "",
 "accumulated_thinking": accumulated_thinking,
 "tool_calls": list(tool_calls_by_id.values),
 "result_metadata": {"error": "SDK 运行异常"},
 "agent_session_id": agent_session_id,
 }
 result = runner.result
 final_answer = (result.final_answer if result else None) or ""
 result_metadata: dict[str, Any] = {
 "status": result.status if result else "unknown",
 }
 if result and result.metadata:
 result_metadata["cost_usd"] = result.metadata.get("cost_usd", 0)
 if result and result.usage:
 result_metadata["input_tokens"] = result.usage.get("input_tokens", 0)
 result_metadata["output_tokens"] = result.usage.get("output_tokens", 0)
 return {
 "phase": RunPhase.FINALIZING.value,
 "final_answer": final_answer,
 "accumulated_thinking": accumulated_thinking,
 "tool_calls": list(tool_calls_by_id.values),
 "result_metadata": result_metadata,
 "agent_session_id": agent_session_id,
 }
async def waiting_node(state: WorkflowState) -> dict[str, Any]:
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
async def finalizing_node(state: WorkflowState) -> dict[str, Any]:
 """收尾节点，标记 workflow 完成。"""
 return {"phase": RunPhase.COMPLETED.value}
def route_after_executing(state: WorkflowState) -> str:
 """条件路由：error 直接结束，有 blocking_tasks 走 waiting，否则走 finalizing。"""
 if state.get("phase") == RunPhase.ERROR.value:
 return END
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
