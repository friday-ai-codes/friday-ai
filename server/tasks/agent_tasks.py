"""Agent background tasks for session management.
Provides async functions for resuming suspended agent sessions
after user responses via Feishu card callbacks.
"""
import asyncio
from typing import Any
import structlog
from agents.core.context import AgentContext
from agents.core.loop import AgentConfig, AgentLoop
from agents.llm.base import create_provider
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
 log.info("开始恢复 Agent 会话", response_preview=user_response[:50])
 try:
 # Load session
 session = await AgentSession.objects.select_related("project", "user").aget(
 session_id=session_id
 )
 # 检查 session 是否已经完成（用户回答前 agent 可能已经跑完了）
 if session.status in (AgentSession.Status.COMPLETED, AgentSession.Status.ERROR, AgentSession.Status.MAX_ITERATIONS):
 log.info(
 "会话已处于终态，跳过恢复",
 session_status=session.status,
 )
 return {
 "status": session.status,
 "error": f"Session already in terminal state: {session.status}",
 }
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
 # Recover chat_id if missing (may have been lost by earlier bug)
 if not temp_data.get("chat_id") and session_id.startswith("wf-"):
 chat_id = await _recover_chat_id_from_node(session_id, log)
 if chat_id:
 temp_data["chat_id"] = chat_id
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
 # Create provider with project's Claude config
 from services.claude_config import aget_claude_config
 claude_config = await aget_claude_config(session.project)
 if not claude_config.api_key:
 raise ValueError("未配置 Claude API Key，请在系统设置或项目设置中配置")
 if not claude_config.model:
 raise ValueError("未配置默认模型，请在系统设置或项目设置中配置默认模型")
 provider = create_provider(
 claude_config.provider_type,
 api_key=claude_config.api_key,
 base_url=claude_config.base_url,
 model=claude_config.model,
 )
 loop = AgentLoop(config=config, context=context, provider=provider)
 # Resume execution
 result = await loop.resume(user_response)
 log.info(
 "Agent 会话恢复完成",
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
 log.error("会话未找到")
 return {
 "status": "error",
 "error": f"Session not found: {session_id}",
 }
 except Exception as e:
 log.exception("恢复 Agent 会话出错", error=str(e))
 return {
 "status": "error",
 "error": str(e),
 }
async def _recover_chat_id_from_node(session_id: str, log: Any) -> str:
 """Recover chat_id from WorkflowNode config when missing from temp_data.
 Looks up the NodeExecution linked to this session_id, then reads
 chat_id from the associated WorkflowNode's config.
 Args:
 session_id: The agent session ID (format: wf-{execution_id}-{node_id})
 log: Bound logger
 Returns:
 The chat_id string, or empty string if not found
 """
 try:
 from workflows.models.execution import NodeExecution
 node_exec = await NodeExecution.objects.filter( # type: ignore[attr-defined]
 output_data__session_id=session_id,
 ).select_related("node").afirst
 if node_exec and node_exec.node:
 chat_id = node_exec.node.config.get("chat_id", "")
 if chat_id:
 log.info("从节点恢复 chat_id", chat_id=chat_id)
 return chat_id
 log.warning("chat_id 恢复失败", reason="node_execution_not_found_or_no_chat_id")
 return ""
 except Exception as e:
 log.warning("chat_id 恢复出错", error=str(e))
 return ""
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
 log.info("工作流节点挂起中，跳过通知")
 return
 try:
 from workflows.engine.scheduler import WorkflowEngine
 from workflows.models.execution import (
 NodeExecution,
 NodeExecutionStatus,
 WorkflowExecution,
 )
 # Find the node execution linked to this session
 node_exec = await NodeExecution.objects.filter( # type: ignore[attr-defined]
 output_data__session_id=session_id,
 status=NodeExecutionStatus.WAITING_EVENT,
 ).select_related("workflow_execution").afirst
 if not node_exec:
 log.warning("未找到工作流节点执行记录")
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
 await node_exec.amark_completed(output_data)
 # Continue workflow execution
 engine = WorkflowEngine
 await engine._continue_after_node(execution, node_exec)
 log.info("工作流已继续执行下一节点")
 else:
 # Agent errored or hit max_iterations
 error_msg = result.error or f"Agent session ended with status: {result.status}"
 await node_exec.amark_failed(error_msg)
 engine = WorkflowEngine
 await engine._handle_node_failure(execution, node_exec)
 log.warning("工作流节点执行失败", agent_status=result.status)
 except Exception as e:
 log.exception("工作流通知出错", error=str(e))
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
 log.info("恢复任务已加入事件循环")
 except RuntimeError:
 # No running loop - create new one in thread
 import threading
 def run_in_thread -> None:
 asyncio.run(resume_agent_session(session_id, user_response))
 thread = threading.Thread(target=run_in_thread, daemon=True)
 thread.start
 log.info("恢复任务已在新线程中调度")
