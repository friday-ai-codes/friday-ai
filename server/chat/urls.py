"""URL configuration for chat app."""
from django.urls import path
from .views import ChatCompletionsView, ModelsView
urlpatterns = [
 path("models", ModelsView.as_view, name="chat-models"),
 path("completions", ChatCompletionsView.as_view, name="chat-completions"),
]
