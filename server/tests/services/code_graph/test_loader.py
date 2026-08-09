"""``services/code_graph/loader.py`` 的装配用例（覆盖 GRAPH-01、GRAPH-03）。

**Plan 121-05** 落地本文件的符号装配（overlay 去重 / MultiDiGraph 语义）与
``CallEdge`` 双档装配（裸名三道过滤 / 解析率）；**Plan 121-06** 填充其余三个桩
（跨仓边二次解析、ChunkEdge 旁挂证据面、按需子图）。

桩的存在是 Wave 0 的 Nyquist 要求：121-VALIDATION.md 里每个 ``-k`` 选择器都必须
从第一个 task 起就能解析到真实用例名。
"""

from __future__ import annotations

import networkx as nx
import pytest

from services.code_graph.access import (
    build_matcher_and_fingerprint,
    make_path_exclusion_memo,
)
from services.code_graph.loader import _NODE_ATTR_KEYS, _load_symbol_nodes


def _assemble_nodes(repository, branch: str = "") -> tuple[nx.MultiDiGraph, object]:
    """按当前仓库的真实 exclusion 规则装配符号节点。

    ⚠️ matcher 由**调用方**解析并注入——``loader`` 是纯装配层，自己不做规则解析
    （Plan 121-05 Task 2 的架构红线，`cache.py` 会在真实链路里做同样的事）。
    """
    matcher, _fingerprint = build_matcher_and_fingerprint(str(repository.id))
    graph = nx.MultiDiGraph()
    index = _load_symbol_nodes(
        graph,
        repository_id=str(repository.id),
        branch=branch,
        is_excluded=make_path_exclusion_memo(matcher),
    )
    return graph, index


# 121-VALIDATION.md 121-05-T1：四类数据装配成 MultiDiGraph，节点/边计数与档位正确。
@pytest.mark.django_db
def test_assembles_multidigraph(indexed_repo, symbols_factory) -> None:
    """图对象是 ``MultiDiGraph``，且同一对节点可并存多档边（D-01）。"""
    caller = symbols_factory("caller", "src/a.py")
    callee = symbols_factory("callee", "src/b.py")

    graph, index = _assemble_nodes(indexed_repo)

    assert isinstance(graph, nx.MultiDiGraph)
    assert graph.is_multigraph() is True
    assert index.node_ids == {str(caller.id), str(callee.id)}

    # 🚨 D-01 的核心回归：DiGraph 对同一对节点的第二条边是**静默覆盖**，
    #    四档边契约要求不同 kind 的边并存。这里连加两条，必须都留下。
    u, v = str(caller.id), str(callee.id)
    graph.add_edge(u, v, kind="call", confidence="resolved", line_number=1)
    graph.add_edge(u, v, kind="cross_repo", confidence="cross_repo", line_number=2)
    assert graph.number_of_edges(u, v) == 2

    # 节点属性个数是内存契约：恒 5 个，⛔ 不含 signature（TextField，数 KB）。
    for _node, data in graph.nodes(data=True):
        assert set(data) == _NODE_ATTR_KEYS
        assert "signature" not in data
        assert "chunk_id" not in data


# 121-VALIDATION.md 121-06-T1：CrossRepoApiCall 按 file+name 解析到符号；
# 解析不上直接丢弃（不建虚拟节点）并计数上报 cross_repo_unresolved_count（D-05）。
@pytest.mark.skip(reason="stub：由 Plan 121-06 实现")
def test_cross_repo_edge_resolution() -> None:
    pass


# 121-VALIDATION.md 121-05-T1：feature 分支 overlay（base ∪ feature），
# 同文件 feature 覆盖 base，去重键取整文件（D-06）。
@pytest.mark.django_db
def test_branch_overlay_feature_over_base(indexed_repo, symbols_factory) -> None:
    """feature 取到 base ∪ feature，且同文件的 base 行被**整文件**覆盖。"""
    symbols_factory("f", "a.py")
    symbols_factory("g", "b.py")
    # feature 分支只写增量行：同一个 a.py 里换了个符号名（行号也漂移了）。
    symbols_factory("f2", "a.py", branch_name="feat/x", start_line=20, end_line=30)

    feature_graph, _index = _assemble_nodes(indexed_repo, "feat/x")
    names = {data["name"] for _n, data in feature_graph.nodes(data=True)}

    assert names == {"g", "f2"}, "base 的 b.py 应保留，a.py 应被 feature 整文件覆盖"
    # 去重键是整文件、不含行号——否则漂移后的 f2 与 f 会并存成两个节点。
    assert "f" not in names

    base_graph, _base_index = _assemble_nodes(indexed_repo, "")
    base_names = {data["name"] for _n, data in base_graph.nodes(data=True)}
    assert base_names == {"f", "g"}, "以 base 装配时不应看见 feature 分支的增量行"


# 121-VALIDATION.md 121-06-T2：ChunkEdge 走旁挂证据面，绝不进 MultiDiGraph 边集
# （chunk 与 symbol 粒度不同，展开成符号级边会笛卡尔爆炸）。
@pytest.mark.skip(reason="stub：由 Plan 121-06 实现")
def test_chunk_evidence_side_channel() -> None:
    pass


# 121-VALIDATION.md 121-06-T3：按需子图在 SQL 侧多跳收敛，
# 查询次数不随仓库规模增长（深度有界，不先全量再裁剪）。
@pytest.mark.skip(reason="stub：由 Plan 121-06 实现")
def test_on_demand_subgraph_depth_bounded() -> None:
    pass
