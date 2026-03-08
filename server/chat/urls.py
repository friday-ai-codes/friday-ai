"""URL configuration for chat app."""
from django.urls import path
from .views import (
 ChatCompletionsView,
 ChatStreamView,
 ConversationDetailView,
 ConversationListView,
 ModelsView,
 ProviderHealthView,
 ProviderListView,
 ProviderModelsView,
 SendMessageView,
)
urlpatterns = [
 # 现有 Chat Protocol API
 path("models", ModelsView.as_view, name="chat-models"),
 path("completions", ChatCompletionsView.as_view, name="chat-completions"),
 # Conversation API (Phase)
 path("conversations/", ConversationListView.as_view, name="conversation-list"),
 path(
 "conversations/<uuid:conversation_id>/",
 ConversationDetailView.as_view,
 name="conversation-detail",
 ),
 path(
 "conversations/<uuid:conversation_id>/messages/",
 SendMessageView.as_view,
 name="conversation-messages",
 ),
 path(
 "conversations/<uuid:conversation_id>/stream/",
 ChatStreamView.as_view,
 name="conversation-stream",
 ),
 # Provider API (Phase)
 path("providers/", ProviderListView.as_view, name="provider-list"),
 path(
 "providers/<str:provider_type>/models/",
 ProviderModelsView.as_view,
 name="provider-models",
 ),
 path(
 "providers/<str:provider_type>/health/",
 ProviderHealthView.as_view,
 name="provider-health",
 ),
]
