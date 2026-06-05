"""codegraph Playground 顶层 URL 路由。

挂载于 friday/urls.py：
    path("api/codegraph/", include("codegraph.playground_urls"))

路由：POST /api/codegraph/playground/search/
"""

from django.urls import path

from codegraph.playground_views import PlaygroundSearchView

urlpatterns = [
    path(
        "playground/search/",
        PlaygroundSearchView.as_view(),
        name="codegraph-playground-search",
    ),
]
