"""Galaxy API URL 路由。
挂载于 friday/urls.py：
 path("api/codegraph/galaxy/", include("codegraph.galaxy.urls"))
路由列表：
- GET /api/codegraph/galaxy/ → GalaxyView
- GET /api/codegraph/galaxy/search/ → GalaxySearchView
- GET /api/codegraph/galaxy/nodes/<id>/ → GalaxyNodeDetailView
"""
from django.urls import path
from codegraph.galaxy.views import GalaxyNodeDetailView, GalaxySearchView, GalaxyView
urlpatterns = [
 path("", GalaxyView.as_view, name="galaxy-list"),
 path("search/", GalaxySearchView.as_view, name="galaxy-search"),
 path("nodes/<str:node_id>/", GalaxyNodeDetailView.as_view, name="galaxy-node-detail"),
]
