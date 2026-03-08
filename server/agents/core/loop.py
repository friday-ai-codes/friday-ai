"""
AgentLoop - Core execution engine implementing the Think-Act-Observe cycle.
Orchestrates the agent's iterative process of:
1. THINK: Call LLM with conversation history and available tools
2. ACT: Execute any tool calls requested by the LLM
3. OBSERVE: Add tool results to conversation and continue
Supports suspension for human-in-the-loop workflows and resumption.
"""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import structlog
from agents.core.context import AgentContext
from agents.core.events import (
 AgentEvent,
 ERROR,
 MESSAGE_COMPLETE,
 TEXT_DELTA,
 THINKING,
 TOOL_USE_RESULT,
 TOOL_USE_START,
)
from agents.core.result import AgentResult
from agents.core.state import AgentState, AgentStateManager, AgentStatus
from agents.llm.base import LLMProvider
from agents.llm.types import ToolCall
from agents.tools.base import ToolResult
from agents.tools.registry import ToolRegistry
logger = structlog.get_logger
@dataclass
class AgentConfig:
 """
 Configuration for an AgentLoop execution.
 Controls system prompt, iteration limits, and tool availability.
 """
 system_prompt: str | None = None
 """Optional system prompt to initialize the conversation."""
 max_iterations: int = 25
 """Maximum number of Think-Act-Observe iterations before stopping."""
 max_tokens: int = 4096
 """Maximum tokens per LLM response."""
 tool_names: list[str] | None = None
 """Limit available tools to these names. None means all tools."""
class AgentLoop:
 """
 Core agent execution engine implementing the ReAct pattern.
 Manages the Think-Act-Observe loop, tool execution, state persistence,
 and supports suspension/resumption for human-in-the-loop workflows.
 Example:
 config = AgentConfig(system_prompt="You are a helpful assistant.")
 context = AgentContext(session_id="sess-123", project_id=1, user_id=1)
 provider = ClaudeProvider
 loop = AgentLoop(config=config, context=context, provider=provider)
 result = await loop.run("Help me analyze this code")
 """
 def __init__(
 self,
 config: AgentConfig,
 context: AgentContext,
 provider: LLMProvider,
 registry: type[ToolRegistry] = ToolRegistry,
 on_event: Callable[[AgentEvent], Awaitable[None]] | None = None,
 ) -> None:
 """
 Initialize the agent loop.
 Args:
 config: Configuration for this execution
 context: Session and project context
 provider: LLM provider for chat completions
 registry: Tool registry class (default: ToolRegistry)
 on_event: Optional async callback for runtime events (SSE streaming)
 """
 self.config = config
 self.context = context
 self.provider = provider
 self.registry = registry
 self.on_event = on_event
 self.state_manager = AgentStateManager
 self.logger = structlog.get_logger.bind(session_id=context.session_id)
 async def _emit(self, event: AgentEvent) -> None:
 """发射事件给回调。无回调时静默跳过。"""
 if self.on_event is not None:
 await self.on_event(event)
 async def run(self, user_message: str) -> AgentResult:
 """
 Start a new agent execution with the given user message.
 Creates initial state, adds system and user messages,
 then executes the Think-Act-Observe loop.
 Args:
 user_message: The user's initial message/request
 Returns:
 AgentResult with outputs, final answer, and execution metadata
 """
 self.logger.info("Agent 开始运行", user_message_length=len(user_message))
 # Initialize state
 messages: list[dict[str, Any]] =
 # Add system prompt if configured
 if self.config.system_prompt:
 messages.append({
 "role": "system",
 "content": self.config.system_prompt,
 })
 # Add user message
 messages.append({
 "role": "user",
 "content": user_message,
 })
 # Preserve existing temp_data (e.g. chat_id set by _ensure_agent_session)
 existing_temp_data: dict[str, Any] = {}
 existing_state = await self.state_manager.load_state(self.context.session_id)
 if existing_state is not None:
 existing_temp_data = existing_state.temp_data
 state = AgentState(
 session_id=self.context.session_id,
 status=AgentStatus.RUNNING,
 messages=messages,
 temp_data=existing_temp_data,
 )
 return await self._execute_loop(state)
 async def resume(self, user_response: str) -> AgentResult:
 """
 Resume a suspended agent execution with user's response.
 Loads the suspended state, injects the user response as a tool result,
 then continues the Think-Act-Observe loop.
 Args:
 user_response: User's response to the pending tool call
 Returns:
 AgentResult with outputs, final answer, and execution metadata
 Raises:
 ValueError: If session not found or not in SUSPENDED status
 """
 self.logger.info("Agent 恢复执行")
 # Load existing state
 state = await self.state_manager.load_state(self.context.session_id)
 if state is None:
 raise ValueError(f"Session not found: {self.context.session_id}")
 if state.status != AgentStatus.SUSPENDED:
 raise ValueError(
 f"Cannot resume session in status {state.status.value}. "
 "Only SUSPENDED sessions can be resumed."
 )
 # Get pending tool call info
 pending = state.pending_tool_call
 if pending is None:
 raise ValueError("Session is suspended but has no pending tool call")
 tool_call_id = pending.get("tool_call_id", "")
 # Inject user response as tool result
 state.messages.append({
 "role": "user",
 "content": [
 {
 "type": "tool_result",
 "tool_use_id": tool_call_id,
 "content": user_response,
 "is_error": False,
 }
 ],
 })
 # Clear suspension state
 state.pending_tool_call = None
 state.status = AgentStatus.RUNNING
 return await self._execute_loop(state)
 async def _execute_loop(self, state: AgentState) -> AgentResult:
 """
 Execute the Think-Act-Observe loop until completion or limit.
 Core loop that:
 1. Calls LLM with current messages and tools
 2. If no tool calls: return final answer
 3. Execute tool calls and add results to messages
 4. Persist state and continue
 Args:
 state: Current agent state
 Returns:
 AgentResult with execution outcome
 """
 tool_calls_count = 0
 while state.iteration < self.config.max_iterations:
 state.iteration += 1
 self.logger.info("Agent 迭代中", iteration=state.iteration)
 # 发射 thinking 事件
 await self._emit(AgentEvent(type=THINKING, data={"iteration": state.iteration}))
 # THINK: Call LLM (流式或非流式)
 tools = self._get_tool_schemas
 if self.on_event is not None and hasattr(self.provider, "stream_chat"):
 # 流式路径：每个 text delta 发射事件
 async def on_text(delta: str) -> None:
 await self._emit(AgentEvent(type=TEXT_DELTA, data={"text": delta}))
 response = await self.provider.stream_chat(
 messages=state.messages,
 tools=tools if tools else None,
 max_tokens=self.config.max_tokens,
 on_text=on_text,
 )
 else:
 # 非流式路径：与之前行为一致
 response = await self.provider.chat(
 messages=state.messages,
 tools=tools if tools else None,
 max_tokens=self.config.max_tokens,
 )
 # Accumulate token usage
 state.usage["input_tokens"] += response.usage.get("input_tokens", 0)
 state.usage["output_tokens"] += response.usage.get("output_tokens", 0)
 # Check for completion (no tool calls = final answer)
 if not response.has_tool_calls:
 state.status = AgentStatus.COMPLETED
 await self.state_manager.save_state(state, self.context)
 self.logger.info(
 "Agent 执行完成",
 iterations=state.iteration,
 tool_calls=tool_calls_count,
 input_tokens=state.usage["input_tokens"],
 output_tokens=state.usage["output_tokens"],
 )
 # 发射 message_complete 事件
 await self._emit(AgentEvent(
 type=MESSAGE_COMPLETE,
 data={
 "usage": state.usage,
 "status": "completed",
 "iterations": state.iteration,
 "model": getattr(self.provider, "model", ""),
 },
 ))
 return AgentResult(
 output=state.output_items,
 final_answer=response.content,
 status="completed",
 usage=state.usage,
 metadata={
 "iterations": state.iteration,
 "tool_calls_count": tool_calls_count,
 },
 )
 # Add assistant message with tool_use blocks
 state.messages.append({
 "role": "assistant",
 "content": response.raw_content,
 })
 # ACT: Execute tools
 tool_results = await self._execute_tools(response.tool_calls, state)
 tool_calls_count += len(tool_results)
 # Check for suspension
 for result in tool_results:
 if result.metadata.get("suspension"):
 # Add ALL tool results to messages before suspending,
 # so the conversation history stays consistent
 # (every tool_use must have a matching tool_result)
 non_suspension_results = [
 {
 "type": "tool_result",
 "tool_use_id": r.tool_call_id,
 "content": r.to_content,
 "is_error": not r.success,
 }
 for r in tool_results
 if not r.metadata.get("suspension")
 ]
 if non_suspension_results:
 state.messages.append({
 "role": "user",
 "content": non_suspension_results,
 })
 state.status = AgentStatus.SUSPENDED
 state.pending_tool_call = {
 "tool_call_id": result.tool_call_id,
 "tool_name": result.metadata.get("tool_name"),
 **result.metadata,
 }
 await self.state_manager.save_state(state, self.context)
 self.logger.info(
 "Agent 已挂起",
 iteration=state.iteration,
 tool_name=result.metadata.get("tool_name"),
 )
 return AgentResult(
 output=state.output_items,
 status="suspended",
 usage=state.usage,
 metadata={
 "iterations": state.iteration,
 "tool_calls_count": tool_calls_count,
 "suspension": state.pending_tool_call,
 },
 )
 # OBSERVE: Add tool results to messages
 tool_result_content = [
 {
 "type": "tool_result",
 "tool_use_id": r.tool_call_id,
 "content": r.to_content,
 "is_error": not r.success,
 }
 for r in tool_results
 ]
 state.messages.append({
 "role": "user",
 "content": tool_result_content,
 })
 # Persist state after each iteration
 await self.state_manager.save_state(state, self.context)
 # Max iterations reached
 state.status = AgentStatus.MAX_ITERATIONS
 await self.state_manager.save_state(state, self.context)
 self.logger.warning(
 "Agent 达到最大迭代次数",
 iterations=state.iteration,
 tool_calls=tool_calls_count,
 )
 # 发射 message_complete 事件（max_iterations 场景）
 await self._emit(AgentEvent(
 type=MESSAGE_COMPLETE,
 data={
 "usage": state.usage,
 "status": "max_iterations",
 "iterations": state.iteration,
 "model": getattr(self.provider, "model", ""),
 },
 ))
 return AgentResult(
 output=state.output_items,
 final_answer="Reached maximum iterations limit",
 status="max_iterations",
 usage=state.usage,
 metadata={
 "iterations": state.iteration,
 "tool_calls_count": tool_calls_count,
 },
 )
 async def _execute_tools(
 self,
 tool_calls: list[ToolCall],
 state: AgentState,
 ) -> list[ToolResult]:
 """
 Execute a list of tool calls sequentially.
 For each tool:
 1. Get tool from registry
 2. Validate arguments
 3. Execute with error handling
 4. Log to database
 Args:
 tool_calls: List of tool calls from LLM
 state: Current agent state for context
 Returns:
 List of ToolResult objects
 """
 results: list[ToolResult] =
 for tool_call in tool_calls:
 started_at = datetime.now(timezone.utc)
 self.logger.debug(
 "开始执行工具",
 tool_name=tool_call.name,
 tool_call_id=tool_call.id,
 )
 # Get tool definition
 tool_def = self.registry.get_tool(tool_call.name)
 if tool_def is None:
 result = ToolResult(
 success=False,
 error=f"Tool not found: {tool_call.name}",
 tool_call_id=tool_call.id,
 )
 results.append(result)
 continue
 # 发射 tool_use_start 事件
 await self._emit(AgentEvent(
 type=TOOL_USE_START,
 data={
 "tool_name": tool_call.name,
 "tool_call_id": tool_call.id,
 "input": tool_call.arguments,
 },
 ))
 # Validate arguments
 valid, error_msg = self.registry.validate_tool_arguments(
 tool_call.name, tool_call.arguments
 )
 if not valid:
 result = ToolResult(
 success=False,
 error=f"Invalid arguments: {error_msg}",
 tool_call_id=tool_call.id,
 )
 results.append(result)
 await self.state_manager.log_tool_call(
 session_id=state.session_id,
 tool_name=tool_call.name,
 tool_call_id=tool_call.id,
 arguments=tool_call.arguments,
 result=result,
 started_at=started_at,
 iteration=state.iteration,
 )
 continue
 # Execute tool
 try:
 result = await tool_def.func(**tool_call.arguments)
 # Ensure result is ToolResult
 if not isinstance(result, ToolResult):
 result = ToolResult(
 success=True,
 output=result,
 tool_call_id=tool_call.id,
 )
 else:
 result.tool_call_id = tool_call.id
 # Add tool name to metadata for suspension handling
 result.metadata["tool_name"] = tool_call.name
 # Check if tool requires suspension
 if tool_def.requires_suspension:
 result.metadata["suspension"] = True
 # Collect output items
 if result.success and result.output is not None:
 state.output_items.append(result.output)
 except Exception as e:
 self.logger.exception(
 "工具执行出错",
 tool_name=tool_call.name,
 error=str(e),
 )
 result = ToolResult(
 success=False,
 error=str(e),
 tool_call_id=tool_call.id,
 metadata={"tool_name": tool_call.name},
 )
 results.append(result)
 # Log tool call to database
 await self.state_manager.log_tool_call(
 session_id=state.session_id,
 tool_name=tool_call.name,
 tool_call_id=tool_call.id,
 arguments=tool_call.arguments,
 result=result,
 started_at=started_at,
 iteration=state.iteration,
 )
 # 发射 tool_use_result 事件
 result_text = (str(result.output)[:200] if result.output else result.error or "")[:200]
 await self._emit(AgentEvent(
 type=TOOL_USE_RESULT,
 data={
 "tool_name": tool_call.name,
 "tool_call_id": tool_call.id,
 "success": result.success,
 "result": result_text,
 },
 ))
 self.logger.debug(
 "工具执行完成",
 tool_name=tool_call.name,
 success=result.success,
 )
 return results
 def _get_tool_schemas(self) -> list[dict[str, Any]]:
 """
 Get tool schemas for the LLM, optionally filtered by config.
 Returns:
 List of tool schemas in Anthropic format
 """
 return self.registry.get_tool_schemas(self.config.tool_names)
