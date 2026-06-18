"""容器回调 API 序列化器（Phase）+ ExecutionContext API 序列化器（Phase）。"""

from __future__ import annotations

from rest_framework import serializers

from services.protocols import CallbackType
from subagent.models import ActionLog, ExecutionContext, InteractionLog, SubAgentSession, TokenUsage


class CallbackSerializer(serializers.Serializer):
    """统一回调端点请求序列化器。

    验证容器发送的回调请求结构。
    """

    type = serializers.ChoiceField(
        choices=[
            CallbackType.COMPLETED,
            CallbackType.FAILED,
            CallbackType.QUESTION,
            CallbackType.HEARTBEAT,
            CallbackType.PROGRESS,
            CallbackType.ACTION_LOG,
            CallbackType.TOKEN_USAGE,
        ],
    )
    session_id = serializers.CharField(max_length=64)
    token = serializers.CharField(max_length=256)
    timestamp = serializers.DateTimeField(required=False)
    payload = serializers.DictField(default=dict)


class CompletedPayloadSerializer(serializers.Serializer):
    """type=completed 时的 payload 验证。"""

    result_type = serializers.ChoiceField(choices=["text", "git"])
    output = serializers.DictField(default=dict)
    duration_ms = serializers.IntegerField(required=False, default=0)
    # Git 产物字段（result_type=git 时必填）
    branch_name = serializers.CharField(required=False, default="", allow_blank=True)
    commit_sha = serializers.CharField(required=False, default="", allow_blank=True)
    modified_files = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    # 容器端可选附带 cross_repo_relevance；不附带视为 []，
    # Server 端 _handle_completed 内会主动回算（避免容器引入 Django ORM 访问）。
    cross_repo_relevance = serializers.ListField(
        required=False,
        default=list,
        child=serializers.DictField(),
    )
    # Claude Code SDK 会话恢复支撑（resume）：容器编码结束附带 SDK session_id 与
    # transcript（jsonl 文本）。server 落库到关联 CodingSession，供 7 天内 re-dispatch
    # resume 续跑。容器侧已按大小上限截断；二者均可选，缺失则该会话仅能语义重建。
    sdk_session_id = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=128
    )
    sdk_transcript = serializers.CharField(
        required=False, default="", allow_blank=True, trim_whitespace=False
    )


class FailedPayloadSerializer(serializers.Serializer):
    """type=failed 时的 payload 验证。"""

    error = serializers.CharField(default="", allow_blank=True)
    exit_code = serializers.IntegerField(required=False, default=1)
    logs = serializers.CharField(required=False, default="", allow_blank=True)


class QuestionPayloadSerializer(serializers.Serializer):
    """type=question 时的 payload 验证。"""

    question = serializers.CharField()
    options = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    context = serializers.CharField(required=False, default="", allow_blank=True)
    code_snippet = serializers.CharField(required=False, default="", allow_blank=True)  # Phase 新增
    default_option = serializers.CharField(required=False, default="", allow_blank=True)
    timeout_minutes = serializers.IntegerField(required=False, default=10)


class HeartbeatPayloadSerializer(serializers.Serializer):
    """type=heartbeat 时的 payload 验证。"""

    progress = serializers.FloatField(required=False, default=0.0)
    message = serializers.CharField(required=False, default="", allow_blank=True)


class ProgressPayloadSerializer(serializers.Serializer):
    """type=progress 时的 payload 验证。"""

    phase = serializers.CharField(required=False, default="", allow_blank=True)
    progress = serializers.FloatField(required=False, default=0.0)
    message = serializers.CharField(required=False, default="", allow_blank=True)
    # 编码任务中间产出（modified_files + recent_tool_calls）
    coding_progress = serializers.JSONField(required=False, default=None)
    # implementation G1: 容器通过 details 传递结构化载荷（suggested_commit_message 等）
    # 消费侧 parse_progress_payload 会对 details 做 isinstance(dict) 双重校验并按
    # scalar 字段透传（跳过保留字段 progress/coding_progress）。
    details = serializers.JSONField(required=False, default=dict)


class ActionLogPayloadSerializer(serializers.Serializer):
    """type=action_log 时的 payload 验证。"""

    action_type = serializers.ChoiceField(choices=ActionLog.ActionType.choices)
    tool_name = serializers.CharField(required=False, default="", allow_blank=True)
    input = serializers.DictField(default=dict)
    output = serializers.DictField(default=dict)
    timestamp = serializers.DateTimeField()
    duration_ms = serializers.IntegerField(required=False, default=0)
    thinking = serializers.CharField(required=False, default="", allow_blank=True)
    model = serializers.CharField(required=False, default="", allow_blank=True)
    sequence = serializers.IntegerField(default=0)


class TokenUsagePayloadSerializer(serializers.Serializer):
    """type=token_usage 时的 payload 验证。"""

    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()
    cache_read_tokens = serializers.IntegerField(required=False, default=0)
    cache_write_tokens = serializers.IntegerField(required=False, default=0)
    model = serializers.CharField()
    timestamp = serializers.DateTimeField()
    total_cost_usd = serializers.DecimalField(
        max_digits=10, decimal_places=6, required=False, default=0
    )


# =============================================================================
# ExecutionContext API 序列化器（Phase）
# =============================================================================


class ActionLogReadSerializer(serializers.ModelSerializer):
    """ActionLog 读取序列化器。"""

    tool_name = serializers.SerializerMethodField()

    class Meta:
        model = ActionLog
        fields = [
            "id",
            "action_type",
            "tool_name",
            "timestamp",
            "sequence",
            "duration_ms",
            "payload",
            "created_at",
        ]

    def get_tool_name(self, obj: ActionLog) -> str:
        return obj.payload.get("tool_name", "") if isinstance(obj.payload, dict) else ""


class TokenUsageReadSerializer(serializers.ModelSerializer):
    """TokenUsage 读取序列化器。"""

    class Meta:
        model = TokenUsage
        fields = [
            "id",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "total_cost_usd",
            "model",
            "source",
            "recorded_at",
        ]


class ExecutionContextListSerializer(serializers.ModelSerializer):
    """ExecutionContext 列表序列化器。"""

    session_id = serializers.CharField(source="session.session_id", read_only=True)
    session_status = serializers.CharField(source="session.status", read_only=True)
    task_type = serializers.CharField(source="session.task_type", read_only=True)
    failure_reason = serializers.CharField(source="session.failure_reason", read_only=True)
    action_log_count = serializers.SerializerMethodField()
    token_usage_count = serializers.SerializerMethodField()

    class Meta:
        model = ExecutionContext
        fields = [
            "id",
            "session_id",
            "session_status",
            "task_type",
            "failure_reason",
            "action_log_count",
            "token_usage_count",
            "created_at",
        ]

    def get_action_log_count(self, obj: ExecutionContext) -> int:
        return obj.session.action_logs.count()

    def get_token_usage_count(self, obj: ExecutionContext) -> int:
        return obj.session.token_usages.count()


class ExecutionContextWriteSerializer(serializers.ModelSerializer):
    """ExecutionContext 创建/更新序列化器。"""

    session = serializers.PrimaryKeyRelatedField(queryset=SubAgentSession.objects.all())

    class Meta:
        model = ExecutionContext
        fields = [
            "session",
            "environment_vars",
            "input_prompt",
            "container_logs",
            "docker_stats",
        ]


class ExecutionContextDetailSerializer(serializers.ModelSerializer):
    """ExecutionContext 详情序列化器（含关联 action_logs + token_usages）。"""

    session_id = serializers.CharField(source="session.session_id", read_only=True)
    session_status = serializers.CharField(source="session.status", read_only=True)
    task_type = serializers.CharField(source="session.task_type", read_only=True)
    failure_reason = serializers.CharField(source="session.failure_reason", read_only=True)
    action_logs = ActionLogReadSerializer(many=True, source="session.action_logs", read_only=True)
    token_usages = TokenUsageReadSerializer(many=True, source="session.token_usages", read_only=True)

    class Meta:
        model = ExecutionContext
        fields = [
            "id",
            "session_id",
            "session_status",
            "task_type",
            "failure_reason",
            "environment_vars",
            "input_prompt",
            "container_logs",
            "docker_stats",
            "action_logs",
            "token_usages",
            "created_at",
            "updated_at",
        ]


# =============================================================================
# InteractionLog API 序列化器
# =============================================================================


class InteractionLogSerializer(serializers.ModelSerializer):
    """InteractionLog 读取序列化器。"""

    session_id = serializers.CharField(source="session.session_id", read_only=True)

    class Meta:
        model = InteractionLog
        fields = [
            "id",
            "session_id",
            "question_id",
            "question_text",
            "question_context",
            "code_snippet",
            "options",
            "answer_text",
            "answer_source",
            "asked_at",
            "answered_at",
        ]


class InteractionAnswerSerializer(serializers.Serializer):
    """提交回答的请求序列化器。"""

    answer = serializers.CharField()
    answer_source = serializers.ChoiceField(
        choices=["button", "text"], default="text",
    )
