"""
AgentContext dataclass for session and project information.
Provides runtime context for agent execution including session identification,
project association, and user information.
"""
from dataclasses import dataclass, field
from typing import Any
@dataclass
class AgentContext:
 """
 Runtime context for an agent execution session.
 Contains identification and association information needed
 throughout the agent's execution lifecycle.
 """
 session_id: str
 """Unique identifier for this agent session."""
 project_id: int
 """ID of the associated project."""
 user_id: int
 """ID of the user who initiated the session."""
 work_item_id: str | None = None
 """Optional Feishu work item ID this session is related to."""
 metadata: dict[str, Any] = field(default_factory=dict)
 """Additional context data (e.g., trigger source, request info)."""
