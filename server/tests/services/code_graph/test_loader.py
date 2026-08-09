"""``services/code_graph/loader.py`` 的装配用例（覆盖 GRAPH-01、GRAPH-03）。

**Plan 121-05** 落地本文件的符号装配（overlay 去重 / MultiDiGraph 语义）与
``CallEdge`` 双档装配（裸名三道过滤 / 解析率）；**Plan 121-06** 填充其余三个桩
（跨仓边二次解析、ChunkEdge 旁挂证据面、按需子图）。

桩的存在是 Wave 0 的 Nyquist 要求：121-VALIDATION.md 里每个 ``-k`` 选择器都必须
从第一个 task 起就能解析到真实用例名。
"""

from __future__ import annotations

import uuid

import networkx as nx
import pytest

from services.code_graph.access import build_matcher_and_fingerprint
from services.code_graph.loader import (
    _CROSS_REPO_EDGE_ATTR_KEYS,
    _EDGE_ATTR_KEYS,
    _NODE_ATTR_KEYS,
    CHUNK_EVIDENCE_MAX_PER_SYMBOL,
    load_graph,
    load_subgraph,
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


def _make_cross_repo_call(
    repository,
    *,
    caller_file: str,
    caller_function: str,
    endpoint_file: str,
    handler_name: str,
    match_confidence: float = 0.7,
    caller_line: int = 33,
):
    """造一条 ``CrossRepoApiCall`` 及其两端（``ApiCallSite`` / ``Endpoint``）。

    ⚠️ 两端都**没有 ``Symbol`` 外键**，``CrossRepoApiCall`` 自身也**没有
    ``repository`` 字段**——这正是 loader 必须做「文件路径 + 名字」二次解析、
    并按 ``call_site__repository_id`` / ``endpoint__repository_id`` 反查过滤的原因。
    """
    from codegraph.models import ApiCallSite, ApiWrapper, CrossRepoApiCall, Endpoint

    wrapper = ApiWrapper.objects.create(
        repository=repository,
        file_path="web/src/api/orders.ts",
        function_symbol=f"fetch_{handler_name}",
        http_method="GET",
        url_path_raw="/api/orders",
        url_path_pattern="/api/orders",
    )
    call_site = ApiCallSite.objects.create(
        repository=repository,
        api_wrapper=wrapper,
        caller_file=caller_file,
        caller_function=caller_function,
        line_number=caller_line,
    )
    endpoint = Endpoint.objects.create(
        repository=repository,
        http_method="GET",
        url_path="/api/orders",
        handler_name=handler_name,
        view_type="FUNCTION_VIEW",
        file_path=endpoint_file,
        line_number=8,
    )
    return CrossRepoApiCall.objects.create(
        call_site=call_site,
        endpoint=endpoint,
        match_confidence=match_confidence,
    )


# 121-VALIDATION.md 121-06-T1：CrossRepoApiCall 按 file+name 解析到符号；
# 解析不上直接丢弃（不建虚拟节点）并计数上报 cross_repo_unresolved_count（D-05）。
@pytest.mark.django_db
def test_cross_repo_edge_resolution(indexed_repo, symbols_factory) -> None:
    """跨仓边的三个分支：解析成功建边 / 解析失败丢弃计数 / 全程不建虚拟节点。"""
    caller = symbols_factory("submitOrder", "web/src/pages/order.ts")
    handler = symbols_factory("order_create", "src/api/views.py")

    # (a) 两端都能按 (file_path, name) 解析到本图已装载的符号。
    _make_cross_repo_call(
        indexed_repo,
        caller_file="web/src/pages/order.ts",
        caller_function="submitOrder",
        endpoint_file="src/api/views.py",
        handler_name="order_create",
        match_confidence=0.7,
        caller_line=33,
    )

    result = _assemble(indexed_repo)
    graph = result.graph

    cross_edges = [
        (u, v, data)
        for u, v, data in graph.edges(data=True)
        if data["kind"] == "cross_repo"
    ]
    assert len(cross_edges) == 1
    u, v, data = cross_edges[0]
    assert (u, v) == (str(caller.id), str(handler.id))
    assert data["confidence"] == "cross_repo"
    assert data["line_number"] == 33
    # 原值透传，⛔ 不归一化——它是 confidence_score() 对本档的必需入参。
    assert data["match_confidence"] == pytest.approx(0.7)
    # 唯一允许 4 个属性的档位。
    assert set(data) == _CROSS_REPO_EDGE_ATTR_KEYS

    assert result.meta.cross_repo_unresolved_count == 0
    # 装配到跨仓边即须声明「本档无法按分支过滤」（ApiCallSite 无 branch_name）。
    assert result.meta.cross_repo_branch_unfiltered is True

    # (b) handler_name 对不上任何符号 ⇒ 该边不进图，计入 unresolved。
    _make_cross_repo_call(
        indexed_repo,
        caller_file="web/src/pages/order.ts",
        caller_function="submitOrder",
        endpoint_file="src/api/views.py",
        handler_name="ghost_handler",
        match_confidence=0.4,
    )

    result = _assemble(indexed_repo)
    graph = result.graph

    assert (
        sum(1 for _u, _v, d in graph.edges(data=True) if d["kind"] == "cross_repo") == 1
    )
    assert result.meta.cross_repo_unresolved_count == 1

    # (c) ⛔ 绝不建虚拟节点：图里每个节点都是一个真实装载过的 Symbol.id。
    loaded_symbol_ids = {str(caller.id), str(handler.id)}
    assert set(graph.nodes) <= loaded_symbol_ids


@pytest.mark.django_db
def test_cross_repo_branch_unfiltered_false_without_cross_edges(
    indexed_repo, symbols_factory, call_edges_factory
) -> None:
    """没有跨仓边时不打「无法按分支过滤」标记——长鸣的标记等于失效的标记。"""
    caller = symbols_factory("caller", "src/a.py")
    callee = symbols_factory("callee", "src/b.py")
    call_edges_factory(caller, callee)

    meta = _assemble(indexed_repo).meta

    assert meta.cross_repo_branch_unfiltered is False
    assert meta.cross_repo_unresolved_count == 0


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


def _bind_chunk(symbol, chunk_id) -> None:
    """把 ``Symbol.chunk_id`` 绑到给定 chunk（软引用，无 FK，可为 ``None``）。"""
    symbol.chunk_id = chunk_id
    symbol.save(update_fields=["chunk_id"])


def _make_chunk_edge(
    repository,
    source_chunk_id,
    target_chunk_id,
    *,
    edge_type: str = "SEMANTIC",
    weight: float = 0.8,
    target_repository_id=None,
):
    from code_relations.models import ChunkEdge

    return ChunkEdge.objects.create(
        repository=repository,
        branch_name="",
        source_chunk_id=source_chunk_id,
        target_chunk_id=target_chunk_id,
        edge_type=edge_type,
        weight=weight,
        target_repository_id=target_repository_id,
    )


# 121-VALIDATION.md 121-06-T2：ChunkEdge 走旁挂证据面，绝不进 MultiDiGraph 边集
# （chunk 与 symbol 粒度不同，展开成符号级边会笛卡尔爆炸）。
@pytest.mark.django_db
def test_chunk_evidence_side_channel(
    indexed_repo, symbols_factory, call_edges_factory
) -> None:
    """chunk 证据挂在旁挂 dict 上，图的边数不因 ``ChunkEdge`` 增加一条。"""
    caller = symbols_factory("caller", "src/a.py")
    callee = symbols_factory("callee", "src/b.py")
    call_edges_factory(caller, callee)

    # 对照组：还没有任何 ChunkEdge 时的边数。
    baseline_edges = _assemble(indexed_repo).graph.number_of_edges()

    # 两个符号共享同一个 chunk（一个 chunk 常含多个 Symbol——这正是笛卡尔爆炸的来源）。
    shared_chunk = uuid.uuid4()
    other_chunk = uuid.uuid4()
    _bind_chunk(caller, shared_chunk)
    _bind_chunk(callee, shared_chunk)
    # chunk_id 为 None 的符号：不进证据面的键，且不得抛异常。
    orphan = symbols_factory("orphan", "src/c.py")

    _make_chunk_edge(indexed_repo, shared_chunk, other_chunk)

    result = _assemble(indexed_repo)

    # 两个共享 chunk 的符号各拿到 1 条证据。
    assert set(result.chunk_evidence) == {str(caller.id), str(callee.id)}
    for symbol_id in (str(caller.id), str(callee.id)):
        records = result.chunk_evidence[symbol_id]
        assert len(records) == 1
        assert records[0].source_chunk_id == str(shared_chunk)
        assert records[0].target_chunk_id == str(other_chunk)
        assert records[0].edge_type == "SEMANTIC"
        assert records[0].weight == pytest.approx(0.8)
        assert records[0].target_repository_id is None

    assert str(orphan.id) not in result.chunk_evidence

    # 🚨 Pitfall 2：边数**不因 ChunkEdge 增加**，图里也不存在 chunk 档的边。
    assert result.graph.number_of_edges() == baseline_edges
    assert result.meta.edge_count == baseline_edges
    assert all(data["kind"] != "chunk" for _u, _v, data in result.graph.edges(data=True))


@pytest.mark.django_db
def test_chunk_evidence_fan_out_is_capped(indexed_repo, symbols_factory) -> None:
    """单个符号的证据条数被 ``CHUNK_EVIDENCE_MAX_PER_SYMBOL`` 截断（防热点 chunk）。"""
    hot = symbols_factory("hot", "src/hot.py")
    hot_chunk = uuid.uuid4()
    _bind_chunk(hot, hot_chunk)

    for _ in range(60):
        _make_chunk_edge(indexed_repo, hot_chunk, uuid.uuid4())

    result = _assemble(indexed_repo)

    assert CHUNK_EVIDENCE_MAX_PER_SYMBOL == 50
    assert len(result.chunk_evidence[str(hot.id)]) == CHUNK_EVIDENCE_MAX_PER_SYMBOL


def _assemble_subgraph(repository, branch: str = "", **kwargs):
    """按仓库当前的真实 exclusion 规则装配一张按需子图。

    ⚠️ 与 :func:`_assemble` 同款契约：``matcher`` / ``exclusion_fingerprint`` 由调用方
    注入，``load_subgraph`` 自身不做规则解析。
    """
    matcher, fingerprint = build_matcher_and_fingerprint(str(repository.id))
    return load_subgraph(
        str(repository.id),
        branch,
        matcher=matcher,
        exclusion_fingerprint=fingerprint,
        **kwargs,
    )


def _make_call_chain(symbols_factory, call_edges_factory, length: int):
    """造一条 ``s0 → s1 → … → s{length}`` 的调用链（每个符号一个文件，避免同名干扰）。"""
    chain = [
        symbols_factory(f"s{i}", f"src/s{i}.py") for i in range(length + 1)
    ]
    for i in range(length):
        call_edges_factory(chain[i], chain[i + 1], line_number=i + 1)
    return chain


# 121-VALIDATION.md 121-06-T3：按需子图在 SQL 侧多跳收敛，
# 查询次数不随仓库规模增长（深度有界，不先全量再裁剪）。
@pytest.mark.django_db
def test_on_demand_subgraph_depth_bounded(
    indexed_repo, symbols_factory, call_edges_factory
) -> None:
    """``depth=2`` 的子图收敛到 ``depth + 1 = 3`` 跳，且不含不可达符号。"""
    chain = _make_call_chain(symbols_factory, call_edges_factory, length=5)
    iso = symbols_factory("iso", "src/iso.py")

    result = _assemble_subgraph(
        indexed_repo, seed_symbol_ids=[str(chain[0].id)], depth=2
    )

    # 半径 = depth + 1 = 3 跳 ⇒ s0..s3。多留的那一跳保证 s2 的邻接是完整的。
    assert set(result.graph.nodes) == {str(s.id) for s in chain[:4]}
    assert str(chain[5].id) not in result.graph.nodes
    assert str(iso.id) not in result.graph.nodes

    # 🔔 上层必须透出：结论覆盖面小于全图。
    assert result.meta.degraded == "on_demand_subgraph"
    # 对照：全量装配不打降级标记。
    assert _assemble(indexed_repo).meta.degraded == ""


@pytest.mark.django_db
def test_on_demand_subgraph_query_count_does_not_scale_with_repo(
    indexed_repo, symbols_factory, call_edges_factory
) -> None:
    """查询次数 ≤ ``depth + 1 + 常数``，且**不随**仓库总符号数增长。

    这条是「SQL 侧多跳收敛」与「先全量装配再裁剪」的判别式：后者的取数量会随仓库
    规模线性膨胀，前者不会。
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    chain = _make_call_chain(symbols_factory, call_edges_factory, length=5)
    depth = 2
    # matcher 在计数窗口外解析——它的 DB 读属于调用方（真实链路里是 cache.py）。
    matcher, fingerprint = build_matcher_and_fingerprint(str(indexed_repo.id))

    def _count_graph_queries() -> int:
        with CaptureQueriesContext(connection) as ctx:
            load_subgraph(
                str(indexed_repo.id),
                "",
                seed_symbol_ids=[str(chain[0].id)],
                depth=depth,
                matcher=matcher,
                exclusion_fingerprint=fingerprint,
            )
        # 只数打到图数据表的查询：日志基础设施自己读 ``system_settings``（结构化日志
        # 的运行期配置），那不是装配取数，不该算进本条契约。
        return sum(
            1
            for q in ctx.captured_queries
            if "codegraph_" in q["sql"] or "code_relations_" in q["sql"]
        )

    small_repo_queries = _count_graph_queries()
    # depth + 1 轮 frontier 扩张 + 常数条（Symbol / CallEdge / CrossRepoApiCall /
    # ChunkEdge 各一条）。
    assert small_repo_queries <= depth + 1 + 4

    # 200 个与种子无关的符号：全量装配会多取 200 行，SQL 侧收敛则一条查询都不多。
    for i in range(200):
        symbols_factory(f"noise{i}", f"src/noise/{i}.py")

    assert _count_graph_queries() == small_repo_queries


@pytest.mark.django_db
def test_on_demand_subgraph_frontier_truncation(
    indexed_repo, symbols_factory, call_edges_factory, monkeypatch
) -> None:
    """每轮 frontier 撞上限即截断，并在降级事件里如实标 ``frontier_truncated``。"""
    from structlog.testing import capture_logs

    from services.code_graph import loader as loader_module

    hub = symbols_factory("hub", "src/hub.py")
    for i in range(5):
        callee = symbols_factory(f"leaf{i}", f"src/leaf{i}.py")
        call_edges_factory(hub, callee)

    monkeypatch.setattr(loader_module, "SUBGRAPH_FRONTIER_LIMIT", 2)

    with capture_logs() as events:
        result = _assemble_subgraph(
            indexed_repo, seed_symbol_ids=[str(hub.id)], depth=1
        )

    # 种子 + 至多 2 个邻居；不截断的话会是 1 + 5 = 6 个节点。
    assert result.graph.number_of_nodes() <= 3

    degraded = [e for e in events if e["event"] == "code_graph_degraded_subgraph"]
    assert len(degraded) == 1
    assert degraded[0]["frontier_truncated"] is True
    # 观测契约：component / category / 触发用户绑定。
    assert degraded[0]["component"] == "code_graph"
    assert degraded[0]["category"] == "sampling"
    assert degraded[0]["initiated_by_user_id"] == "system"


@pytest.mark.django_db
def test_on_demand_subgraph_applies_exclusion(
    indexed_repo, symbols_factory, call_edges_factory, exclusion_rule_factory
) -> None:
    """exclusion 在子图路径同口径生效：被排除文件的邻居不进节点集。"""
    seed = symbols_factory("seed", "src/ok.py")
    secret = symbols_factory("load_key", "secret/keys.py")
    call_edges_factory(seed, secret)
    exclusion_rule_factory("secret/**")

    result = _assemble_subgraph(
        indexed_repo, seed_symbol_ids=[str(seed.id)], depth=2
    )

    assert set(result.graph.nodes) == {str(seed.id)}
    # 被排除节点连同其邻接边一并消失，不是输出阶段裁剪。
    assert result.graph.number_of_edges() == 0
    assert result.meta.excluded_file_count == 1
