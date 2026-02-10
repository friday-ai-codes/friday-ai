"""Agent background tasks for session management.
Provides async functions for resuming suspended agent sessions
after user responses via Feishu card callbacks.
"""
import asyncio
from typing import Any
import structlog
from agents.core.context import AgentContext
from agents.core.loop import AgentConfig, AgentLoop
from agents.llm.claude import ClaudeProvider
from agents.models import AgentSession
logger = structlog.get_logger(__name__)
async def resume_agent_session(session_id: str, user_response: str) -> dict[str, Any]:
 """Resume a suspended agent session with user's response.
 Loads the suspended session, injects the user response as a tool result,
 and continues the Think-Act-Observe loop.
 Args:
 session_id: The agent session ID to resume
 user_response: The user's response text
 Returns:
 Dict with status and result information
 Example:
 >>> result = await resume_agent_session("sess-123", "Python")
 >>> print(result["status"]) # "completed" or "suspended"
 """
 log = logger.bind(session_id=session_id)
 log.info("resume_agent_session_start", response_preview=user_response[:50])
 try:
 # Load session
 session = await AgentSession.objects.select_related("project", "user").aget(
 session_id=session_id
 )
 # Update question history in temp_data
 temp_data = session.temp_data or {}
 history: list[dict[str, str]] = temp_data.get("question_history", )
 current_question = temp_data.get("current_question", "")
 if current_question:
 history.append({
 "question": current_question,
 "answer": user_response,
 })
 temp_data["question_history"] = history
 temp_data.pop("current_question", None)
 session.temp_data = temp_data
 await session.asave(update_fields=["temp_data"])
 # Create context and loop
 # Note: AgentContext types expect int but models use UUID - runtime compatible
 context = AgentContext(
 session_id=session_id,
 project_id=session.project_id, # type: ignore[arg-type]
 user_id=session.user_id, # type: ignore[arg-type]
 work_item_id=session.work_item_id or "",
 )
 # Use default config or restore from session metadata
 config = AgentConfig
 if session.metadata and "config" in session.metadata:
 stored_config = session.metadata["config"]
 config = AgentConfig(
 system_prompt=stored_config.get("system_prompt"),
 max_iterations=stored_config.get("max_iterations", 25),
 max_tokens=stored_config.get("max_tokens", 4096),
 tool_names=stored_config.get("tool_names"),
 )
 provider = ClaudeProvider
 loop = AgentLoop(config=config, context=context, provider=provider)
 # Resume execution
 result = await loop.resume(user_response)
 log.info(
 "resume_agent_session_complete",
 status=result.status,
 iterations=result.metadata.get("iterations"),
 )
 # Notify workflow engine if this is a workflow node session
 if session_id.startswith("wf-"):
 await _notify_workflow_completion(session_id, result, log)
 return {
 "status": result.status,
 "final_answer": result.final_answer,
 "output": result.output,
 "metadata": result.metadata,
 }
 except AgentSession.DoesNotExist:
 log.error("session_not_found")
 return {
 "status": "error",
 "error": f"Session not found: {session_id}",
 }
 except Exception as e:
 log.exception("resume_agent_session_error", error=str(e))
 return {
 "status": "error",
 "error": str(e),
 }
async def _notify_workflow_completion(
 session_id: str,
 result: Any,
 log: Any,
) -> None:
 """Notify workflow engine after agent session completes or re-suspends.
 When a workflow-originated agent session (session_id starts with "wf-")
 finishes execution, this function finds the corresponding NodeExecution
 and tells the WorkflowEngine to continue executing successors.
 If the agent re-suspends (e.g., waiting for another user interaction),
 no notification is needed — the workflow stays suspended until the next
 resume_agent_session call.
 """
 if result.status == "suspended":
 log.info("workflow_notify_skip_suspended")
 return
 try:
 from asgiref.sync import sync_to_async
 from workflows.engine.scheduler import WorkflowEngine
 from workflows.models.execution import (
 NodeExecution,
 NodeExecutionStatus,
 WorkflowExecution,
 )
 # Find the node execution linked to this session
 node_exec = await sync_to_async(
 lambda: NodeExecution.objects.filter(
 output_data__agent_session_id=session_id,
 status=NodeExecutionStatus.WAITING_EVENT,
 )
 .select_related("workflow_execution")
 .first
 )
 if not node_exec:
 log.warning("workflow_node_execution_not_found")
 return
 execution: WorkflowExecution = node_exec.workflow_execution
 if result.status == "completed":
 # Mark node as completed with agent output
 output_data = {
 "agent_session_id": session_id,
 "final_answer": result.final_answer,
 "output": result.output,
 "usage": result.usage,
 }
 await sync_to_async(node_exec.mark_completed)(output_data)
 # Continue workflow execution
 engine = WorkflowEngine
 await engine._continue_after_node(execution, node_exec)
 log.info("workflow_continued_after_node")
 else:
 # Agent errored or hit max_iterations
 error_msg = result.error or f"Agent session ended with status: {result.status}"
 await sync_to_async(node_exec.mark_failed)(error_msg)
 engine = WorkflowEngine
 await engine._handle_node_failure(execution, node_exec)
 log.warning("workflow_node_failed", agent_status=result.status)
 except Exception as e:
 log.exception("workflow_notify_error", error=str(e))
def schedule_resume_agent_session(session_id: str, user_response: str) -> None:
 """Schedule async resume task to run in background.
 Uses asyncio.create_task if in async context, otherwise creates
 a new event loop task. This allows the Feishu callback to return
 immediately without waiting for agent execution.
 Args:
 session_id: The agent session ID to resume
 user_response: The user's response text
 """
 log = logger.bind(session_id=session_id)
 try:
 # Try to get existing event loop
 loop = asyncio.get_running_loop
 # Schedule task in current loop
 loop.create_task(resume_agent_session(session_id, user_response))
 log.info("resume_task_scheduled_in_loop")
 except RuntimeError:
 # No running loop - create new one in thread
 import threading
 def run_in_thread -> None:
 asyncio.run(resume_agent_session(session_id, user_response))
 thread = threading.Thread(target=run_in_thread, daemon=True)
 thread.start
 log.info("resume_task_scheduled_in_thread")
