"""delivery URL configuration（Phase 28-03 最小 REST）。

字面段路由（IsAuthenticated）：手动 upsert + 按三元组读取 WorkItem。
"""

from django.urls import path

from delivery.api.views import WorkItemDetailView, WorkItemUpsertView

urlpatterns = [
    path("work-items/upsert/", WorkItemUpsertView.as_view(), name="work-item-upsert"),
    path("work-items/", WorkItemDetailView.as_view(), name="work-item-detail"),
]
