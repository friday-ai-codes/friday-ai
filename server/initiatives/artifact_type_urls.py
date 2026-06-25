"""工件类型管理 URL configuration（/api/artifact-types/，超管 CRUD，ARTIFACT-01/05）。"""

from django.urls import path

from initiatives.views import ArtifactTypeDetailView, ArtifactTypeListCreateView

urlpatterns = [
    path("", ArtifactTypeListCreateView.as_view(), name="artifact-type-list"),
    path("<uuid:type_id>/", ArtifactTypeDetailView.as_view(), name="artifact-type-detail"),
]
