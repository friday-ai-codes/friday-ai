"""
Tool decorator and core types for the Agent tool framework.

Provides the @tool decorator for registering async functions as agent tools,
along with ToolResult and ToolDefinition types.
"""

import functools
import inspect
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


class ToolCategory(Enum):
    """Categories of tools available to the agent."""

    PROJECT = "PROJECT"  # Space and repository operations
    KNOWLEDGE = "KNOWLEDGE"  # Knowledge base and context retrieval
    FEISHU = "FEISHU"  # Feishu integration (docs, messages)
    SUBAGENT = "SUBAGENT"  # Claude Code subagent operations
    GENERAL = "GENERAL"  # General utility tools
    # implementation RELEV：召回 / 相关性聚合类工具
    RETRIEVAL = "RETRIEVAL"
    # 主动与用户协商澄清类工具（ask_clarification）。
    # 与 GENERAL 区分语义：调用此类工具会让 graph 进入 waiting_clarification
    # 状态并 interrupt，等待用户答复后才能继续推理。
    COMMUNICATION = "COMMUNICATION"


@dataclass
class ToolResult:
    """
    Standardized result from tool execution.

    All tools return ToolResult to provide consistent output format
    for the agent to process.
    """

    success: bool
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_call_id: str = ""  # Set by executor

    def to_content(self) -> str:
        """
        Convert result to string content for LLM consumption.

        Returns JSON string for dict/list output, str(output) for other types,
        or "Error: {error}" if not successful.
        """
        if not self.success:
            return f"Error: {self.error}"

        if self.output is None:
            return "Success (no output)"

        if isinstance(self.output, (dict, list)):
            return json.dumps(self.output, ensure_ascii=False, indent=2)

        return str(self.output)


@dataclass
class ToolDefinition:
    """
    Definition of a registered tool.

    Contains all metadata needed for the agent to understand
    and invoke the tool.
    """

    name: str
    description: str
    category: ToolCategory
    parameters: dict[str, Any]  # JSON Schema
    func: Callable[..., Any]  # The async function
    requires_suspension: bool = False  # For tools like ask_user_question


# Module-level registry of all tools
_tool_registry: dict[str, ToolDefinition] = {}


def tool(
    name: str,
    description: str,
    category: str = "GENERAL",
    parameters: dict[str, Any] | None = None,
    requires_suspension: bool = False,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Decorator to register an async function as an agent tool.

    Args:
        name: Unique name for the tool (used in tool_use blocks)
        description: Human-readable description for the LLM
        category: Tool category (PROJECT, KNOWLEDGE, FEISHU, SUBAGENT, GENERAL)
        parameters: JSON Schema for tool parameters. If None, uses empty schema.
        requires_suspension: If True, tool execution suspends the agent loop
            (e.g., for user questions that need external response)

    Returns:
        Decorator function that registers the tool

    Raises:
        TypeError: If the decorated function is not async (coroutine function)
        ValueError: If a tool with the same name is already registered

    Example:
        @tool(
            name="search_repository_code",
            description="Search for code in the repository",
            category="PROJECT",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "file_pattern": {"type": "string", "description": "Glob pattern"}
                },
                "required": ["query"]
            }
        )
        async def search_repository_code(query: str, file_pattern: str = "**/*") -> ToolResult:
            # Implementation
            return ToolResult(success=True, output=results)
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        # Validate that the function is async
        if not inspect.iscoroutinefunction(func):
            raise TypeError(
                f"Tool '{name}' must be an async function (use 'async def'). "
                f"Got: {type(func).__name__}"
            )

        # Check for duplicate registration
        if name in _tool_registry:
            raise ValueError(
                f"Tool '{name}' is already registered. "
                f"Existing: {_tool_registry[name].func.__module__}.{_tool_registry[name].func.__name__}"
            )

        # Parse category
        try:
            tool_category = ToolCategory[category.upper()]
        except KeyError:
            valid_categories = [c.name for c in ToolCategory]
            raise ValueError(
                f"Invalid category '{category}' for tool '{name}'. "
                f"Valid categories: {valid_categories}"
            )

        # Use default schema if not provided
        tool_parameters = parameters or {"type": "object", "properties": {}}

        # Create tool definition
        definition = ToolDefinition(
            name=name,
            description=description,
            category=tool_category,
            parameters=tool_parameters,
            func=func,
            requires_suspension=requires_suspension,
        )

        # Register the tool
        _tool_registry[name] = definition

        # Create wrapper that preserves signature
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            return await func(*args, **kwargs)

        # Attach definition to wrapper for introspection
        wrapper._tool_definition = definition  # type: ignore[attr-defined]

        return wrapper  # type: ignore[return-value]

    return decorator
