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
    requirement = models.TextField()
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
    version = models.PositiveIntegerField()
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


class McpCodingExecutionTrace(models.Model):
    """Execution trace for an external MCP coding plan run."""

    class Status(models.TextChoices):
        QUEUED = "queued", "已排队"
        DISPATCHING = "dispatching", "分发中"
        RUNNING = "running", "执行中"
        COMPLETED = "completed", "已完成"
        PARTIAL = "partial", "部分完成"
        FAILED = "failed", "失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        "interactions.InteractionRun",
        on_delete=models.CASCADE,
        related_name="mcp_coding_execution_traces",
    )
    plan = models.ForeignKey(
        McpCodingPlan,
        on_delete=models.CASCADE,
        related_name="execution_traces",
    )
    plan_version = models.ForeignKey(
        McpCodingPlanVersion,
        on_delete=models.CASCADE,
        related_name="execution_traces",
    )
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="mcp_coding_execution_traces",
    )
    coding_session = models.ForeignKey(
        "chat.CodingSession",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    subagent_session = models.ForeignKey(
        "subagent.SubAgentSession",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    tool_call = models.ForeignKey(
        "interactions.ToolCallRecord",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    retry_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="retries",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
    )
    branch_name = models.CharField(max_length=255, blank=True, default="")
    target_branch = models.CharField(max_length=255, blank=True, default="")
    timeout_seconds = models.PositiveIntegerField(default=3600)
    retry_count = models.PositiveIntegerField(default=0)
    dispatch_payload = models.JSONField(default=dict, blank=True)
    runner_logs = models.JSONField(default=list, blank=True)
    file_changes = models.JSONField(default=list, blank=True)
    test_results = models.JSONField(default=list, blank=True)
    push_result = models.JSONField(default=dict, blank=True)
    last_diff = models.JSONField(default=dict, blank=True)
    branch_summary = models.JSONField(default=dict, blank=True)
    mr_result = models.JSONField(default=dict, blank=True)
    recovery_state = models.JSONField(default=dict, blank=True)
    commit_sha = models.CharField(max_length=64, blank=True, default="")
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mcp_coding_execution_traces"
        indexes = [
            models.Index(fields=["plan", "-created_at"]),
            models.Index(fields=["repository", "-created_at"]),
            models.Index(fields=["run"]),
            models.Index(fields=["status"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"McpCodingExecutionTrace({self.id}, {self.status})"


class McpWorkItemContext(models.Model):
    """Feishu work item context snapshot for external MCP workflows."""

    class Status(models.TextChoices):
        COMPLETED = "completed", "已完成"
        PARTIAL = "partial", "部分完成"
        ERROR = "error", "错误"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        "interactions.InteractionRun",
        on_delete=models.CASCADE,
        related_name="mcp_work_item_contexts",
    )
    space = models.ForeignKey(
        "projects.Space",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="mcp_work_item_contexts",
    )
    tool_call = models.ForeignKey(
        "interactions.ToolCallRecord",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    feishu_project_key = models.CharField(max_length=128, db_index=True)
    work_item_type = models.CharField(max_length=80, db_index=True)
    work_item_id = models.BigIntegerField(db_index=True)
    name = models.CharField(max_length=500, blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.COMPLETED,
        db_index=True,
    )
    work_item_status = models.CharField(max_length=120, blank=True, default="")
    description = models.TextField(blank=True, default="")
    owners = models.JSONField(default=list, blank=True)
    fields = models.JSONField(default=dict, blank=True)
    relations = models.JSONField(default=list, blank=True)
    documents = models.JSONField(default=list, blank=True)
    comments = models.JSONField(default=list, blank=True)
    context = models.JSONField(default=dict, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "mcp_work_item_contexts"
        indexes = [
            models.Index(fields=["feishu_project_key", "work_item_type", "work_item_id"]),
            models.Index(fields=["run"]),
            models.Index(fields=["status"]),
            models.Index(fields=["space", "-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return (
            f"McpWorkItemContext("
            f"{self.feishu_project_key}/{self.work_item_type}/{self.work_item_id})"
        )


class McpWorkItemTechnicalPlan(models.Model):
    """Technical plan generated from a Feishu work item context."""

    class Status(models.TextChoices):
        COMPLETED = "completed", "已完成"
        PARTIAL = "partial", "部分完成"
        FAILED = "failed", "失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        "interactions.InteractionRun",
        on_delete=models.CASCADE,
        related_name="mcp_work_item_technical_plans",
    )
    context = models.ForeignKey(
        McpWorkItemContext,
        on_delete=models.CASCADE,
        related_name="technical_plans",
    )
    space = models.ForeignKey(
        "projects.Space",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="mcp_work_item_technical_plans",
    )
    tool_call = models.ForeignKey(
        "interactions.ToolCallRecord",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    feishu_project_key = models.CharField(max_length=128, db_index=True)
    work_item_type = models.CharField(max_length=80, db_index=True)
    work_item_id = models.BigIntegerField(db_index=True)
    title = models.CharField(max_length=240)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.COMPLETED,
        db_index=True,
    )
    plan_body = models.JSONField(default=dict, blank=True)
    markdown = models.TextField(blank=True, default="")
    repository_tasks = models.JSONField(default=list, blank=True)
    evidence = models.JSONField(default=list, blank=True)
    similar_cases = models.JSONField(default=list, blank=True)
    feishu_document_id = models.CharField(max_length=128, blank=True, default="")
    feishu_document_url = models.CharField(max_length=500, blank=True, default="")
    comment_result = models.JSONField(default=dict, blank=True)
    retry_state = models.JSONField(default=dict, blank=True)
    error_stage = models.CharField(max_length=80, blank=True, default="")
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mcp_work_item_technical_plans"
        indexes = [
            models.Index(fields=["context", "-created_at"]),
            models.Index(fields=["feishu_project_key", "work_item_type", "work_item_id"]),
            models.Index(fields=["run"]),
            models.Index(fields=["status"]),
            models.Index(fields=["space", "-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"McpWorkItemTechnicalPlan({self.title}, {self.status})"


class McpWorkItemRepoTask(models.Model):
    """Per-repository execution task created from a work item technical plan."""

    class Status(models.TextChoices):
        PENDING = "pending", "待执行"
        PLANNED = "planned", "已生成编码方案"
        RUNNING = "running", "执行中"
        COMPLETED = "completed", "已完成"
        PARTIAL = "partial", "部分完成"
        FAILED = "failed", "失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        "interactions.InteractionRun",
        on_delete=models.CASCADE,
        related_name="mcp_work_item_repo_tasks",
    )
    technical_plan = models.ForeignKey(
        McpWorkItemTechnicalPlan,
        on_delete=models.CASCADE,
        related_name="repo_tasks",
    )
    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="mcp_work_item_repo_tasks",
    )
    coding_plan = models.ForeignKey(
        McpCodingPlan,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="work_item_repo_tasks",
    )
    plan_version = models.ForeignKey(
        McpCodingPlanVersion,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="work_item_repo_tasks",
    )
    execution_trace = models.ForeignKey(
        McpCodingExecutionTrace,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="work_item_repo_tasks",
    )
    tool_call = models.ForeignKey(
        "interactions.ToolCallRecord",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    order = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    branch_name = models.CharField(max_length=255, blank=True, default="")
    target_branch = models.CharField(max_length=255, blank=True, default="")
    task_body = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    recovery_state = models.JSONField(default=dict, blank=True)
    commit_sha = models.CharField(max_length=64, blank=True, default="")
    mr_url = models.CharField(max_length=500, blank=True, default="")
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mcp_work_item_repo_tasks"
        constraints = [
            models.UniqueConstraint(
                fields=["technical_plan", "order"],
                name="uniq_work_item_repo_task_order",
            ),
        ]
        indexes = [
            models.Index(fields=["technical_plan", "order"]),
            models.Index(fields=["repository", "-created_at"]),
            models.Index(fields=["run"]),
            models.Index(fields=["status"]),
        ]
        ordering = ["technical_plan", "order"]

    def __str__(self) -> str:
        return f"McpWorkItemRepoTask({self.repository_id}, {self.status})"


class McpLearningCase(models.Model):
    """Auditable reusable implementation/fix case for work item RAG."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # v0.17.0 Phase 101：自动提炼场景无 InteractionRun（run 恒为 None），FK 放松为可空；
    # 人工 create_learning_case 路径继续必传 run，级联语义不变。
    run = models.ForeignKey(
        "interactions.InteractionRun",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="mcp_learning_cases",
    )
    # v0.17.0 Phase 101：自动提炼幂等键（= SubAgentSession.session_id，LOOP-05 review
    # 沉淀用 "{session_id}:pr_review" 变体，故 max_length=80）。用 null 而非空串默认：
    # 人工 create_learning_case 路径不写此字段，多条 NULL 不参与 unique 冲突
    # （SQLite/Postgres 语义一致）。
    source_session_id = models.CharField(
        max_length=80, null=True, blank=True, unique=True, default=None
    )
    context = models.ForeignKey(
        McpWorkItemContext,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="learning_cases",
    )
    technical_plan = models.ForeignKey(
        McpWorkItemTechnicalPlan,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="learning_cases",
    )
    tool_call = models.ForeignKey(
        "interactions.ToolCallRecord",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    work_item_type = models.CharField(max_length=80, blank=True, default="", db_index=True)
    work_item_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    title = models.CharField(max_length=240)
    problem = models.TextField(blank=True, default="")
    root_cause = models.TextField(blank=True, default="")
    solution = models.TextField(blank=True, default="")
    outcome = models.CharField(max_length=80, blank=True, default="", db_index=True)
    repositories = models.JSONField(default=list, blank=True)
    files = models.JSONField(default=list, blank=True)
    symbols = models.JSONField(default=list, blank=True)
    branches = models.JSONField(default=list, blank=True)
    mr_urls = models.JSONField(default=list, blank=True)
    tests = models.JSONField(default=list, blank=True)
    source_links = models.JSONField(default=dict, blank=True)
    case_body = models.JSONField(default=dict, blank=True)
    embedding_text = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mcp_learning_cases"
        indexes = [
            models.Index(fields=["work_item_type", "-created_at"]),
            models.Index(fields=["outcome", "-created_at"]),
            models.Index(fields=["run"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"McpLearningCase({self.title}, {self.outcome})"
