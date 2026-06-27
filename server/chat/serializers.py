"""Serializers for chat API."""

from rest_framework import serializers


class ChatMessageSerializer(serializers.Serializer):
    """Serializer for chat message."""

    role = serializers.ChoiceField(choices=["user", "assistant", "system"])
    content = serializers.CharField()


class ChatCompletionRequestSerializer(serializers.Serializer):
    """Serializer for chat completion request."""

    model = serializers.CharField(help_text="模型 ID")
    messages = ChatMessageSerializer(many=True, help_text="消息列表")
    source = serializers.ChoiceField(
        choices=["system", "project"],
        default="system",
        help_text="配置来源",
    )
    space_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="空间 ID（当 source=project 时必填）",
    )
    api_key = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="临时 API Key（用于测试未保存的配置）",
    )
    base_url = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="临时 Base URL（用于测试未保存的配置）",
    )
    max_tokens = serializers.IntegerField(
        default=4096,
        min_value=1,
        max_value=100000,
        help_text="最大 token 数",
    )

    def validate(self, attrs):
        """Validate the request."""
        if attrs.get("source") == "project" and not attrs.get("space_id"):
            # Check if temporary credentials are provided
            if not attrs.get("api_key"):
                raise serializers.ValidationError(
                    {"space_id": "使用空间配置时必须提供 space_id 或临时 api_key"}
                )
        return attrs


class ModelsRequestSerializer(serializers.Serializer):
    """Serializer for models list request."""

    source = serializers.ChoiceField(
        choices=["system", "project"],
        default="system",
        help_text="配置来源",
    )
    space_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="空间 ID（当 source=project 时必填）",
    )
    api_key = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="临时 API Key（用于测试未保存的配置）",
    )
    base_url = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="临时 Base URL（用于测试未保存的配置）",
    )

    def validate(self, attrs):
        """Validate the request."""
        if attrs.get("source") == "project" and not attrs.get("space_id"):
            if not attrs.get("api_key"):
                raise serializers.ValidationError(
                    {"space_id": "使用空间配置时必须提供 space_id 或临时 api_key"}
                )
        return attrs


class ModelSerializer(serializers.Serializer):
    """Serializer for model info."""

    id = serializers.CharField()
    name = serializers.CharField()
    created = serializers.IntegerField(allow_null=True)


class ModelsResponseSerializer(serializers.Serializer):
    """Serializer for models list response."""

    models = ModelSerializer(many=True)


class ChatCompletionResponseSerializer(serializers.Serializer):
    """Serializer for chat completion response."""

    content = serializers.CharField()
    model = serializers.CharField()
    usage = serializers.DictField(child=serializers.IntegerField(), allow_null=True)


# ============================================================================
# Conversation Serializers (implementation)
# ============================================================================


class CreateConversationSerializer(serializers.Serializer):
    """创建对话请求。"""

    # 可空：不传 / 传 null 表示创建不绑定空间的「通用对话」
    space_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="空间 ID（可选，为空时创建不绑定空间的通用对话）",
    )
    title = serializers.CharField(max_length=200, default="新对话", required=False)
    model = serializers.CharField(
        max_length=100,
        required=False,
        default="",
        allow_blank=True,
        help_text="LLM 模型 ID（可选，为空时使用系统默认）",
    )


class ConversationPatchSerializer(serializers.Serializer):
    """implementation contract contract：对话部分更新 Serializer。

    允许字段：
        - provider_credential_id（UUID，null 表示清空 pin）
        - model（LLM 模型 ID 字符串）
        - title（对话标题）
        - space_id（UUID，null 表示切回不绑定空间的通用对话）

    frozen 校验由 ConversationDetailView.patch 在 serializer 前完成（contract 双重防御）。
    space_id 不受 frozen 拦截（与 title 同等待遇），但 running 态由 view 拒绝。
    """

    provider_credential_id = serializers.UUIDField(required=False, allow_null=True)
    model = serializers.CharField(
        required=False, allow_blank=True, max_length=200,
    )
    title = serializers.CharField(required=False, max_length=500)
    space_id = serializers.UUIDField(required=False, allow_null=True)
    # WS-03：AI 对话的项目绑定可改归/解绑（null 解绑）。可读性校验在 view 层
    # 经 resolve_allowed_project_ids fail-closed 完成。
    bound_project_id = serializers.UUIDField(required=False, allow_null=True)
    # 归档开关：true 归档（从默认列表隐藏）/ false 取消归档。不受 frozen 限制。
    is_archived = serializers.BooleanField(required=False)

    def validate_provider_credential_id(self, value):
        """FK 存在性 + is_active 校验，防止指向已软删 / 已禁用凭证（security mitigation-02）。"""
        if value is None:
            return value
        # lazy import 避免 chat ↔ system 循环依赖
        from system.models import ProviderCredential

        try:
            ProviderCredential.objects.get(id=value, is_active=True)
        except ProviderCredential.DoesNotExist as exc:
            raise serializers.ValidationError(
                "Provider 凭证不存在或已禁用",
            ) from exc
        return value


class ConversationForkRequestSerializer(serializers.Serializer):
    """编辑历史 user message 前创建新分支 conversation 的请求体。"""

    content = serializers.CharField(required=True, trim_whitespace=True)

    def validate_content(self, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError("编辑后的内容不能为空")
        return stripped


class ConversationListSerializer(serializers.Serializer):
    """对话列表项。

    UAT 第 3 项 hotfix（follow-up）：暴露 status + provider_credential_id，
    让前端 ChatHeader 能从 list 响应直接读到 pin 状态（chat 路径下 default.vue 接线）。
    """

    id = serializers.UUIDField()
    space_id = serializers.UUIDField(allow_null=True)
    title = serializers.CharField()
    model = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField()
    provider_credential_id = serializers.SerializerMethodField()
    is_archived = serializers.BooleanField(required=False)
    # 列表徽标聚合标记（由 list_conversations annotate 注入；default=False 向后兼容）。
    has_sdd_spec = serializers.BooleanField(required=False, default=False)
    has_coding_plan = serializers.BooleanField(required=False, default=False)
    has_coding_session = serializers.BooleanField(required=False, default=False)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_provider_credential_id(self, obj) -> str | None:
        """读 FK 的 _id 列（避免 sync ORM 触发；list/detail 路径均 async-safe）。"""
        cred_id = getattr(obj, "provider_credential_id_id", None)
        return str(cred_id) if cred_id else None


class _OwnerBriefSerializer(serializers.Serializer):
    """会话 owner 简要信息（admin 列表跨用户展示用）。"""

    id = serializers.UUIDField()
    username = serializers.CharField()
    display_name = serializers.CharField(allow_blank=True)


class AdminConversationListSerializer(serializers.Serializer):
    """管理员只读后台的会话列表项（ADMVW-01）。

    在普通 ConversationListSerializer 字段基础上补充跨用户管理所需的
    ``owner``（嵌套 {id, username, display_name}）与 ``message_count``
    （来自 service 层 ``annotate(Count("messages"))``）。

    **独立类，不污染** 既有 ConversationListSerializer / DetailSerializer 契约。
    owner 用 SerializerMethodField 读 ``obj.created_by``（需 service 层
    select_related 预取，None 安全），避免 async 序列化触发惰性 FK。
    """

    id = serializers.UUIDField()
    space_id = serializers.UUIDField(allow_null=True)
    title = serializers.CharField()
    status = serializers.CharField()
    model = serializers.CharField(required=False, allow_blank=True)
    message_count = serializers.IntegerField(read_only=True)
    owner = serializers.SerializerMethodField()
    # 列表徽标聚合标记（由 admin_list_conversations annotate 注入；default=False 向后兼容）。
    has_sdd_spec = serializers.BooleanField(required=False, default=False)
    has_coding_plan = serializers.BooleanField(required=False, default=False)
    has_coding_session = serializers.BooleanField(required=False, default=False)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_owner(self, obj) -> dict | None:
        """读已预取的 created_by；None（历史/匿名/开放模式会话）安全返回 null。"""
        user = getattr(obj, "created_by", None)
        if user is None:
            return None
        return {
            "id": str(user.id),
            "username": user.username,
            "display_name": user.display_name or "",
        }


class ConversationMessageSerializer(serializers.Serializer):
    """对话消息。

    parts contract：``parts`` 字段透传 ``Message.parts`` JSONField，
    前端 hydrate 优先用 ``parts``；``parts == []`` 时合成（legacy 历史消息兼容层，
    legacy hydration contract）。``content`` / ``tool_calls`` 字段保留作向后兼容（飞书导出 /
    检索 fallback / openAI compat path 仍读），由 finalize 强同源派生。
    """

    id = serializers.UUIDField()
    role = serializers.CharField()
    content = serializers.CharField(allow_blank=True)
    tool_calls = serializers.JSONField(required=False, allow_null=True)
    tool_call_id = serializers.CharField(required=False, allow_blank=True)
    metadata = serializers.JSONField(required=False)
    parts = serializers.JSONField(required=False)
    created_at = serializers.DateTimeField()


class ResolvedProviderChainEntrySerializer(serializers.Serializer):
    """implementation contract contract：四层解析链单条目序列化（响应契约驱动前端 tooltip）。"""

    layer = serializers.CharField()  # "node" | "conversation" | "project" | "system"
    provider_type = serializers.CharField(allow_null=True)
    model = serializers.CharField(allow_null=True, allow_blank=True)
    credential_id = serializers.UUIDField(allow_null=True)
    active = serializers.BooleanField()


class ResolvedProviderSerializer(serializers.Serializer):
    """implementation contract contract：Conversation / Node 响应扩展 resolved_provider 对象。"""

    provider_type = serializers.CharField()
    model = serializers.CharField(allow_blank=True)
    source = serializers.CharField()  # winning layer
    chain = ResolvedProviderChainEntrySerializer(many=True)


class ConversationDetailSerializer(serializers.Serializer):
    """对话详情（含消息列表 + implementation resolved_provider）。

    UAT 第 3 项 hotfix（follow-up）：补齐 model + status + provider_credential_id，
    与 list 响应字段对齐；让前端切换对话后能从 detail 直接读到 pin 状态。
    """

    id = serializers.UUIDField()
    space_id = serializers.UUIDField(allow_null=True)
    title = serializers.CharField()
    model = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField()
    provider_credential_id = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    messages = ConversationMessageSerializer(many=True, required=False)
    # implementation contract contract：四层 Provider 解析 Inspector（null=全链路缺失，前端降级）
    resolved_provider = ResolvedProviderSerializer(required=False, allow_null=True)

    def get_provider_credential_id(self, obj) -> str | None:
        """读 FK 的 _id 列（避免 sync ORM 触发；list/detail 路径均 async-safe）。"""
        cred_id = getattr(obj, "provider_credential_id_id", None)
        return str(cred_id) if cred_id else None


class RuntimeLogSerializer(serializers.Serializer):
    """运行态日志。"""

    type = serializers.CharField()
    content = serializers.CharField(allow_blank=True)
    ts = serializers.IntegerField()


class TaskProgressSerializer(serializers.Serializer):
    """编排任务进度。"""

    completed = serializers.IntegerField()
    total = serializers.IntegerField()


class ConversationRuntimeDeepSessionSerializer(serializers.Serializer):
    """单个深度分析子会话的运行态快照（多子代理各自独立日志）。"""

    session_id = serializers.CharField()
    task_description = serializers.CharField(allow_blank=True, required=False)
    status = serializers.CharField(allow_blank=True, required=False)
    progress_message = serializers.CharField(allow_blank=True, required=False)
    progress_percent = serializers.FloatField(allow_null=True, required=False)
    logs = RuntimeLogSerializer(many=True, required=False)


class ConversationRuntimeCodingPlanSessionSerializer(serializers.Serializer):
    """CodingPlan.sessions[] 单条状态快照。"""

    session_id = serializers.UUIDField()
    repository_id = serializers.UUIDField()
    repository_name = serializers.CharField()
    branch_name = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    pr_url = serializers.CharField(allow_blank=True)
    commit_sha = serializers.CharField(allow_blank=True)
    error_message = serializers.CharField(allow_blank=True)


class ConversationRuntimeCodingPlanSerializer(serializers.Serializer):
    """对话内最近 CodingPlan + 每仓 session 状态。"""

    plan_id = serializers.UUIDField()
    title = serializers.CharField(allow_blank=True)
    sessions = ConversationRuntimeCodingPlanSessionSerializer(many=True)
    feishu_doc_token = serializers.CharField(
        allow_blank=True, required=False, default=""
    )
    feishu_doc_url = serializers.CharField(
        allow_blank=True, required=False, default=""
    )


class ConversationRuntimeSerializer(serializers.Serializer):
    """对话运行态。"""

    conversation_id = serializers.UUIDField()
    active = serializers.BooleanField()
    mode = serializers.CharField(allow_null=True, required=False)
    status = serializers.CharField(allow_null=True, required=False)
    orchestration_run_id = serializers.CharField(allow_blank=True, required=False)
    phase = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    task_progress = TaskProgressSerializer(allow_null=True, required=False)
    session_id = serializers.CharField(allow_blank=True, required=False)
    task_description = serializers.CharField(allow_blank=True, required=False)
    progress_message = serializers.CharField(allow_blank=True, required=False)
    progress_percent = serializers.FloatField(allow_null=True, required=False)
    logs = RuntimeLogSerializer(many=True, required=False)
    # 多个深度分析子会话各自独立的日志（前端按会话渲染横向 swiper）
    deep_sessions = ConversationRuntimeDeepSessionSerializer(many=True, required=False)
    # 最近 CodingPlan + 每仓 session 状态
    coding_plan = ConversationRuntimeCodingPlanSerializer(
        allow_null=True, required=False
    )
    # 流式快照（仅 active=true 时返回）—— 详见 orchestration.graph._StreamingSnapshot
    # 与前端 store streamingPendingText / streamingThinking / streamingToolCalls /
    # streamingNarrations / streamingTimeline 一一对应；用 JSONField pass-through
    # 而不展开嵌套 serializer，避免后续 timeline kind / batch_id 等字段扩展破坏契约。
    streaming_snapshot = serializers.JSONField(allow_null=True, required=False)
    # 待回复的澄清（刷新 / 切回会话时恢复 ClarificationCard）；JSONField pass-through
    # 与前端 ClarificationPayload 对齐（clarification_id/question/options/allow_freeform）。
    pending_clarification = serializers.JSONField(allow_null=True, required=False)
    # plan 编排结构化澄清轮（CLARIFY-04，与 chat 单题 pending_clarification 物理隔离）：
    # {clarification_id, round_no, questions:[{question_id, question, qtype, options,
    # recommended, selected, freeform_text}]}，供前端 91-05 渲染多题澄清卡。
    pending_plan_clarification = serializers.JSONField(allow_null=True, required=False)


class WebPushPublicKeySerializer(serializers.Serializer):
    """Web Push 公钥响应。"""

    public_key = serializers.CharField()
    subject = serializers.CharField()


class WebPushSubscriptionKeysSerializer(serializers.Serializer):
    """Push 订阅密钥。"""

    p256dh = serializers.CharField()
    auth = serializers.CharField()


class WebPushSubscriptionSerializer(serializers.Serializer):
    """Push 订阅请求。"""

    endpoint = serializers.CharField()
    keys = WebPushSubscriptionKeysSerializer()
    user_agent = serializers.CharField(required=False, allow_blank=True)


class WebPushUnsubscribeSerializer(serializers.Serializer):
    """Push 取消订阅请求。"""

    endpoint = serializers.CharField()


class SendMessageSerializer(serializers.Serializer):
    """发送消息请求。"""

    content = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="消息内容",
    )
    input_parts = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        help_text="可选多模态输入 parts（text/image）",
    )
    role = serializers.ChoiceField(
        choices=["developer", "pm", "designer", "qa", "general"],
        default="developer",
        required=False,
        help_text="用户角色（影响 AI 回答风格）",
    )
    force_deep_analysis = serializers.BooleanField(
        default=False,
        required=False,
        help_text="强制使用深度分析模式（跳过 RAG，直接调用 Runner + Claude Code）",
    )
    feishu_doc_id = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="前端从消息中提取的飞书文档 ID",
    )
    branch = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="检索默认分支（RAG/工具未显式指定 branch 时使用）",
    )

    def validate(self, attrs):
        """允许 image-only 消息，但拒绝真正空消息。"""
        content = str(attrs.get("content", "") or "")
        input_parts = attrs.get("input_parts") or []
        has_text = bool(content.strip()) or any(
            isinstance(part, dict)
            and part.get("type") == "text"
            and str(part.get("text", "")).strip()
            for part in input_parts
        )
        has_image = any(
            isinstance(part, dict) and part.get("type") == "image"
            for part in input_parts
        )
        if not has_text and not has_image:
            raise serializers.ValidationError({"content": "消息内容不能为空"})
        return attrs


# ============================================================================
# CodingPlan Serializers (implementation)
# ============================================================================


class CodingPlanSerializer(serializers.Serializer):
    """CodingPlan 详情序列化器（implementation）。

    所有字段 read-only：写路径走 LLM tool（create_coding_plan / update_coding_plan），
    不通过 REST 直写。
    """

    id = serializers.UUIDField(read_only=True)
    conversation_id = serializers.UUIDField(read_only=True)
    title = serializers.CharField(read_only=True, allow_blank=True)
    tech_plan = serializers.CharField(read_only=True)
    affected_files = serializers.JSONField(read_only=True)
    feishu_doc_token = serializers.CharField(read_only=True, allow_blank=True)
    feishu_doc_url = serializers.CharField(read_only=True, allow_blank=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


# ============================================================================
# CodingSession Serializers (implementation)
# ============================================================================


class CodingSessionSerializer(serializers.Serializer):
    """CodingSession 详情序列化器。"""

    id = serializers.UUIDField(read_only=True)
    # 新增反向 FK 暴露（null 表示历史 session 尚未迁移到 CodingPlan）
    coding_plan_id = serializers.UUIDField(read_only=True, allow_null=True)
    status = serializers.CharField(read_only=True)
    tech_plan = serializers.CharField(read_only=True)
    affected_files = serializers.JSONField(read_only=True)
    revision_count = serializers.IntegerField(read_only=True)
    repository_id = serializers.UUIDField(read_only=True)
    branch_name = serializers.CharField(read_only=True)
    target_branch = serializers.CharField(read_only=True, allow_blank=True)
    pr_url = serializers.URLField(read_only=True, allow_blank=True)
    error_message = serializers.CharField(read_only=True, allow_blank=True)
    confirmation_step = serializers.CharField(read_only=True, allow_blank=True)
    suggested_commit_message = serializers.CharField(read_only=True, allow_blank=True)
    suggested_pr_title = serializers.CharField(read_only=True, allow_blank=True)
    suggested_pr_description = serializers.CharField(read_only=True, allow_blank=True)
    conflict_check_result = serializers.JSONField(read_only=True)
    diff_summary = serializers.JSONField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


# ============================================================================
# 批量创建 CodingSession
# ============================================================================


class CodingSessionsBatchCreateRequestSerializer(serializers.Serializer):
    """POST /api/chat/coding-plans/{id}/sessions/ 请求体。"""

    repository_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=20,
        help_text="目标仓库 UUID 列表（1-20 个）",
    )
    branch_template = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=200,
        help_text=(
            "可选分支模板。支持占位符 ${repo} → repository.name。"
            "为空时按 CodingPlan title 推断。"
        ),
    )
    target_branch = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=255,
        help_text="PR 目标分支，统一应用到本次 fan-out 的所有仓库；为空时回退默认 develop。",
    )


class _SessionCreatedItemSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    repository_id = serializers.UUIDField()
    branch_name = serializers.CharField()


class _SessionFailedItemSerializer(serializers.Serializer):
    repository_id = serializers.UUIDField()
    error = serializers.CharField()


class CodingSessionsBatchCreateResponseSerializer(serializers.Serializer):
    """POST /api/chat/coding-plans/{id}/sessions/ 响应体。"""

    created = _SessionCreatedItemSerializer(many=True)
    failed = _SessionFailedItemSerializer(many=True)


class ExportToFeishuSerializer(serializers.Serializer):
    """导出对话消息到飞书文档。"""

    message_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        help_text="要导出的消息 ID 列表",
    )
    title = serializers.CharField(
        max_length=200,
        help_text="飞书文档标题",
    )
    folder_token = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="目标文件夹 token（可选，覆盖项目配置）",
    )


class ExportCodingPlanToFeishuSerializer(serializers.Serializer):
    """导出 CodingPlan 到飞书文档（implementation / work item）。

    与 ``ExportToFeishuSerializer`` 区别：标题与 folder_token 全部可选，
    缺省时由 view 层回退到 ``coding_plan.title`` / ``project.feishu_doc_folder_token``。
    """

    folder_token = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=200,
        help_text="目标飞书文件夹 token（可选，覆盖项目配置）",
    )
    title = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=200,
        help_text="飞书文档标题（可选，默认使用 CodingPlan.title）",
    )


# ============================================================================
# 路由决策手动微调（manual_override）
# ============================================================================


class RoutingTraceManualOverrideCandidateSerializer(serializers.Serializer):
    """单条 candidate 的 manual override payload（限制仅 selected 可改）。"""

    repository_id = serializers.UUIDField()
    selected = serializers.BooleanField()


class RoutingTraceManualOverrideSerializer(serializers.Serializer):
    """POST /api/chat/routing-traces/<uuid>/override/ 请求体。

    限制 frontend 只能改 selected 字段；score / level /
    evidence / selected_by_ai 由 Server 端继承原 trace，前端无权改写。
    """

    candidates = serializers.ListField(
        child=RoutingTraceManualOverrideCandidateSerializer(),
        min_length=1,
        help_text="每条只需 {repository_id, selected}；其它字段被忽略",
    )


# ============================================================================
# implementation / 协商答复 endpoint
# ============================================================================


class ClarificationAnswerSerializer(serializers.Serializer):
    """``POST /api/chat/clarifications/<id>/answer/`` 请求体。

    用户必须至少提供 ``selected_option_id`` 或 ``freeform_text`` 之一。
    `selected_option_id` 必须能在 trace.options 里找到（视图层校验）。
    """

    selected_option_id = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        default="",
        help_text="用户选中的 ClarificationOption.id；可空仅用 freeform 时传 \"\"",
    )
    freeform_text = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
        default="",
        help_text="用户自由输入兜底；可空仅用 selected_option_id 时传 \"\"",
    )

    def validate(self, attrs: dict) -> dict:
        selected = (attrs.get("selected_option_id") or "").strip()
        freeform = (attrs.get("freeform_text") or "").strip()
        if not selected and not freeform:
            raise serializers.ValidationError(
                "必须至少提供 selected_option_id 或 freeform_text 之一"
            )
        return attrs


class PlanClarificationAnswerSerializer(serializers.Serializer):
    """``POST /api/chat/conversations/<id>/plan-clarification/answer/`` 请求体。

    收 plan 编排结构化澄清轮的多题答复（与 chat 单题 ``ClarificationAnswerSerializer``
    物理隔离）。每条形态 ``{question_id, selected, freeform_text?}``：

    - ``question_id``：必填字符串（视图层做归属校验——必属该 session pending 轮）。
    - ``selected``：``str``（single）或 ``list[str]``（multi）；纯 freeform 时可空。
    - ``freeform_text``：可选自由文本补充。

    serializer 只做**结构**校验（非空列表 + 每条含 ``question_id``）；归属/越界校验留
    视图层（acount 比对该 session pending 轮的子题集合）。
    """

    answers = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=False,
        help_text="结构化答复列表，每条 {question_id, selected, freeform_text?}",
    )

    def validate_answers(self, value: list[dict]) -> list[dict]:
        for ans in value:
            qid = str(ans.get("question_id") or "").strip()
            if not qid:
                raise serializers.ValidationError("每条 answer 必须含非空 question_id")
        return value
