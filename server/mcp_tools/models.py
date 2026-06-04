"""Persistent artifacts produced by external MCP planning tools."""
from __future__ import annotations
import uuid
from django.db import models
class McpRepositoryAnalysis(models.Model):
 """Repository analysis artifact linked to one MCP InteractionRun."""
 class Status(models.TextChoices):
 COMPLETED = "completed", "已完成"
 ERROR = "error", "错误"
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 run = models.ForeignKey(
 "interactions.InteractionRun",
 on_delete=models.CASCADE,
 related_name="mcp_repository_analyses",
 )
 repository = models.ForeignKey(
 "repositories.Repository",
 on_delete=models.CASCADE,
 related_name="mcp_repository_analyses",
 )
 tool_call = models.ForeignKey(
 "interactions.ToolCallRecord",
 null=True,
 blank=True,
 on_delete=models.SET_NULL,
 related_name="+",
 )
 branch = models.CharField(max_length=200, blank=True, default="")
 focus = models.TextField(blank=True, default="")
 status = models.CharField(
 max_length=20,
 choices=Status.choices,
 default=Status.COMPLETED,
 db_index=True,
 )
 summary = models.JSONField(default=dict, blank=True)
 evidence = models.JSONField(default=list, blank=True)
 created_at = models.DateTimeField(auto_now_add=True)
 class Meta:
 db_table = "mcp_repository_analyses"
 indexes = [
 models.Index(fields=["repository", "-created_at"]),
 models.Index(fields=["run"]),
 ]
 ordering = ["-created_at"]
 def __str__(self) -> str:
 return f"McpRepositoryAnalysis({self.repository_id}, {self.branch or 'base'})"
class McpCodingPlan(models.Model):
 """Stable external MCP coding plan identity."""
 class Status(models.TextChoices):
 DRAFT = "draft", "草稿"
 SUPERSEDED = "superseded", "已替换"
 EXECUTING = "executing", "执行中"
 COMPLETED = "completed", "已完成"
 FAILED = "failed", "失败"
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 run = models.ForeignKey(
 "interactions.InteractionRun",
 on_delete=models.CASCADE,
 related_name="mcp_coding_plans",
 )
 repository = models.ForeignKey(
 "repositories.Repository",
 on_delete=models.CASCADE,
 related_name="mcp_coding_plans",
 )
 analysis = models.ForeignKey(
 McpRepositoryAnalysis,
 null=True,
 blank=True,
 on_delete=models.SET_NULL,
 related_name="coding_plans",
 )
 branch = models.CharField(max_length=200, blank=True, default="")
 requirement = models.TextField
 title = models.CharField(max_length=240)
 current_version = models.PositiveIntegerField(default=1)
 status = models.CharField(
 max_length=20,
 choices=Status.choices,
 default=Status.DRAFT,
 db_index=True,
 )
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "mcp_coding_plans"
 indexes = [
 models.Index(fields=["repository", "-created_at"]),
 models.Index(fields=["run"]),
 models.Index(fields=["status"]),
 ]
 ordering = ["-created_at"]
 def __str__(self) -> str:
 return f"McpCodingPlan({self.title}, v{self.current_version})"
class McpCodingPlanVersion(models.Model):
 """Versioned MCP coding plan payload."""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 plan = models.ForeignKey(
 McpCodingPlan,
 on_delete=models.CASCADE,
 related_name="versions",
 )
 run = models.ForeignKey(
 "interactions.InteractionRun",
 on_delete=models.CASCADE,
 related_name="mcp_coding_plan_versions",
 )
 tool_call = models.ForeignKey(
 "interactions.ToolCallRecord",
 null=True,
 blank=True,
 on_delete=models.SET_NULL,
 related_name="+",
 )
 version = models.PositiveIntegerField
 plan_body = models.JSONField(default=dict, blank=True)
 affected_files = models.JSONField(default=list, blank=True)
 steps = models.JSONField(default=list, blank=True)
 test_plan = models.JSONField(default=list, blank=True)
 risks = models.JSONField(default=list, blank=True)
 evidence = models.JSONField(default=list, blank=True)
 change_summary = models.TextField(blank=True, default="")
 risk_delta = models.JSONField(default=dict, blank=True)
 created_at = models.DateTimeField(auto_now_add=True)
 class Meta:
 db_table = "mcp_coding_plan_versions"
 constraints = [
 models.UniqueConstraint(
 fields=["plan", "version"],
 name="uniq_mcp_plan_version",
 ),
 ]
 indexes = [
 models.Index(fields=["plan", "-version"]),
 models.Index(fields=["run"]),
 ]
 ordering = ["plan", "-version"]
 def __str__(self) -> str:
 return f"McpCodingPlanVersion({self.plan_id}, v{self.version})"
