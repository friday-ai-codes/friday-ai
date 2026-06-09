"""tools app URL configuration —— 绑定 CRUD + 可绑定列表 + 执行端点。

挂载于 ``/api/tools/``：
- ``bindings/``  → ToolTokenBindingViewSet（list/create-upsert/delete，owner 隔离）
- ``bindable/``  → BindableToolsView（仅 mcp/skill + active）
- ``execute/``   → RemoteToolExecuteView（PAT-only fail-closed 执行）
"""

from adrf.routers import DefaultRouter
from django.urls import include, path

from .views import BindableToolsView, RemoteToolExecuteView, ToolTokenBindingViewSet

router = DefaultRouter()
router.register("bindings", ToolTokenBindingViewSet, basename="tool-binding")

urlpatterns = [
    path("", include(router.urls)),
    path("bindable/", BindableToolsView.as_view(), name="bindable-tools"),
    path("execute/", RemoteToolExecuteView.as_view(), name="tool-execute"),
]
