from django.urls import path

from .views import ChatCompletionsView, MessagesView, ModelsView

urlpatterns = [
    # 双路由兼容策略：OpenAI SDK 默认不带末尾斜杠，project instructions 要求带斜杠
    # Django APPEND_SLASH=True 对 POST 会 redirect（变 GET 报错），必须直接双注册
    path("chat/completions", ChatCompletionsView.as_view()),
    path("chat/completions/", ChatCompletionsView.as_view()),
    path("models", ModelsView.as_view()),
    path("models/", ModelsView.as_view()),
    path("messages", MessagesView.as_view()),
    path("messages/", MessagesView.as_view()),
]
