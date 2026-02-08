"""
AgentState and AgentStateManager for runtime state and persistence.
Provides state management for agent execution, including status tracking,
message history, and database persistence via Django async ORM.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
import structlog
from agents.core.context import AgentContext
from agents.models import AgentSession, ToolCallLog
from agents.tools.base import ToolResult
logger = structlog.get_logger
# Suspension expiration policy
SUSPENSION_EXPIRY_DAYS = 7
"""Sessions suspended for more than this many days are considered expired."""
class AgentStatus(Enum):
 """Status of an agent execution session."""
 RUNNING = "running"
 SUSPENDED = "suspended"
 COMPLETED = "completed"
 ERROR = "error"
 MAX_ITERATIONS = "max_iterations"
@dataclass
class AgentState:
 """
 Runtime state of an agent execution.
 Tracks conversation history, iteration count, token usage,
 and any pending tool calls for suspension handling.
 """
 session_id: str
 """Unique identifier for this session."""
 status: AgentStatus
 """Current execution status."""
 messages: list[dict[str, Any]]
 """Conversation history (system, user, assistant, tool_result messages)."""
 iteration: int = 0
 """Current iteration count in the Think-Act-Observe loop."""
 usage: dict[str, int] = field(
 default_factory=lambda: {"input_tokens": 0, "output_tokens": 0}
 )
 """Accumulated token usage across all LLM calls."""
 pending_tool_call: dict[str, Any] | None = None
 """Tool call awaiting external response (for suspension)."""
 output_items: list[Any] = field(default_factory=list)
 """Accumulated outputs from tool executions."""
 temp_data: dict[str, Any] = field(default_factory=dict)
 """Tool-specific temporary data for suspension persistence."""
class AgentStateManager:
 """
 Manages persistence of agent state to database.
 Uses Django async ORM to save/load AgentSession and log ToolCallLog entries.
 """
 async def save_state(self, state: AgentState, context: AgentContext) -> None:
 """
 Persist agent state to database.
 Creates or updates the AgentSession record with current state.
 Args:
 state: Current agent state to persist
 context: Agent context with project/user info
 """
 # Prepare metadata
 metadata = {
 "iteration_count": state.iteration,
 "usage": state.usage,
 }
 # Map AgentStatus to AgentSession.Status
 status_map = {
 AgentStatus.RUNNING: AgentSession.Status.RUNNING,
 AgentStatus.SUSPENDED: AgentSession.Status.SUSPENDED,
 AgentStatus.COMPLETED: AgentSession.Status.COMPLETED,
 AgentStatus.ERROR: AgentSession.Status.ERROR,
 AgentStatus.MAX_ITERATIONS: AgentSession.Status.MAX_ITERATIONS,
 }
 await AgentSession.objects.aupdate_or_create(
 session_id=state.session_id,
 defaults={
 "project_id": context.project_id,
 "user_id": context.user_id,
 "work_item_id": context.work_item_id or "",
 "status": status_map[state.status],
 "messages": state.messages,
 "pending_tool_call": state.pending_tool_call,
 "output": state.output_items,
 "metadata": metadata,
 "suspended_at": (
 datetime.now(timezone.utc)
 if state.status == AgentStatus.SUSPENDED
 else None
 ),
 "temp_data": state.temp_data,
 },
 )
 logger.debug(
 "agent_state_saved",
 session_id=state.session_id,
 status=state.status.value,
 iteration=state.iteration,
 )
 async def load_state(self, session_id: str) -> AgentState | None:
 """
 Load agent state from database.
 Args:
 session_id: Session ID to load
 Returns:
 AgentState if found, None otherwise
 """
 try:
 session = await AgentSession.objects.aget(session_id=session_id)
 except AgentSession.DoesNotExist:
 return None
 # Map AgentSession.Status back to AgentStatus (use string keys for Django CharField)
 status_map: dict[str, AgentStatus] = {
 AgentSession.Status.RUNNING.value: AgentStatus.RUNNING,
 AgentSession.Status.SUSPENDED.value: AgentStatus.SUSPENDED,
 AgentSession.Status.COMPLETED.value: AgentStatus.COMPLETED,
 AgentSession.Status.ERROR.value: AgentStatus.ERROR,
 AgentSession.Status.MAX_ITERATIONS.value: AgentStatus.MAX_ITERATIONS,
 }
 metadata = session.metadata or {}
 usage = metadata.get("usage", {"input_tokens": 0, "output_tokens": 0})
 # session.status is a string from CharField
 agent_status = status_map.get(session.status, AgentStatus.RUNNING)
 return AgentState(
 session_id=session.session_id,
 status=agent_status,
 messages=session.messages or,
 iteration=metadata.get("iteration_count", 0),
 usage=usage,
 pending_tool_call=session.pending_tool_call,
 output_items=session.output or,
 temp_data=session.temp_data or {},
 )
 async def log_tool_call(
 self,
 session_id: str,
 tool_name: str,
 tool_call_id: str,
 arguments: dict[str, Any],
 result: ToolResult,
 started_at: datetime,
 iteration: int,
 ) -> None:
 """
 Log a tool execution to the database.
 Args:
 session_id: Session this tool call belongs to
 tool_name: Name of the tool that was executed
 tool_call_id: Unique ID for this tool call
 arguments: Arguments passed to the tool
 result: Result from tool execution
 started_at: When tool execution started
 iteration: Which iteration this call occurred in
 """
 completed_at = datetime.now(timezone.utc)
 duration_ms = int((completed_at - started_at).total_seconds * 1000)
 # Get the session for the foreign key
 try:
 session = await AgentSession.objects.aget(session_id=session_id)
 except AgentSession.DoesNotExist:
 logger.warning(
 "tool_call_log_skipped",
 session_id=session_id,
 reason="session_not_found",
 )
 return
 await ToolCallLog.objects.acreate(
 session=session,
 tool_name=tool_name,
 tool_call_id=tool_call_id,
 arguments=arguments,
 result_success=result.success,
 result_output=result.output if result.success else None,
 result_error=result.error or "",
 started_at=started_at,
 completed_at=completed_at,
 duration_ms=duration_ms,
 iteration=iteration,
 )
 logger.debug(
 "tool_call_logged",
 session_id=session_id,
 tool_name=tool_name,
 success=result.success,
 duration_ms=duration_ms,
 )
 async def check_session_expired(self, session_id: str) -> bool:
 """
 Check if a suspended session has expired (7+ days).
 Args:
 session_id: Session ID to check
 Returns:
 True if session is expired or does not exist
 """
 try:
 session = await AgentSession.objects.aget(session_id=session_id)
 except AgentSession.DoesNotExist:
 return True # Non-existent is considered expired
 if session.status != AgentSession.Status.SUSPENDED:
 return False
 if session.suspended_at is None:
 return False
 expiry_time = session.suspended_at + timedelta(days=SUSPENSION_EXPIRY_DAYS)
 return datetime.now(timezone.utc) > expiry_time
 async def expire_old_sessions(self) -> int:
 """
 Mark expired suspended sessions as error.
 Sessions suspended for more than SUSPENSION_EXPIRY_DAYS are marked
 as ERROR with temp_data cleared.
 Returns:
 Number of sessions marked as expired
 """
 expiry_cutoff = datetime.now(timezone.utc) - timedelta(
 days=SUSPENSION_EXPIRY_DAYS
 )
 updated = await AgentSession.objects.filter(
 status=AgentSession.Status.SUSPENDED,
 suspended_at__lt=expiry_cutoff,
 ).aupdate(
 status=AgentSession.Status.ERROR,
 final_answer="Session expired after 7 days of inactivity",
 temp_data={},
 )
 if updated > 0:
 logger.info("expired_sessions", count=updated)
 return updated
 async def create_full_snapshot(self, state: AgentState) -> dict[str, Any]:
 """
 Create a full snapshot dict for debugging/export.
 Includes all state fields plus a timestamp.
 Args:
 state: Agent state to snapshot
 Returns:
 Dictionary with complete state snapshot
 """
 return {
 "session_id": state.session_id,
 "status": state.status.value,
 "iteration": state.iteration,
 "messages": state.messages,
 "pending_tool_call": state.pending_tool_call,
 "output_items": state.output_items,
 "temp_data": state.temp_data,
 "usage": state.usage,
 "snapshot_at": datetime.now(timezone.utc).isoformat,
 }
