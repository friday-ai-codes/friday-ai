"""RemoteToolRegistry for querying and serializing active tools."""
from typing import Any
from tools.models import RemoteTool
class RemoteToolRegistry:
 """Query interface for the RemoteTool table."""
 @staticmethod
 def get_active_tools -> list[RemoteTool]:
 return list(RemoteTool.objects.filter(is_active=True))
 @staticmethod
 def get_tools_payload -> list[dict[str, Any]]:
 """Serialize active tools to Anthropic-compatible tool schema list."""
 return [
 {"name": t.name, "description": t.description, "input_schema": t.input_schema}
 for t in RemoteTool.objects.filter(is_active=True)
 ]
 @staticmethod
 async def aget_tools_payload -> list[dict[str, Any]]:
 """Serialize active tools to Anthropic-compatible tool schema list (async)."""
 return [
 {"name": t.name, "description": t.description, "input_schema": t.input_schema}
 async for t in RemoteTool.objects.filter(is_active=True)
 ]
 @staticmethod
 def get_tool(name: str) -> RemoteTool | None:
 return RemoteTool.objects.filter(name=name, is_active=True).first
