"""
LLM response types for the Agent framework.
Provides dataclasses for structured LLM responses including tool calls
and token usage tracking.
"""
from dataclasses import dataclass, field
from typing import Any
@dataclass
class ToolCall:
 """
 Represents a tool invocation requested by the LLM.
 Attributes:
 id: Unique tool_use_id from the LLM response
 name: Name of the tool to execute
 arguments: Parsed arguments dictionary for the tool
 """
 id: str
 name: str
 arguments: dict[str, Any]
@dataclass
class LLMResponse:
 """
 Standardized response from an LLM provider.
 Contains parsed text content, tool calls, token usage metrics,
 and the raw content blocks for message history reconstruction.
 Attributes:
 content: Concatenated text content from the response
 raw_content: Original content blocks (for message history)
 tool_calls: List of parsed tool calls (empty if none requested)
 usage: Token usage dict with 'input_tokens' and 'output_tokens'
 stop_reason: Why the response ended (end_turn, tool_use, max_tokens, etc.)
 """
 content: str
 raw_content: list[Any]
 tool_calls: list[ToolCall] = field(default_factory=list)
 usage: dict[str, int] = field(default_factory=dict)
 stop_reason: str | None = None
 @property
 def has_tool_calls(self) -> bool:
 """Check if the response contains any tool calls."""
 return len(self.tool_calls) > 0
