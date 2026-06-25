"""
Django models for Agent state persistence.

AgentSession: Stores the full state of an agent execution session
ToolCallLog: Records audit trail of tool executions within a session
"""

from django.db import models

from accounts.models import User
from projects.models import Space


class AgentSession(models.Model):
    """
    Stores the full state of an agent execution session.

    Supports suspension and resumption for human-in-the-loop workflows.
    """

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUSPENDED = "suspended", "Suspended"
        COMPLETED = "completed", "Completed"
        ERROR = "error", "Error"
        MAX_ITERATIONS = "max_iterations", "Max Iterations Reached"

    class SuspensionReason(models.TextChoices):
        NONE = "", "None"
        USER_QUESTION = "user_question", "Waiting for user response"
        HUMAN_APPROVAL = "human_approval", "Waiting for human approval"
        EXTERNAL_ACTION = "external_action", "Waiting for external action"

    # Identification
    session_id = models.CharField(max_length=64, unique=True, db_index=True)

    # Relationships
    space = models.ForeignKey(
        Space,
        on_delete=models.CASCADE,
        related_name="agent_sessions",
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="agent_sessions",
        null=True,
        blank=True,
    )

    # Optional link to Feishu work item
    work_item_id = models.CharField(max_length=64, blank=True, default="")

    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RUNNING,
        db_index=True,
    )

    # Conversation history (list of message dicts)
    messages = models.JSONField(default=list)

    # Suspension state
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspension_reason = models.CharField(
        max_length=50,
        choices=SuspensionReason.choices,
        default=SuspensionReason.NONE,
        blank=True,
    )
    pending_tool_call = models.JSONField(null=True, blank=True)

    # Output
    output = models.JSONField(default=list)  # List of outputs produced
    final_answer = models.TextField(blank=True, default="")

    # Metadata (iteration count, tool_calls count, usage stats)
    metadata = models.JSONField(default=dict)

    # Temporary data for tool-specific state (cleared on completion)
    temp_data = models.JSONField(default=dict, blank=True)
    """
    Tool-specific temporary data that needs to persist across suspension.
    Examples: intermediate computation results, cached API responses,
    tool state that cannot be derived from messages alone.
    Cleared when session completes or errors.
    """

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["space", "status"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"AgentSession({self.session_id}, {self.status})"

    def increment_iteration(self) -> int:
        """Increment and return the current iteration count."""
        iteration = self.metadata.get("iteration_count", 0) + 1
        self.metadata["iteration_count"] = iteration
        return iteration

    def add_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Add token usage to cumulative stats."""
        usage = self.metadata.setdefault("usage", {"input_tokens": 0, "output_tokens": 0})
        usage["input_tokens"] += input_tokens
        usage["output_tokens"] += output_tokens

    def increment_tool_calls(self) -> int:
        """Increment and return the tool calls count."""
        count = self.metadata.get("tool_calls_count", 0) + 1
        self.metadata["tool_calls_count"] = count
        return count


class ToolCallLog(models.Model):
    """
    Records audit trail of tool executions within a session.

    Provides detailed logging for debugging, analysis, and compliance.
    """

    # Relationship to session
    session = models.ForeignKey(
        AgentSession,
        on_delete=models.CASCADE,
        related_name="tool_calls",
    )

    # Tool identification
    tool_name = models.CharField(max_length=64, db_index=True)
    tool_call_id = models.CharField(max_length=64)

    # Input
    arguments = models.JSONField(default=dict)

    # Result
    result_success = models.BooleanField(default=False)
    result_output = models.JSONField(null=True, blank=True)
    result_error = models.TextField(blank=True, default="")

    # Timing
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField()
    duration_ms = models.IntegerField(default=0)

    # Context
    iteration = models.IntegerField(default=0)

    class Meta:
        ordering = ["started_at"]
        indexes = [
            models.Index(fields=["session", "iteration"]),
            models.Index(fields=["tool_name", "-started_at"]),
        ]

    def __str__(self) -> str:
        status = "OK" if self.result_success else "FAILED"
        return f"ToolCall({self.tool_name}, {status}, {self.duration_ms}ms)"
