"""tools app URL configuration —— 执行端点。

挂载于 ``/api/tools/``：
- ``execute/`` → RemoteToolExecuteView（PAT-only fail-closed 执行）
"""

from django.urls import path

from .views import RemoteToolExecuteView

urlpatterns = [
    path("execute/", RemoteToolExecuteView.as_view(), name="tool-execute"),
]
