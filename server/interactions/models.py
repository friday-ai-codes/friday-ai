"""Interaction Ledger 审计账本模型 —— 四张 append-only 表。

覆盖外部 MCP/Skill 入口的全量交互留痕（contract 全量事件级入库）：

- ``InteractionRun``：顶层运行实例，对外 trace 锚点（contract）。
- ``InteractionEvent``：事件流，8 类 event_type + 父子 trace（contract）。
- ``ToolCallRecord``：tool call 明细（contract）。
- ``ModelUsageRecord``：model usage 明细（contract）。

**append-only 约束（contract）**：四表只增不改，重试记录为新事件 / 新记录，
不覆盖历史；模型层不提供更新语义。

**脱敏契约（contract）**：``token_fingerprint`` 仅存 hash_token（sha256 hex），
绝不存明文；``raw_request`` / ``payload`` / tool ``input``·``output`` / model prompt
在写库前必须已经过 ``redact_for_ledger``（由 checkpoint 的写入 helper 保证）。

**零侵入软关联（Pitfall 6）**：对现有 ``AgentSession`` / ``OrchestrationRun`` /
父事件均用 ``on_delete=SET_NULL`` + ``related_name="+"``，删除上游不连带删审计记录、
也不在现有表上反向挂关系。
"""

import uuid

from django.db import models


class InteractionRun(models.Model):
    """顶层交互运行实例 —— 对外 trace 锚点（contract）。

    每次外部 MCP/Skill 请求同步创建一条（保证可追踪）。append-only：
    状态推进通过新增子事件表达，run 自身仅在收尾时补 ``completed_at`` /
    终态 ``status``，不重写历史语义。
    """

    class Status(models.TextChoices):
        RUNNING = "running", "运行中"
        COMPLETED = "completed", "已完成"
        ERROR = "error", "错误"
        # DENIED：token 吊销/过期/无效时记录的拒绝运行（供 contract）。
        DENIED = "denied", "已拒绝"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # 对外暴露的 trace id（contract），与内部 pk 解耦。
    run_id = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    # = hash_token(token)（sha256 hex，64 字符）；绝不存明文（contract）。
    token_fingerprint = models.CharField(
        max_length=64, db_index=True, blank=True, default=""
    )
    # 请求来源标识（如 mcp / skill / cli）。
    source = models.CharField(max_length=50, db_index=True)
    # 外部请求关联 id（便于跨系统对账）。
    request_id = models.CharField(
        max_length=128, blank=True, default="", db_index=True
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RUNNING,
        db_index=True,
    )
    # 原始请求快照（写入前已 redacted，由 checkpoint helper 保证）。
    raw_request = models.JSONField(default=dict, blank=True)
    # 软关联现有内部 session，零侵入（SET_NULL + "+"，不反向挂关系）。
    agent_session = models.ForeignKey(
        "agents.AgentSession",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    orchestration_run = models.ForeignKey(
        "orchestration.OrchestrationRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "interaction_runs"
        indexes = [
            models.Index(fields=["token_fingerprint", "-created_at"]),
            models.Index(fields=["status"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"InteractionRun({self.run_id}, {self.status})"


class InteractionEvent(models.Model):
    """交互事件流 —— 8 类 event_type + 父子 trace（contract）。

    append-only：每个用户输入 / agent 决策 / tool 调用等都是一条独立事件，
    重试为新事件（不覆盖）。``seq`` 由写入 helper 在应用层分配，按 (run, seq)
    线性排序还原完整 trace。
    """

    class EventType(models.TextChoices):
        USER_INPUT = "user_input", "用户输入"
        SKILL_STEP = "skill_step", "Skill 步骤"
        AGENT_DECISION = "agent_decision", "Agent 决策"
        CLARIFICATION = "clarification", "澄清"
        TOOL_CALL = "tool_call", "工具调用"
        TOOL_RESULT = "tool_result", "工具结果"
        ERROR = "error", "错误"
        RETRY = "retry", "重试"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        InteractionRun, on_delete=models.CASCADE, related_name="events"
    )
    # 自关联父事件表达父子 trace；上游删除不连带删子事件（SET_NULL）。
    parent_event = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    # 同一 run 内的事件序号，由 helper 应用层分配（首版串行假设）。
    seq = models.PositiveIntegerField()
    event_type = models.CharField(
        max_length=30, choices=EventType.choices, db_index=True
    )
    # 事件负载（写入前必须已 redact_for_ledger，contract/05）。
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "interaction_events"
        indexes = [
            models.Index(fields=["run", "seq"]),
        ]
        ordering = ["run", "seq"]

    def __str__(self) -> str:
        return f"InteractionEvent({self.run_id}, {self.seq}, {self.event_type})"


class ToolCallRecord(models.Model):
    """工具调用明细记录（contract）。

    append-only：每次 tool 调用（含重试，``retry_index`` 区分）记录一条，
    不覆盖。``input`` / ``output`` 写库前已 redacted。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        InteractionRun, on_delete=models.CASCADE, related_name="tool_calls"
    )
    # 关联触发该调用的事件；上游删除不连带删记录（SET_NULL + "+"）。
    parent_event = models.ForeignKey(
        InteractionEvent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    tool_name = models.CharField(max_length=128, db_index=True)
    # tool 入参 / 出参（写库前已 redacted）。
    input = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=30)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    # 重试序号：同一逻辑调用的第 N 次尝试（0 为首次），重试不覆盖前次。
    retry_index = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tool_call_records"
        indexes = [
            models.Index(fields=["run", "-created_at"]),
            models.Index(fields=["tool_name"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ToolCallRecord({self.run_id}, {self.tool_name}, {self.status})"


class RetrievalTrace(models.Model):
    """检索证据留痕（work item）。

    append-only：每条 routing 候选、RAG chunk、GraphRAG edge、文件读取证据
    独立落一行，便于按 InteractionRun 回放外部 MCP read tool 的检索过程。
    payload 写入前由 ledger helper 统一脱敏。
    """

    class Kind(models.TextChoices):
        ROUTING = "routing", "仓库路由"
        CHUNK = "chunk", "RAG chunk 命中"
        EDGE = "edge", "GraphRAG 邻居边"
        FILE = "file", "文件读取"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # run 改 nullable（per 72-02）：chat / workflow 召回无 InteractionRun 也可独立成行，
    # 上游 run 删除不连带删留痕（SET_NULL）。MCP 路径仍可传 run，向后兼容。
    run = models.ForeignKey(
        InteractionRun,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="retrieval_traces",
    )
    tool_call = models.ForeignKey(
        ToolCallRecord,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    seq = models.PositiveIntegerField()
    kind = models.CharField(max_length=20, choices=Kind.choices, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    # 绑定触发用户与会话/入口（per 观测规范；query 原文/chunk 内容/score 仍走 payload
    # 经 redact_for_ledger，由 72-04 写入逻辑负责）。
    user_id = models.CharField(max_length=64, blank=True, default="system", db_index=True)
    conversation_id = models.CharField(
        max_length=64, blank=True, default="", db_index=True
    )
    source = models.CharField(max_length=32, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "retrieval_traces"
        indexes = [
            models.Index(fields=["run", "seq"]),
            models.Index(fields=["kind"]),
        ]
        ordering = ["run", "seq"]

    def __str__(self) -> str:
        return f"RetrievalTrace({self.run_id}, {self.seq}, {self.kind})"


class ModelUsageRecord(models.Model):
    """模型用量明细记录（contract）。

    append-only：每次模型调用（含失败，``failure_type`` 标注）记录一条 token
    用量与成本估算，便于后续费用归因 / 质量分析（首版仅留痕，不做扣费）。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # run 改 nullable（per RATE-02）：非 MCP 的 LLM 调用（chat / workflow / 容器）
    # 也能独立成行，纳入 TPS 统计；上游 run 删除不连带删用量（SET_NULL）。MCP 路径
    # 仍可传 run，向后兼容零回归。
    run = models.ForeignKey(
        InteractionRun,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="model_usages",
    )
    parent_event = models.ForeignKey(
        InteractionEvent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    # LLM 调用来源（受控枚举，22 类见 LOGGING-SPEC §4.1）；TPS/TTFT/上游码按此区分维度。
    call_source = models.CharField(max_length=40, blank=True, default="", db_index=True)
    provider = models.CharField(max_length=64)
    model = models.CharField(max_length=128)
    # prompt 版本（业务 prompt）与 system prompt 版本，便于回溯对齐。
    prompt_version = models.CharField(max_length=64, blank=True, default="")
    system_prompt_version = models.CharField(
        max_length=64, blank=True, default=""
    )
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    # 成本估算（货币单位，DecimalField 保精度）；缺省未知时为 null。
    cost_estimate = models.DecimalField(
        max_digits=12, decimal_places=6, null=True, blank=True
    )
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    # 流式首 chunk 计时（per SLA-04）；非流式 / 未知为 null。
    ttft_ms = models.PositiveIntegerField(null=True, blank=True)
    # 上游 provider HTTP 状态码（per SLA-03，429/529 单列）；正常 / 未知为 null。
    upstream_status_code = models.PositiveIntegerField(null=True, blank=True)
    # 失败类型（成功为空字符串）；失败也留痕不覆盖（429/529/其它上游码标签）。
    failure_type = models.CharField(max_length=64, blank=True, default="")
    # 绑定触发用户与入口（per 观测规范）；无触发用户记 system。
    user_id = models.CharField(max_length=64, blank=True, default="system", db_index=True)
    source = models.CharField(max_length=32, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "model_usage_records"
        indexes = [
            models.Index(fields=["run", "-created_at"]),
            models.Index(fields=["provider", "model"]),
            # Phase 73 TPS / 上游码聚合（call_source 维度 + 上游错误码筛选）。
            models.Index(fields=["call_source", "-created_at"]),
            models.Index(fields=["upstream_status_code"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ModelUsageRecord({self.run_id}, {self.provider}/{self.model})"
