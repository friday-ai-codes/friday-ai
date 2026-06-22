"""codegraph 仓库嵌套 URL 路由。

挂载于 repositories/urls.py 末尾：
    path("<uuid:repository_id>/codegraph/", include("codegraph.urls"))

所有路由均在 /api/repositories/{repository_id}/codegraph/ 前缀下。
"""

from django.urls import path

from codegraph.views import (
    CallsForSymbolView,
    CodegraphCancelView,
    CodegraphDeleteView,
    CodegraphHistoryListView,
    CodegraphProgressStreamView,
    CodegraphRebuildView,
    CodegraphStatsView,
    EndpointListView,
    GraphNeighborsView,
    ImportEdgeListView,
    SymbolListView,
)

urlpatterns = [
    path("symbols/", SymbolListView.as_view(), name="codegraph-symbol-list"),
    path(
        "symbols/<uuid:symbol_id>/calls/",
        CallsForSymbolView.as_view(),
        name="codegraph-calls-for-symbol",
    ),
    path("imports/", ImportEdgeListView.as_view(), name="codegraph-import-list"),
    path("endpoints/", EndpointListView.as_view(), name="codegraph-endpoint-list"),
    # 结构化图谱累计计数（前端"N 关系"用，区别于 GraphBuildHistory 的 per-run delta）
    path("stats/", CodegraphStatsView.as_view(), name="codegraph-stats"),
    # 统一邻居查询（file | component | symbol）。具名前缀放空 path 之前。
    path(
        "graph/neighbors/",
        GraphNeighborsView.as_view(),
        name="codegraph-graph-neighbors",
    ),
    # implementation-04 / work item-05：REST 三件套
    # 显式前缀放在根路径 CodegraphDeleteView 之前避免被空字符串 path 抢匹配。
    path(
        "rebuild/",
        CodegraphRebuildView.as_view(),
        name="codegraph-rebuild",
    ),
    path(
        "cancel/",
        CodegraphCancelView.as_view(),
        name="codegraph-cancel",
    ),
    path(
        "history/",
        CodegraphHistoryListView.as_view(),
        name="codegraph-history-list",
    ),
    # implementation-04：SSE 端点仅推图谱构建进度，与扩展后的
    # IndexProgressStreamView 共享 _build_graph_payload helper。必须放在
    # 末尾空字符串 path 之前（与 rebuild/cancel/history 同顺序敏感约束）。
    path(
        "stream/",
        CodegraphProgressStreamView.as_view(),
        name="codegraph-progress-stream",
    ),
    # implementation-03：DELETE /api/repositories/{id}/codegraph/
    # 挂在根路径，仅清图谱三件套保留向量轨；并发 RUNNING 时返 409。
    path("", CodegraphDeleteView.as_view(), name="codegraph-delete"),
]
