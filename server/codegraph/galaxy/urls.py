"""Galaxy API URL 路由。

挂载于 friday/urls.py：
    path("api/codegraph/galaxy/", include("codegraph.galaxy.urls"))

路由列表：
- GET /api/codegraph/galaxy/               → GalaxyView         (L1 细粒度)
- GET /api/codegraph/galaxy/repos/         → GalaxyReposView    (L2 仓库节点)
- GET /api/codegraph/galaxy/search/        → GalaxySearchView
- GET /api/codegraph/galaxy/nodes/<id>/    → GalaxyNodeDetailView
"""

from django.urls import path

from codegraph.galaxy.views import (
    GalaxyNodeDetailView,
    GalaxyReposView,
    GalaxySearchView,
    GalaxyView,
)

urlpatterns = [
    path("", GalaxyView.as_view(), name="galaxy-list"),
    path("repos/", GalaxyReposView.as_view(), name="galaxy-repos"),
    path("search/", GalaxySearchView.as_view(), name="galaxy-search"),
    path("nodes/<str:node_id>/", GalaxyNodeDetailView.as_view(), name="galaxy-node-detail"),
]
