from __future__ import annotations
import asyncio
from typing import Any
import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamWriter, interrupt
from agents.chat_runner import ChatAnthropicRunner, ChatRunnerConfig
from agents.core.events import (
 MESSAGE_COMPLETE,
 PHASE_TRANSITION,
 TASK_PROGRESS,
 TEXT_DELTA,
 THINKING,
 TOOL_USE_RESULT,
 TOOL_USE_START,
)
from orchestration.checkpointer import get_checkpointer
from orchestration.runner_registry import register_runner, unregister_runner
from orchestration.state import RunPhase, WorkflowState
logger = structlog.get_logger(__name__)
async def _persist_run_phase(run_id: str, phase: str) -> None:
 """将 phase 写入 OrchestrationRun — SSE 推流前调用，确保 DB >= SSE。"""
 try:
 from orchestration.models import OrchestrationRun
 await OrchestrationRun.objects.filter(run_id=run_id).aupdate(phase=phase)
 except Exception:
 logger.warning("persist_run_phase_failed", run_id=run_id, phase=phase, exc_info=True)
async def planning_node(state: WorkflowState, writer: StreamWriter) -> dict[str, Any]:
 """接收用户消息，决定执行策略。发射 PHASE_TRANSITION executing。"""
 await _persist_run_phase(state.get("run_id", ""), RunPhase.EXECUTING.value)
 writer({"type": PHASE_TRANSITION, "data": {"phase": "executing"}})
 return {"phase": RunPhase.EXECUTING.value}
async def executing_node(
 state: WorkflowState,
 config: RunnableConfig,
 writer: StreamWriter,
) -> dict[str, Any]:
 """驱动 ChatAnthropicRunner — 支持首次运行和 blocking_results 注入两种模式。
 模式 A（首次）：正常运行 SDK，提取 __blocking_task__ 标记。
 模式 B（二次）：注入 blocking_results 作为上下文再运行 SDK 生成最终回答。
 """
 blocking_results = state.get("blocking_results")
 if blocking_results:
 return await _execute_with_results(state, config, writer, blocking_results)
 return await _execute_first_run(state, config, writer)
async def _build_chat_runner(
 config: RunnableConfig,
) -> tuple[ChatAnthropicRunner, str] | dict[str, Any]:
 """从 config 构建 ChatAnthropicRunner，返回 (runner, agent_session_id) 或 error dict。"""
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
 dsb = cfg.get("default_search_branch")
 default_search_branch: str | None = None
 if isinstance(dsb, str):
 s = dsb.strip
 if s:
 default_search_branch = s
 runner_config = ChatRunnerConfig(
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
 default_search_branch=default_search_branch,
 )
 return ChatAnthropicRunner(runner_config), agent_session_id
async def _run_chat_stream(
 runner: ChatAnthropicRunner,
 prompt: str,
 writer: StreamWriter,
 run_id: str,
) -> tuple[list[str], dict[str, dict[str, Any]]]:
 """运行 Chat runner stream，返回 (accumulated_thinking, tool_calls_by_id)。
 中断时通过 writer 推送 phase_transition interrupted 确认事件后重新抛出。
 """
 accumulated_thinking: list[str] =
 tool_calls_by_id: dict[str, dict[str, Any]] = {}
 blocking_marker_seen = False
 try:
 async for event in runner.stream(prompt):
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
 if isinstance(event.data["result"], dict) and event.data["result"].get("__blocking_task__"):
 blocking_marker_seen = True
 should_forward = True
 if blocking_marker_seen and event.type in {THINKING, TEXT_DELTA, MESSAGE_COMPLETE}:
 should_forward = False
 if should_forward:
 writer({"type": event.type, "data": event.data})
 except asyncio.CancelledError:
 try:
 await _persist_run_phase(run_id, "interrupted")
 writer({"type": PHASE_TRANSITION, "data": {"phase": "interrupted"}})
 except Exception:
 pass
 raise
 return accumulated_thinking, tool_calls_by_id
async def _extract_blocking_tasks(
 tool_calls_by_id: dict[str, dict[str, Any]],
 conversation_id: str,
) -> list[dict[str, Any]]:
 """从 tool_calls 结果中提取 __blocking_task__ 标记，并 drain fallback registry。"""
 from agents.tools.blocking_task_registry import drain_blocking_tasks
 blocking_tasks: list[dict[str, Any]] =
 for tc in tool_calls_by_id.values:
 result = tc.get("result")
 if isinstance(result, dict) and result.get("__blocking_task__"):
 blocking_tasks.append({
 "task_type": result["task_type"],
 "task_id": result["task_id"],
 "params": result.get("params", {}),
 })
 fallback_tasks = await drain_blocking_tasks(conversation_id)
 seen_ids = {t["task_id"] for t in blocking_tasks}
 for ft in fallback_tasks:
 if ft["task_id"] not in seen_ids:
 blocking_tasks.append(ft)
 seen_ids.add(ft["task_id"])
 return blocking_tasks
def _build_result_metadata(runner: ChatAnthropicRunner) -> dict[str, Any]:
 """从 runner.result 构建 result_metadata。"""
 result = runner.result
 result_metadata: dict[str, Any] = {
 "status": result.status if result else "unknown",
 }
 if result and result.metadata:
 result_metadata["cost_usd"] = result.metadata.get("cost_usd", 0)
 if result and result.usage:
 result_metadata["input_tokens"] = result.usage.get("input_tokens", 0)
 result_metadata["output_tokens"] = result.usage.get("output_tokens", 0)
 return result_metadata
async def _execute_first_run(
 state: WorkflowState,
 config: RunnableConfig,
 writer: StreamWriter,
) -> dict[str, Any]:
 """首次运行 Chat runner：正常执行并提取 blocking task 标记。"""
 build_result = await _build_chat_runner(config)
 if isinstance(build_result, dict):
 return build_result
 runner, agent_session_id = build_result
 cfg = config.get("configurable", {})
 conv_id = cfg.get("conversation_id", "")
 run_id = state.get("run_id", "")
 await _persist_run_phase(run_id, RunPhase.EXECUTING.value)
 writer({"type": PHASE_TRANSITION, "data": {"phase": "executing"}})
 accumulated_thinking: list[str] =
 tool_calls_by_id: dict[str, dict[str, Any]] = {}
 if conv_id:
 register_runner(conv_id, runner)
 try:
 accumulated_thinking, tool_calls_by_id = await _run_chat_stream(
 runner, state.get("user_message", ""), writer, run_id,
 )
 except Exception:
 logger.exception(
 "executing_node_chat_runner_error",
 session_id=cfg.get("session_id", ""),
 )
 result = runner.result
 return {
 "phase": RunPhase.ERROR.value,
 "final_answer": (result.final_answer if result else None) or "",
 "accumulated_thinking": accumulated_thinking,
 "tool_calls": list(tool_calls_by_id.values),
 "result_metadata": {"error": "Chat runner 运行异常"},
 "agent_session_id": agent_session_id,
 }
 finally:
 if conv_id:
 unregister_runner(conv_id)
 blocking_tasks = await _extract_blocking_tasks(
 tool_calls_by_id, cfg.get("conversation_id", ""),
 )
 if blocking_tasks:
 logger.info(
 "executing_node_blocking_tasks_detected",
 count=len(blocking_tasks),
 task_ids=[t["task_id"] for t in blocking_tasks],
 )
 writer({"type": TASK_PROGRESS, "data": {"completed_count": 0, "total_count": len(blocking_tasks)}})
 await _persist_run_phase(run_id, RunPhase.WAITING.value)
 writer({"type": PHASE_TRANSITION, "data": {"phase": "waiting", "blocking_task_count": len(blocking_tasks)}})
 return {
 "phase": RunPhase.WAITING.value,
 "accumulated_thinking": accumulated_thinking,
 "tool_calls": list(tool_calls_by_id.values),
 "blocking_tasks": blocking_tasks,
 "agent_session_id": agent_session_id,
 }
 result_metadata = _build_result_metadata(runner)
 result = runner.result
 final_answer = (result.final_answer if result else None) or ""
 await _persist_run_phase(run_id, RunPhase.FINALIZING.value)
 writer({"type": PHASE_TRANSITION, "data": {"phase": "finalizing"}})
 return {
 "phase": RunPhase.FINALIZING.value,
 "final_answer": final_answer,
 "accumulated_thinking": accumulated_thinking,
 "tool_calls": list(tool_calls_by_id.values),
 "result_metadata": result_metadata,
 "agent_session_id": agent_session_id,
 }
async def _execute_with_results(
 state: WorkflowState,
 config: RunnableConfig,
 writer: StreamWriter,
 blocking_results: list[dict[str, Any]],
) -> dict[str, Any]:
 """二次运行 Chat runner：注入 blocking_results 作为上下文生成最终回答。"""
 build_result = await _build_chat_runner(config)
 if isinstance(build_result, dict):
 return build_result
 runner, agent_session_id = build_result
 cfg = config.get("configurable", {})
 conv_id = cfg.get("conversation_id", "")
 run_id = state.get("run_id", "")
 loop_count = state.get("wait_execute_loops", 0)
 # 防止 LLM 在阻塞任务失败后无限重试相同工具
 if loop_count >= 2:
 error_msg = "分析任务多次尝试后仍失败，请稍后重试。"
 await _persist_run_phase(run_id, RunPhase.ERROR.value)
 return {
 "phase": RunPhase.ERROR.value,
 "final_answer": error_msg,
 "accumulated_thinking": state.get("accumulated_thinking", ),
 "tool_calls": state.get("tool_calls", ),
 "result_metadata": {"error": error_msg, "status": "error"},
 "agent_session_id": agent_session_id,
 "blocking_results":,
 }
 await _persist_run_phase(run_id, RunPhase.EXECUTING.value)
 writer({"type": PHASE_TRANSITION, "data": {"phase": "executing"}})
 results_text = "\n\n".join(
 f"=== {r.get('task_type', 'unknown')} (task_id: {r.get('task_id', '?')}) ===\n"
 + (r.get("output", "") if r.get("success") else f"失败: {r.get('error', '未知错误')}")
 for r in blocking_results
 )
 prompt = (
 f"用户原始问题: {state.get('user_message', '')}\n\n"
 f"你之前发起了以下分析任务，现在所有结果已返回：\n\n"
 f"{results_text}\n\n"
 f"请根据这些分析结果，综合回答用户的问题。"
 )
 if conv_id:
 register_runner(conv_id, runner)
 try:
 accumulated_thinking, tool_calls_by_id = await _run_chat_stream(
 runner, prompt, writer, run_id,
 )
 except Exception:
 logger.exception(
 "executing_node_chat_runner_error_second_run",
 session_id=cfg.get("session_id", ""),
 )
 result = runner.result
 return {
 "phase": RunPhase.ERROR.value,
 "final_answer": (result.final_answer if result else None) or "",
 "accumulated_thinking": state.get("accumulated_thinking", ),
 "tool_calls": state.get("tool_calls", ),
 "result_metadata": {"error": "Chat runner 二次运行异常"},
 "agent_session_id": agent_session_id,
 "blocking_results":,
 }
 finally:
 if conv_id:
 unregister_runner(conv_id)
 all_thinking = state.get("accumulated_thinking", ) + accumulated_thinking
 all_tool_calls = state.get("tool_calls", ) + list(tool_calls_by_id.values)
 new_blocking = await _extract_blocking_tasks(
 tool_calls_by_id, cfg.get("conversation_id", ""),
 )
 if new_blocking:
 logger.info(
 "executing_node_blocking_tasks_in_second_run",
 count=len(new_blocking),
 )
 writer({"type": TASK_PROGRESS, "data": {"completed_count": 0, "total_count": len(new_blocking)}})
 await _persist_run_phase(run_id, RunPhase.WAITING.value)
 writer({"type": PHASE_TRANSITION, "data": {"phase": "waiting", "blocking_task_count": len(new_blocking)}})
 return {
 "phase": RunPhase.WAITING.value,
 "accumulated_thinking": all_thinking,
 "tool_calls": all_tool_calls,
 "blocking_tasks": new_blocking,
 "agent_session_id": agent_session_id,
 "blocking_results":,
 }
 result_metadata = _build_result_metadata(runner)
 result = runner.result
 final_answer = (result.final_answer if result else None) or ""
 await _persist_run_phase(run_id, RunPhase.FINALIZING.value)
 writer({"type": PHASE_TRANSITION, "data": {"phase": "finalizing"}})
 return {
 "phase": RunPhase.FINALIZING.value,
 "final_answer": final_answer,
 "accumulated_thinking": all_thinking,
 "tool_calls": all_tool_calls,
 "result_metadata": result_metadata,
 "agent_session_id": agent_session_id,
 "blocking_results":,
 }
async def waiting_node(state: WorkflowState) -> dict[str, Any]:
 """等待阻塞任务完成，resume 后回到 executing 继续推理。
 interrupt 暂停 graph 并将 blocking_tasks 作为 payload 保存。
 resume 值为 list[BlockingTaskResult]，作为 interrupt 的返回值传入。
 不在 interrupt 前放置副作用 — 避免 resume 时重放。
 """
 results = interrupt(state.get("blocking_tasks", ))
 blocking_results = results if isinstance(results, list) else [results]
 loop_count = state.get("wait_execute_loops", 0)
 return {
 "phase": RunPhase.EXECUTING.value,
 "blocking_results": blocking_results,
 "blocking_tasks":,
 "wait_execute_loops": loop_count + 1,
 }
async def finalizing_node(state: WorkflowState) -> dict[str, Any]:
 """收尾节点，标记 workflow 完成。"""
 return {"phase": RunPhase.COMPLETED.value}
def route_after_executing(state: WorkflowState) -> str:
 """条件路由：error 直接结束，有 blocking_tasks 走 waiting（含循环计数保护），否则走 finalizing。"""
 if state.get("phase") == RunPhase.ERROR.value:
 return END
 if state.get("blocking_tasks"):
 if state.get("wait_execute_loops", 0) >= 2:
 return "finalizing"
 return "waiting"
 return "finalizing"
def build_graph -> StateGraph:
 """构建编排 StateGraph builder。
 拓扑: START → planning → executing → (conditional) → finalizing → END
 ↘ waiting → executing（循环）↗
 """
 builder: StateGraph = StateGraph(WorkflowState)
 builder.add_node("planning", planning_node)
 builder.add_node("executing", executing_node)
 builder.add_node("waiting", waiting_node)
 builder.add_node("finalizing", finalizing_node)
 builder.add_edge(START, "planning")
 builder.add_edge("planning", "executing")
 builder.add_conditional_edges("executing", route_after_executing)
 builder.add_edge("waiting", "executing")
 builder.add_edge("finalizing", END)
 return builder
async def get_compiled_graph -> Any:
 """编译 graph 并绑定持久化 checkpointer（生产用 AsyncSqliteSaver）。"""
 checkpointer = await get_checkpointer
 return build_graph.compile(checkpointer=checkpointer)
