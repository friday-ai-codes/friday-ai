"""URL configuration for chat app."""
from django.urls import path
from .views import (
 ChatCompletionsView,
 ChatInterruptView,
 ChatStreamView,
 ConversationDetailView,
 ConversationListView,
 ModelsView,
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
 "conversations/<uuid:conversation_id>/interrupt/",
 ChatInterruptView.as_view,
 name="conversation-interrupt",
 ),
]
