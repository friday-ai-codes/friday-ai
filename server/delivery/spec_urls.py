"""spec 治理 URL configuration（Phase 50-03，D-50-4）。

独立 ``/api/specs/`` 端点：list（过滤）/ detail（正文+评审历史）/ transition（流转）。
"""

from django.urls import path

from delivery.api.spec_views import (
    SpecDetailView,
    SpecListView,
    SpecTransitionView,
)

urlpatterns = [
    path("", SpecListView.as_view(), name="spec-list"),
    path("<uuid:spec_id>/", SpecDetailView.as_view(), name="spec-detail"),
    path(
        "<uuid:spec_id>/transition/",
        SpecTransitionView.as_view(),
        name="spec-transition",
    ),
]
