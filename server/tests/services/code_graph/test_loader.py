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

from services.code_graph.access import build_matcher_and_fingerprint
from services.code_graph.loader import (
    _EDGE_ATTR_KEYS,
    _NODE_ATTR_KEYS,
    load_graph,
)


def _assemble(repository, branch: str = "", *, include_low_confidence: bool = False):
    """按仓库当前的真实 exclusion 规则装配整张图。

    ⚠️ ``matcher`` 与 ``exclusion_fingerprint`` 由**调用方**解析后注入——``loader``
    是纯装配层，自身不做规则解析（真实链路里这一步由 ``cache.py`` 承担，一次取图
    只解析一次）。
    """
    matcher, fingerprint = build_matcher_and_fingerprint(str(repository.id))
    return load_graph(
        str(repository.id),
        branch,
        matcher=matcher,
        exclusion_fingerprint=fingerprint,
        include_low_confidence=include_low_confidence,
    )


# 121-VALIDATION.md 121-05-T1：四类数据装配成 MultiDiGraph，节点/边计数与档位正确。
@pytest.mark.django_db
def test_assembles_multidigraph(
    indexed_repo, symbols_factory, call_edges_factory
) -> None:
    """图对象是 ``MultiDiGraph``，且同一对节点可并存多档边（D-01）。"""
    caller = symbols_factory("caller", "src/a.py")
    callee = symbols_factory("callee", "src/b.py")
    call_edges_factory(caller, callee, line_number=7)

    result = _assemble(indexed_repo)
    graph = result.graph

    assert isinstance(graph, nx.MultiDiGraph)
    assert graph.is_multigraph() is True
    assert set(graph.nodes) == {str(caller.id), str(callee.id)}
    assert result.meta.node_count == 2
    assert result.meta.edge_count == 1

    # 解析边（``callee_symbol`` 非空）的档位与种类。
    data = next(iter(graph.get_edge_data(str(caller.id), str(callee.id)).values()))
    assert data["kind"] == "call"
    assert data["confidence"] == "resolved"
    assert data["line_number"] == 7

    # 🚨 D-01 的核心回归：DiGraph 对同一对节点的第二条边是**静默覆盖**，
    #    四档边契约要求不同 kind 的边并存。这里再加一条，两条必须都在。
    u, v = str(caller.id), str(callee.id)
    graph.add_edge(u, v, kind="cross_repo", confidence="cross_repo", line_number=2)
    assert graph.number_of_edges(u, v) == 2

    # 节点属性个数是内存契约：恒 5 个，⛔ 不含 signature（TextField，数 KB）。
    for _node, node_data in graph.nodes(data=True):
        assert set(node_data) == _NODE_ATTR_KEYS
        assert "signature" not in node_data
        assert "chunk_id" not in node_data


@pytest.mark.django_db
def test_edge_attrs_are_exactly_three_without_reason(
    indexed_repo, symbols_factory, call_edges_factory
) -> None:
    """边属性恒 3 个，``reason`` 现推不存（D-08）。"""
    caller = symbols_factory("caller", "src/a.py")
    callee = symbols_factory("callee", "src/b.py")
    call_edges_factory(caller, callee)

    graph = _assemble(indexed_repo).graph

    assert graph.number_of_edges() == 1
    for _u, _v, data in graph.edges(data=True):
        assert set(data) == _EDGE_ATTR_KEYS
        # 第 4 个属性会让每条边跳一个内存尺寸级（30 万边约 +6.9MB）。
        assert "reason" not in data


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

    feature_graph = _assemble(indexed_repo, "feat/x").graph
    names = {data["name"] for _n, data in feature_graph.nodes(data=True)}

    assert names == {"g", "f2"}, "base 的 b.py 应保留，a.py 应被 feature 整文件覆盖"
    # 去重键是整文件、不含行号——否则漂移后的 f2 与 f 会并存成两个节点。
    assert "f" not in names

    base_graph = _assemble(indexed_repo, "").graph
    base_names = {data["name"] for _n, data in base_graph.nodes(data=True)}
    assert base_names == {"f", "g"}, "以 base 装配时不应看见 feature 分支的增量行"


# ── 121-05-T3：裸名边的开关与三道过滤 ───────────────────────────────────────


@pytest.mark.django_db
def test_bare_name_edge_not_loaded_by_default(
    indexed_repo, symbols_factory, call_edges_factory
) -> None:
    """裸名边默认不装载；显式开启且三道过滤全过时才出现，档位为 ``bare_name``。"""
    caller = symbols_factory("caller", "src/a.py")
    symbols_factory("helper", "src/a.py", start_line=50, end_line=60)
    call_edges_factory(
        caller, None, callee_name="helper", callee_file="src/a.py", line_number=12
    )

    assert _assemble(indexed_repo).graph.number_of_edges() == 0

    graph = _assemble(indexed_repo, include_low_confidence=True).graph
    assert graph.number_of_edges() == 1
    _u, _v, data = next(iter(graph.edges(data=True)))
    assert data["confidence"] == "bare_name"
    assert data["kind"] == "call"
    assert data["line_number"] == 12


@pytest.mark.django_db
def test_bare_name_cross_directory_dropped(
    indexed_repo, symbols_factory, call_edges_factory
) -> None:
    """过滤 ①：跨目录同名一律丢弃（同名命中率极高，保留即制造假阳性）。"""
    caller = symbols_factory("caller", "src/a.py")
    symbols_factory("helper", "vendor/a.py")
    call_edges_factory(caller, None, callee_name="helper", callee_file="vendor/a.py")

    assert _assemble(indexed_repo, include_low_confidence=True).graph.number_of_edges() == 0


@pytest.mark.django_db
def test_bare_name_qualifier_mismatch_dropped(
    indexed_repo, symbols_factory, call_edges_factory
) -> None:
    """过滤 ②：``callee_qualifier`` 对不上候选文件的模块/包名即丢弃。"""
    caller = symbols_factory("caller", "src/a.py")
    symbols_factory("helper", "src/util.py")
    call_edges_factory(
        caller,
        None,
        callee_name="helper",
        callee_file="src/util.py",
        callee_qualifier="other",
    )
    assert _assemble(indexed_repo, include_low_confidence=True).graph.number_of_edges() == 0

    # 限定符与模块名（basename 去扩展名）对得上时放行。
    call_edges_factory(
        caller,
        None,
        callee_name="helper",
        callee_file="src/util.py",
        callee_qualifier="util",
    )
    assert _assemble(indexed_repo, include_low_confidence=True).graph.number_of_edges() == 1


@pytest.mark.django_db
def test_bare_name_blacklisted_name_dropped(
    indexed_repo, symbols_factory, call_edges_factory
) -> None:
    """过滤 ③：``callee_name`` 命中 ``BARE_NAME_BLACKLIST`` 即丢弃。"""
    caller = symbols_factory("caller", "src/a.py")
    symbols_factory("handle", "src/a.py", start_line=50, end_line=60)
    call_edges_factory(
        caller, None, callee_name="handle", callee_file="src/a.py"
    )

    # 同目录 + 无限定符，前两道都过，只被黑名单挡下。
    assert _assemble(indexed_repo, include_low_confidence=True).graph.number_of_edges() == 0


@pytest.mark.django_db
def test_module_level_caller_edge_dropped(
    indexed_repo, symbols_factory, call_edges_factory
) -> None:
    """``caller_symbol_id IS NULL``（模块级调用）的边被丢弃且不抛异常（D-05 同理）。"""
    callee = symbols_factory("callee", "src/b.py")
    call_edges_factory(None, callee)

    result = _assemble(indexed_repo)

    assert result.graph.number_of_edges() == 0
    # ⛔ 不用 caller_file 造虚拟节点：虚拟节点会污染上层的深度分组与计数。
    assert result.meta.node_count == 1


# ── 121-05-T3：解析率 ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_resolution_rate_and_low_resolution_flag(
    indexed_repo, symbols_factory, call_edges_factory
) -> None:
    """``resolution_rate`` 按全部落库边统计，且与 ``include_low_confidence`` 无关。"""
    caller = symbols_factory("caller", "src/a.py")
    targets = [
        symbols_factory(f"t{i}", "src/b.py", start_line=10 * i + 1, end_line=10 * i + 5)
        for i in range(4)
    ]

    # 2 条解析边 + 3 条裸名边 ⇒ 0.4 < 0.6 阈值。
    for target in targets[:2]:
        call_edges_factory(caller, target)
    for i in range(3):
        call_edges_factory(
            caller, None, callee_name=f"missing{i}", callee_file="src/z.py"
        )

    closed = _assemble(indexed_repo)
    opened = _assemble(indexed_repo, include_low_confidence=True)

    assert closed.meta.resolution_rate == pytest.approx(0.4)
    assert closed.meta.low_resolution is True
    # 🚨 开关不得影响解析率——否则关掉裸名时解析率恒为 1.0，变成一个假信号。
    assert opened.meta.resolution_rate == pytest.approx(0.4)
    assert opened.meta.low_resolution is True

    # 补足到 4 解析 + 1 裸名的另一组：0.8 ≥ 阈值。
    other = symbols_factory("other", "src/c.py")
    for target in targets[2:]:
        call_edges_factory(other, target)
    from codegraph.models import CallEdge

    CallEdge.objects.filter(callee_symbol__isnull=True).exclude(
        callee_name="missing0"
    ).delete()

    result = _assemble(indexed_repo)
    assert result.meta.resolution_rate == pytest.approx(0.8)
    assert result.meta.low_resolution is False


@pytest.mark.django_db
def test_resolution_rate_defaults_to_one_without_edges(
    indexed_repo, symbols_factory
) -> None:
    """一条调用边都没有时解析率定义为 ``1.0``，不误报 ``low_resolution``。"""
    symbols_factory("lonely", "src/a.py")

    meta = _assemble(indexed_repo).meta

    assert meta.resolution_rate == pytest.approx(1.0)
    assert meta.low_resolution is False


@pytest.mark.django_db
def test_meta_carries_injected_exclusion_fingerprint(
    indexed_repo, symbols_factory
) -> None:
    """指纹由入参注入、原样写进 ``GraphMeta``，loader 不重算。"""
    symbols_factory("s", "src/a.py")
    _matcher, fingerprint = build_matcher_and_fingerprint(str(indexed_repo.id))

    meta = _assemble(indexed_repo).meta

    assert meta.built_signature == fingerprint
    assert meta.repository_id == str(indexed_repo.id)
    assert meta.branch == ""
    assert meta.degraded == ""
    assert meta.partial_edges is False


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
