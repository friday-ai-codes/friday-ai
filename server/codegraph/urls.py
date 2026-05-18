"""codegraph 仓库嵌套 URL 路由。
挂载于 repositories/urls.py 末尾：
 path("<uuid:repository_id>/codegraph/", include("codegraph.urls"))
所有路由均在 /api/repositories/{repository_id}/codegraph/ 前缀下。
"""
from django.urls import path
from codegraph.views import (
 CallsForSymbolView,
 CodegraphDeleteView,
 EndpointListView,
 ImportEdgeListView,
 SymbolListView,
)
urlpatterns = [
 path("symbols/", SymbolListView.as_view, name="codegraph-symbol-list"),
 path(
 "symbols/<uuid:symbol_id>/calls/",
 CallsForSymbolView.as_view,
 name="codegraph-calls-for-symbol",
 ),
 path("imports/", ImportEdgeListView.as_view, name="codegraph-import-list"),
 path("endpoints/", EndpointListView.as_view, name="codegraph-endpoint-list"),
 # Phase GRAPH-：DELETE /api/repositories/{id}/codegraph/
 # 挂在根路径，仅清图谱三件套保留向量轨；并发 RUNNING 时返 409。
 path("", CodegraphDeleteView.as_view, name="codegraph-delete"),
]
