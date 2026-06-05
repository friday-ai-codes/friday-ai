"""
AgentResult dataclass for agent loop output.

Provides a standardized result type for agent execution outcomes.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    """
    Result of an agent execution.

    Contains all outputs, final answer, status, and metadata
    from an agent's Think-Act-Observe loop execution.
    """

    output: list[Any]
    """Collected outputs from tool executions."""

    status: str
    """Final status: 'completed', 'suspended', 'error', or 'max_iterations'."""

    final_answer: str | None = None
    """LLM's final response text (when status is 'completed')."""

    usage: dict[str, int] = field(default_factory=dict)
    """Total token usage: {'input_tokens': N, 'output_tokens': M}."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional info (iterations count, tool_calls_count, suspension details)."""

    error: str | None = None
    """Error message if status is 'error'."""
