"""RemoteTool model for server-side tool registry.

Supports three sources: builtin (direct function call), mcp (MCP Server),
and skill (sequential multi-step execution).
"""

from typing import Any

from django.db import models


class RemoteTool(models.Model):
    """A tool that can be invoked remotely by containers via the Runner."""

    class Source(models.TextChoices):
        BUILTIN = "builtin", "内置"
        MCP = "mcp", "MCP Server"
        SKILL = "skill", "Skill"

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField()
    source = models.CharField(max_length=20, choices=Source.choices)
    input_schema: models.JSONField[dict[str, Any], dict[str, Any]] = models.JSONField()
    timeout = models.IntegerField(default=30)
    is_active = models.BooleanField(default=True)
    config: models.JSONField[dict[str, Any], dict[str, Any]] = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "remote_tools"

    def __str__(self) -> str:
        return f"{self.name} ({self.source})"
