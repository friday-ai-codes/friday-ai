"""Agent API views."""

from rest_framework.response import Response
from rest_framework.views import APIView

from agents.tools.registry import ToolRegistry


class ToolListView(APIView):
    """API endpoint to list all registered agent tools.

    Returns tool metadata for frontend tool selector configuration.
    """

    def get(self, request) -> Response:
        """Get all registered tools.

        Returns:
            JSON response with list of tools, each containing:
            - name: Tool identifier
            - description: Human-readable description
            - category: Tool category (PROJECT, KNOWLEDGE, FEISHU, etc.)
            - parameters_schema: JSON Schema for tool parameters
        """
        tools = ToolRegistry.get_all_tools()

        tool_list = [
            {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category.value,
                "parameters_schema": tool.parameters,
            }
            for tool in tools
        ]

        return Response({"tools": tool_list})
