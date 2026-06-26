"""Feishu URL configuration."""

from django.urls import path

import feishu.callbacks.approval_callback as _approval_callback  # noqa: F401

# Register card callback handlers (import triggers @register_card_callback)
import feishu.callbacks.board_split_callback as _board_split_callback  # noqa: F401
import feishu.callbacks.chat_question_callback as _chat_question_callback  # noqa: F401
import feishu.callbacks.coding_callback as _coding_callback  # noqa: F401
import feishu.callbacks.container_callback as _container_callback  # noqa: F401
import feishu.callbacks.plan_callback as _plan_callback  # noqa: F401
import feishu.callbacks.repo_association_callback as _repo_association_callback  # noqa: F401

from .views import (
    CardCallbackView,
    FeishuConfigTestView,
    FeishuConfigView,
    FeishuWebhookView,
    IMMessageWebhookView,
    RefreshWebhookTokenView,
    TriggerLogDeleteView,
    TriggerLogDetailView,
    TriggerLogListView,
    TriggerLogRawView,
    TriggerLogRetryView,
    UpdateWebhookTokenView,
)

urlpatterns = [
    # Webhook endpoint（旧版共享端点：按 payload 解析空间 + 事件类型匹配，向后兼容）
    path("webhook/", FeishuWebhookView.as_view(), name="feishu-webhook"),
    # 专属端点：每个飞书触发节点一个 token，命中即直达对应工作流（飞书侧自动化规则指向此 URL）
    path("webhook/<str:token>/", FeishuWebhookView.as_view(), name="feishu-webhook-scoped"),
    # Card callback (IM interactions)
    path("card/callback/", CardCallbackView.as_view(), name="card-callback"),
    # IM message webhook (user messages to bot)
    path("im/message/", IMMessageWebhookView.as_view(), name="im-message-webhook"),
    # Config management (per space)
    path("spaces/<uuid:space_id>/config/", FeishuConfigView.as_view(), name="feishu-config"),
    path(
        "spaces/<uuid:space_id>/config/test/",
        FeishuConfigTestView.as_view(),
        name="feishu-config-test",
    ),
    path(
        "spaces/<uuid:space_id>/refresh-token/",
        RefreshWebhookTokenView.as_view(),
        name="feishu-refresh-token",
    ),
    path(
        "spaces/<uuid:space_id>/token/",
        UpdateWebhookTokenView.as_view(),
        name="feishu-update-token",
    ),
    # Logs
    path("logs/", TriggerLogListView.as_view(), name="feishu-logs"),
    path("logs/<uuid:log_id>/", TriggerLogDetailView.as_view(), name="feishu-log-detail"),
    path("logs/<uuid:log_id>/raw/", TriggerLogRawView.as_view(), name="feishu-log-raw"),
    path("logs/<uuid:log_id>/delete/", TriggerLogDeleteView.as_view(), name="feishu-log-delete"),
    path("logs/<uuid:log_id>/retry/", TriggerLogRetryView.as_view(), name="feishu-log-retry"),
]
