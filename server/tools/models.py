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


class ToolTokenBinding(models.Model):
    """用户令牌 ↔ skill/mcp 工具的持久绑定（Phase 11 容器注入依据，per MCPB-01）。

    每个用户对同一工具最多一条绑定（unique(user, remote_tool)），「重复绑定即更新」
    由 10-03 upsert 在应用层收敛。本表只引用 ``access_token`` FK，绝不复制明文 /
    token_hash（T-10-05）；令牌 / 工具 / 用户删除时三 FK 级联清理（T-10-06）。
    """

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="tool_token_bindings",
    )
    access_token = models.ForeignKey(
        "access_tokens.AccessToken",
        on_delete=models.CASCADE,
        related_name="tool_bindings",
    )
    remote_tool = models.ForeignKey(
        RemoteTool,
        on_delete=models.CASCADE,
        related_name="token_bindings",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tool_token_bindings"
        unique_together = (("user", "remote_tool"),)
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ToolTokenBinding(user={self.user_id}, tool={self.remote_tool_id})"
