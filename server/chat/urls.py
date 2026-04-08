"""URL configuration for chat app."""
from django.urls import path
from .views import (
 ChatCompletionsView,
 ChatInterruptView,
 ChatStreamView,
 CodingSessionConfirmView,
 CodingSessionDetailView,
 CodingSessionListView,
 ConversationDetailView,
 ConversationListView,
 ConversationRuntimeView,
 ExportToFeishuView,
 ModelsView,
 WebPushPublicKeyView,
 WebPushSubscriptionView,
 WebPushUnsubscribeView,
)
urlpatterns = [
 # 现有 Chat Protocol API
 path("models/", ModelsView.as_view, name="chat-models"),
 path("completions/", ChatCompletionsView.as_view, name="chat-completions"),
 # Conversation API (Phase)
 path("conversations/", ConversationListView.as_view, name="conversation-list"),
 path(
 "conversations/<uuid:conversation_id>/",
 ConversationDetailView.as_view,
 name="conversation-detail",
 ),
 path(
 "conversations/<uuid:conversation_id>/stream/",
 ChatStreamView.as_view,
 name="conversation-stream",
 ),
 path(
 "conversations/<uuid:conversation_id>/runtime/",
 ConversationRuntimeView.as_view,
 name="conversation-runtime",
 ),
 path(
 "conversations/<uuid:conversation_id>/interrupt/",
 ChatInterruptView.as_view,
 name="conversation-interrupt",
 ),
 path(
 "push/public-key/",
 WebPushPublicKeyView.as_view,
 name="chat-push-public-key",
 ),
 path(
 "push/subscriptions/",
 WebPushSubscriptionView.as_view,
 name="chat-push-subscriptions",
 ),
 path(
 "push/subscriptions/unsubscribe/",
 WebPushUnsubscribeView.as_view,
 name="chat-push-unsubscribe",
 ),
 # Phase: 导出对话消息到飞书文档
 path(
 "conversations/<uuid:conversation_id>/export-to-feishu/",
 ExportToFeishuView.as_view,
 name="conversation-export-to-feishu",
 ),
 # Phase: 编码会话
 path(
 "coding-sessions/",
 CodingSessionListView.as_view,
 name="coding-session-list",
 ),
 path(
 "coding-sessions/<uuid:session_id>/",
 CodingSessionDetailView.as_view,
 name="coding-session-detail",
 ),
 path(
 "coding-sessions/<uuid:session_id>/confirm/",
 CodingSessionConfirmView.as_view,
 name="coding-session-confirm",
 ),
]
