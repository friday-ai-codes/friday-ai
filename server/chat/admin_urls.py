"""管理员只读会话后台路由（ADMVW-01/02/03）。

挂载在 ``/api/admin/conversations/``（顶层 friday/urls.py api_patterns 内
``path("admin/", include("chat.admin_urls"))``）。与 Phase 8 锁定的 chat.urls
**物理分离**，仅暴露只读 GET（list/detail）+ fork POST。

``<uuid:conversation_id>`` 路径转换器即输入校验（非法 id → URLconf 不匹配 404）。
"""

from django.urls import path

from .admin_views import (
    AdminConversationDetailView,
    AdminConversationForkView,
    AdminConversationListView,
)

urlpatterns = [
    path(
        "conversations/",
        AdminConversationListView.as_view(),
        name="admin-conversation-list",
    ),
    path(
        "conversations/<uuid:conversation_id>/",
        AdminConversationDetailView.as_view(),
        name="admin-conversation-detail",
    ),
    path(
        "conversations/<uuid:conversation_id>/fork/",
        AdminConversationForkView.as_view(),
        name="admin-conversation-fork",
    ),
]
