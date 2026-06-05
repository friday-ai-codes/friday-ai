"""
AgentContext dataclass for session and space information.

Provides runtime context for agent execution including session identification,
space association, and user information.
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

    space_id: Any = None
    """ID of the associated space (UUID or int)."""

    user_id: Any = None
    """ID of the user who initiated the session (UUID or int)."""

    work_item_id: str | None = None
    """Optional Feishu work item ID this session is related to."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional context data (e.g., trigger source, request info)."""
