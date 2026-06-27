"""URL configuration for chat app."""

from django.urls import path

from .views import (
    ChatCompletionsView,
    ChatImageUploadView,
    ChatImageView,
    ChatInterruptView,
    ChatStreamView,
    ClarificationAnswerView,
    ClarificationSkipView,
    CodingPlanDetailView,
    CodingPlanListView,
    CodingPlanSessionsBatchCreateView,
    CodingSessionConfirmView,
    CodingSessionDetailView,
    CodingSessionListView,
    CommitConfirmView,
    ConflictCheckView,
    ConversationDetailView,
    ConversationListView,
    ConversationMessageForkView,
    ConversationMessagesDeleteView,
    ConversationPreflightView,
    ConversationRuntimeView,
    DiffSummaryView,
    ExportCodingPlanToFeishuView,
    ExportToFeishuView,
    FeishuExportAvailabilityView,
    ModelsView,
    PlanClarificationAnswerView,
    PRConfirmView,
    RoutingTraceManualOverrideView,
    WebPushPublicKeyView,
    WebPushSubscriptionView,
    WebPushUnsubscribeView,
)

urlpatterns = [
    # 现有 Chat Protocol API
    path("models/", ModelsView.as_view(), name="chat-models"),
    path("completions/", ChatCompletionsView.as_view(), name="chat-completions"),
    path("images/", ChatImageUploadView.as_view(), name="chat-image-upload"),
    path("images/<str:file_name>/", ChatImageView.as_view(), name="chat-image"),
    # Conversation API (implementation)
    path("conversations/", ConversationListView.as_view(), name="conversation-list"),
    path(
        "conversations/<uuid:conversation_id>/",
        ConversationDetailView.as_view(),
        name="conversation-detail",
    ),
    path(
        "conversations/<uuid:conversation_id>/stream/",
        ChatStreamView.as_view(),
        name="conversation-stream",
    ),
    path(
        "conversations/<uuid:conversation_id>/runtime/",
        ConversationRuntimeView.as_view(),
        name="conversation-runtime",
    ),
    # implementation contract contract：对话凭证前置探测
    path(
        "conversations/<uuid:conversation_id>/preflight/",
        ConversationPreflightView.as_view(),
        name="conversation-preflight",
    ),
    # implementation contract contract：对话历史批量清理（硬删 before_id 之前消息）
    path(
        "conversations/<uuid:conversation_id>/messages/",
        ConversationMessagesDeleteView.as_view(),
        name="conversation-messages-delete",
    ),
    path(
        "conversations/<uuid:conversation_id>/messages/<uuid:message_id>/fork/",
        ConversationMessageForkView.as_view(),
        name="conversation-message-fork",
    ),
    path(
        "conversations/<uuid:conversation_id>/interrupt/",
        ChatInterruptView.as_view(),
        name="conversation-interrupt",
    ),
    path(
        "push/public-key/",
        WebPushPublicKeyView.as_view(),
        name="chat-push-public-key",
    ),
    path(
        "push/subscriptions/",
        WebPushSubscriptionView.as_view(),
        name="chat-push-subscriptions",
    ),
    path(
        "push/subscriptions/unsubscribe/",
        WebPushUnsubscribeView.as_view(),
        name="chat-push-unsubscribe",
    ),
    # 导出对话消息到飞书文档
    path(
        "conversations/<uuid:conversation_id>/export-to-feishu/",
        ExportToFeishuView.as_view(),
        name="conversation-export-to-feishu",
    ),
    # 飞书导出可用性探测（前端据此隐藏「导出到飞书」入口）
    path(
        "feishu-export-availability/",
        FeishuExportAvailabilityView.as_view(),
        name="chat-feishu-export-availability",
    ),
    # 编码会话
    path(
        "coding-sessions/",
        CodingSessionListView.as_view(),
        name="coding-session-list",
    ),
    path(
        "coding-sessions/<uuid:session_id>/",
        CodingSessionDetailView.as_view(),
        name="coding-session-detail",
    ),
    path(
        "coding-sessions/<uuid:session_id>/confirm/",
        CodingSessionConfirmView.as_view(),
        name="coding-session-confirm",
    ),
    path(
        "coding-sessions/<uuid:session_id>/commit-confirm/",
        CommitConfirmView.as_view(),
        name="coding-session-commit-confirm",
    ),
    path(
        "coding-sessions/<uuid:session_id>/pr-confirm/",
        PRConfirmView.as_view(),
        name="coding-session-pr-confirm",
    ),
    path(
        "coding-sessions/<uuid:session_id>/conflict-check/",
        ConflictCheckView.as_view(),
        name="coding-session-conflict-check",
    ),
    path(
        "coding-sessions/<uuid:session_id>/diff-summary/",
        DiffSummaryView.as_view(),
        name="coding-session-diff-summary",
    ),
    # CodingPlan 独立领域 REST 端点
    path(
        "coding-plans/",
        CodingPlanListView.as_view(),
        name="coding-plan-list",
    ),
    path(
        "coding-plans/<uuid:plan_id>/",
        CodingPlanDetailView.as_view(),
        name="coding-plan-detail",
    ),
    # CodingPlan 批量创建 CodingSession
    path(
        "coding-plans/<uuid:plan_id>/sessions/",
        CodingPlanSessionsBatchCreateView.as_view(),
        name="coding-plan-sessions-batch",
    ),
    # 导出 CodingPlan 到飞书文档
    path(
        "coding-plans/<uuid:coding_plan_id>/export-to-feishu/",
        ExportCodingPlanToFeishuView.as_view(),
        name="coding-plan-export-to-feishu",
    ),
    # 路由决策手动微调
    path(
        "routing-traces/<uuid:trace_id>/override/",
        RoutingTraceManualOverrideView.as_view(),
        name="routing-trace-manual-override",
    ),
    # 协商答复 endpoint
    path(
        "clarifications/<str:clarification_id>/answer/",
        ClarificationAnswerView.as_view(),
        name="chat-clarification-answer",
    ),
    # 协商跳过 endpoint（按 conversation 维度，兜底卡片漏发时仍可跳过）
    path(
        "conversations/<uuid:conversation_id>/clarification/skip/",
        ClarificationSkipView.as_view(),
        name="conversation-clarification-skip",
    ),
    # plan 编排澄清专属路由（CLARIFY-04/06，与上面 chat 单题澄清物理隔离）
    path(
        "conversations/<uuid:conversation_id>/plan-clarification/answer/",
        PlanClarificationAnswerView.as_view(),
        name="conversation-plan-clarification-answer",
    ),
]
