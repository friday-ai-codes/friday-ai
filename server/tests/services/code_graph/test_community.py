"""``services/code_graph/community.py`` 验收测（MOD-01 / MOD-02）。

125-02：Louvain / 指纹 / 取图纪律。
125-03：rebuild×2 LLM=0 / Jaccard / 空摘要重试（仍 skip）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import networkx as nx
import pytest

import services.code_graph.community as community_mod


def test_louvain_seed_stable() -> None:
    """同投影图两次 Louvain 划分一致；``LOUVAIN_SEED`` 常量存在。

    （Req: MOD-01, 决策: D-04/D-05）
    """
    assert hasattr(community_mod, "LOUVAIN_SEED")
    assert isinstance(community_mod.LOUVAIN_SEED, int)

    g = nx.MultiDiGraph()
    # 两个紧耦合团 + 桥，规模均 ≥5。
    for i in range(6):
        g.add_node(f"a{i}", name=f"a{i}", symbol_type="FUNCTION", file_path="a.py", start_line=i, end_line=i)
    for i in range(6):
        g.add_node(f"b{i}", name=f"b{i}", symbol_type="FUNCTION", file_path="b.py", start_line=i, end_line=i)
    for i in range(5):
        g.add_edge(f"a{i}", f"a{i + 1}", kind="call", confidence="resolved", line_number=i)
        g.add_edge(f"b{i}", f"b{i + 1}", kind="call", confidence="resolved", line_number=i)
    g.add_edge("a0", "b0", kind="call", confidence="resolved", line_number=0)

    u = community_mod.project_undirected(g)
    from networkx.algorithms.community import louvain_communities

    c1 = [frozenset(c) for c in louvain_communities(u, seed=community_mod.LOUVAIN_SEED)]
    c2 = [frozenset(c) for c in louvain_communities(u, seed=community_mod.LOUVAIN_SEED)]
    assert sorted(c1, key=lambda s: sorted(s)) == sorted(c2, key=lambda s: sorted(s))


def test_project_undirected_sorted_nodes_edges() -> None:
    """无向投影节点/边按稳定序输出（确定性划分前置）。

    （Req: MOD-01, 决策: D-05）
    """
    g = nx.MultiDiGraph()
    g.add_nodes_from(["z", "a", "m"])
    g.add_edge("z", "a")
    g.add_edge("m", "a")
    g.add_edge("a", "z")  # reverse duplicate → undirected 去重
    frozen = nx.freeze(g.copy())

    u = community_mod.project_undirected(frozen)
    assert list(u.nodes()) == sorted(["z", "a", "m"])
    assert list(u.edges()) == sorted([("a", "m"), ("a", "z")])
    # 原图未 mutate
    assert frozen.number_of_nodes() == 3


def test_fingerprint_deterministic_order_independent() -> None:
    """成员 fingerprint 与成员顺序无关、同集合结果稳定。

    （Req: MOD-02, 决策: D-06）
    """
    members_a = [
        {"symbol_id": "bbb", "name": "b", "file_path": "b.py", "symbol_type": "FUNCTION"},
        {"symbol_id": "aaa", "name": "a", "file_path": "a.py", "symbol_type": "CLASS"},
    ]
    members_b = list(reversed(members_a))
    fp_a = community_mod.member_fingerprint(members_a)
    fp_b = community_mod.member_fingerprint(members_b)
    assert fp_a == fp_b
    assert len(fp_a) == 32
    assert fp_a == community_mod.member_fingerprint(members_a)


@pytest.mark.skip(reason="Wave 0 桩：由 125-03 落地")
def test_fingerprint_jaccard_skip() -> None:
    """指纹全等 short-circuit；Jaccard≥阈值复用既有 summary。

    （Req: MOD-02, 决策: D-06/D-07）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-03 落地")
def test_rebuild_twice_zero_llm() -> None:
    """无代码变更连续 rebuild 两次 → LLM 调用数 = 0（验收铁律）。

    （Req: MOD-02, 决策: D-07）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-03 落地")
def test_empty_summary_retries() -> None:
    """既有 summary 为空时允许重试生成（仍计 LLM）。

    （Req: MOD-02, 决策: D-08）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-03 落地")
def test_unclustered_or_small_skips_llm() -> None:
    """unclustered 或规模过小社区不调 LLM。

    （Req: MOD-02/MOD-03, 决策: D-08）
    """
    pytest.fail("Wave 0 桩")


def test_get_graph_only_no_loader_import() -> None:
    """源文件静态：``community.py`` 不 import loader/cache，只经 ``get_graph_service``。

    （Req: MOD-01, 威胁: T-125-01）
    """
    path = Path(community_mod.__file__).resolve()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden_modules = {
        "services.code_graph.loader",
        "services.code_graph.cache",
    }
    forbidden_names = {"loader", "cache"}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod not in forbidden_modules, f"forbidden import from {mod}"
            if mod == "services.code_graph":
                for alias in node.names:
                    assert alias.name not in forbidden_names, (
                        f"forbidden from services.code_graph import {alias.name}"
                    )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden_modules
                assert not alias.name.startswith("services.code_graph.loader")
                assert not alias.name.startswith("services.code_graph.cache")

    src = path.read_text(encoding="utf-8")
    assert "get_graph_service" in src
