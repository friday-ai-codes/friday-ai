"""
Tool registry for discovering and managing registered tools.

Provides methods to:
- Get all registered tools
- Get tools by category
- Generate Anthropic-compatible tool schemas
- Validate tool arguments
"""

from typing import Any

from agents.tools.base import ToolCategory, ToolDefinition, _tool_registry
from agents.tools.schema import validate_arguments


class ToolRegistry:
    """
    Registry for discovering and managing agent tools.

    All methods are class methods since the registry is module-level.
    Tools are registered via the @tool decorator.
    """

    @classmethod
    def get_all_tools(cls) -> list[ToolDefinition]:
        """
        Get all registered tools.

        Returns:
            List of all ToolDefinition objects.
        """
        return list(_tool_registry.values())

    @classmethod
    def get_tool(cls, name: str) -> ToolDefinition | None:
        """
        Get a tool by name.

        Args:
            name: The tool name to look up

        Returns:
            ToolDefinition if found, None otherwise.
        """
        return _tool_registry.get(name)

    @classmethod
    def get_tools_by_category(cls, category: str | ToolCategory) -> list[ToolDefinition]:
        """
        Get all tools in a specific category.

        Args:
            category: Category name (string) or ToolCategory enum

        Returns:
            List of ToolDefinition objects in the category.
        """
        if isinstance(category, str):
            try:
                category = ToolCategory[category.upper()]
            except KeyError:
                return []

        return [t for t in _tool_registry.values() if t.category == category]

    @classmethod
    def get_tool_schemas(
        cls, tool_names: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """
        Get Anthropic-compatible tool schemas for the specified tools.

        Args:
            tool_names: Optional list of tool names to include.
                If None, returns schemas for all registered tools.

        Returns:
            List of tool schema dicts in Anthropic format:
            {"name": str, "description": str, "input_schema": dict}
        """
        if tool_names is not None:
            tools = [_tool_registry[name] for name in tool_names if name in _tool_registry]
        else:
            tools = list(_tool_registry.values())

        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]

    @classmethod
    def validate_tool_arguments(
        cls, tool_name: str, arguments: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """
        Validate arguments for a specific tool against its JSON Schema.

        Args:
            tool_name: Name of the tool to validate against
            arguments: Arguments dict to validate

        Returns:
            Tuple of (is_valid, error_message).
            If tool not found, returns (False, "Tool not found: {name}").
            If valid, returns (True, None).
            If invalid, returns (False, validation error message).
        """
        tool = _tool_registry.get(tool_name)
        if tool is None:
            return False, f"Tool not found: {tool_name}"

        return validate_arguments(tool.parameters, arguments)

    @classmethod
    def clear(cls) -> None:
        """
        Clear all registered tools.

        WARNING: Only use in tests! This removes all tool registrations.
        """
        _tool_registry.clear()
