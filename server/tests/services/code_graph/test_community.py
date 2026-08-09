"""``services/code_graph/community.py`` 验收测（MOD-01 / MOD-02）。

125-02：Louvain / 指纹 / 取图纪律。
125-03：rebuild×2 LLM=0 / Jaccard / 空摘要重试。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import networkx as nx
import pytest

import services.code_graph.community as community_mod
from codegraph.models import SymbolCommunity


def _member(i: int, *, prefix: str = "m", file_path: str = "pkg/a.py") -> dict[str, Any]:
    return {
        "symbol_id": f"{prefix}-{i}",
        "name": f"{prefix}_fn_{i}",
        "file_path": file_path,
        "symbol_type": "FUNCTION",
    }


def _community_desc(
    members: list[dict[str, Any]],
    *,
    unclustered: bool = False,
    community_key: str | None = None,
) -> dict[str, Any]:
    fp = community_mod.member_fingerprint(members)
    key = community_key or (f"unclustered:pkg:{fp[:8]}" if unclustered else fp[:16])
    return {
        "community_key": key,
        "algorithm": "louvain",
        "unclustered": unclustered,
        "members": members,
        "member_keys": [community_mod._member_stable_key(m) for m in members],
        "member_fingerprint": fp,
        "member_count": len(members),
        "top_files": sorted({str(m["file_path"]) for m in members}),
    }


def _fake_summary_json(tag: str = "ok") -> str:
    return json.dumps(
        {
            "key_files": ["pkg/a.py"],
            "entry_points": ["m_fn_0"],
            "responsibility": f"module {tag}",
        },
        ensure_ascii=False,
    )


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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_fingerprint_jaccard_skip(repository) -> None:
    """指纹全等 short-circuit；Jaccard≥阈值复用既有 summary。

    （Req: MOD-02, 决策: D-06/D-07）
    """
    assert community_mod.JACCARD_THRESHOLD == 0.8

    members = [_member(i) for i in range(6)]
    desc = _community_desc(members)
    await SymbolCommunity.objects.acreate(
        repository=repository,
        branch_name="",
        community_key=desc["community_key"],
        algorithm="louvain",
        member_count=desc["member_count"],
        members=desc["members"],
        top_files=desc["top_files"],
        member_fingerprint=desc["member_fingerprint"],
        summary=_fake_summary_json("fp"),
        summary_model="test-model",
    )

    calls = {"n": 0}

    async def _summary_fn(ms, community):  # noqa: ANN001
        calls["n"] += 1
        return _fake_summary_json("should-not-run")

    g = nx.freeze(nx.MultiDiGraph())
    with patch.object(community_mod, "detect_communities", return_value=[desc]):
        result = await community_mod.rebuild_communities(
            str(repository.id),
            "",
            graph=g,
            summary_fn=_summary_fn,
        )

    assert calls["n"] == 0
    assert result["summaries_skipped"] >= 1
    assert result["summaries_generated"] == 0
    row = await SymbolCommunity.objects.aget(repository=repository, community_key=desc["community_key"])
    assert "module fp" in (row.summary or "")

    # Jaccard ≥ 0.8：成员集高重叠但指纹不同 → 复用旧 summary / community_key
    old_members = [_member(i, prefix="j") for i in range(10)]
    new_members = [_member(i, prefix="j") for i in range(9)] + [_member(99, prefix="j")]
    old_desc = _community_desc(old_members, community_key="old-jaccard-key")
    new_desc = _community_desc(new_members)
    assert old_desc["member_fingerprint"] != new_desc["member_fingerprint"]
    score = community_mod.jaccard(old_desc["member_keys"], new_desc["member_keys"])
    assert score >= community_mod.JACCARD_THRESHOLD

    await SymbolCommunity.objects.filter(repository=repository).adelete()
    await SymbolCommunity.objects.acreate(
        repository=repository,
        branch_name="",
        community_key=old_desc["community_key"],
        algorithm="louvain",
        member_count=old_desc["member_count"],
        members=old_desc["members"],
        top_files=old_desc["top_files"],
        member_fingerprint=old_desc["member_fingerprint"],
        summary=_fake_summary_json("jaccard"),
        summary_model="test-model",
    )
    calls["n"] = 0
    with patch.object(community_mod, "detect_communities", return_value=[new_desc]):
        result2 = await community_mod.rebuild_communities(
            str(repository.id),
            "",
            graph=g,
            summary_fn=_summary_fn,
        )
    assert calls["n"] == 0
    assert result2["summaries_generated"] == 0
    reused = await SymbolCommunity.objects.aget(repository=repository)
    assert reused.community_key == "old-jaccard-key"
    assert "module jaccard" in (reused.summary or "")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_rebuild_twice_zero_llm(repository) -> None:
    """无代码变更连续 rebuild 两次 → LLM 调用数 = 0（验收铁律）。

    （Req: MOD-02, 决策: D-07）
    """
    members = [_member(i) for i in range(6)]
    desc = _community_desc(members)
    calls = {"n": 0}

    async def _summary_fn(ms, community):  # noqa: ANN001
        calls["n"] += 1
        return _fake_summary_json(f"gen-{calls['n']}")

    g = nx.MultiDiGraph()
    for i in range(6):
        g.add_node(
            f"n{i}",
            name=f"n{i}",
            symbol_type="FUNCTION",
            file_path="a.py",
            start_line=i,
            end_line=i,
        )
    for i in range(5):
        g.add_edge(f"n{i}", f"n{i + 1}", kind="call", confidence="resolved", line_number=i)
    frozen = nx.freeze(g)

    with patch.object(community_mod, "detect_communities", return_value=[desc]):
        first = await community_mod.rebuild_communities(
            str(repository.id),
            "",
            graph=frozen,
            summary_fn=_summary_fn,
        )
    assert first["summaries_generated"] == 1
    assert calls["n"] == 1
    n_after_first = calls["n"]

    with patch.object(community_mod, "detect_communities", return_value=[desc]):
        second = await community_mod.rebuild_communities(
            str(repository.id),
            "",
            graph=frozen,
            summary_fn=_summary_fn,
        )
    assert calls["n"] == n_after_first == 1
    assert second["summaries_generated"] == 0
    assert second["summaries_skipped"] >= 1
    row = await SymbolCommunity.objects.aget(repository=repository)
    assert row.summary
    assert "module gen-1" in row.summary


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_empty_summary_retries(repository) -> None:
    """既有 summary 为空时允许重试生成（仍计 LLM）。

    （Req: MOD-02, 决策: D-08）
    """
    members = [_member(i) for i in range(6)]
    desc = _community_desc(members)
    await SymbolCommunity.objects.acreate(
        repository=repository,
        branch_name="",
        community_key=desc["community_key"],
        algorithm="louvain",
        member_count=desc["member_count"],
        members=desc["members"],
        top_files=desc["top_files"],
        member_fingerprint=desc["member_fingerprint"],
        summary="",  # 空白 → 必须重试
        summary_model=None,
    )
    calls = {"n": 0}

    async def _summary_fn(ms, community):  # noqa: ANN001
        calls["n"] += 1
        return _fake_summary_json("retry")

    g = nx.freeze(nx.MultiDiGraph())
    with patch.object(community_mod, "detect_communities", return_value=[desc]):
        result = await community_mod.rebuild_communities(
            str(repository.id),
            "",
            graph=g,
            summary_fn=_summary_fn,
        )
    assert calls["n"] == 1
    assert result["summaries_generated"] == 1
    row = await SymbolCommunity.objects.aget(repository=repository)
    assert "module retry" in (row.summary or "")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_unclustered_or_small_skips_llm(repository) -> None:
    """unclustered 或规模过小社区不调 LLM。

    （Req: MOD-02/MOD-03, 决策: D-08）
    """
    small = _community_desc([_member(i) for i in range(3)], unclustered=False)
    unclustered = _community_desc(
        [_member(i, prefix="u", file_path="pkg/x.py") for i in range(2)],
        unclustered=True,
    )
    calls = {"n": 0}

    async def _summary_fn(ms, community):  # noqa: ANN001
        calls["n"] += 1
        return _fake_summary_json("nope")

    g = nx.freeze(nx.MultiDiGraph())
    with patch.object(
        community_mod,
        "detect_communities",
        return_value=[small, unclustered],
    ):
        result = await community_mod.rebuild_communities(
            str(repository.id),
            "",
            graph=g,
            summary_fn=_summary_fn,
        )
    assert calls["n"] == 0
    assert result["summaries_generated"] == 0
    assert await SymbolCommunity.objects.filter(repository=repository).acount() == 2


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
