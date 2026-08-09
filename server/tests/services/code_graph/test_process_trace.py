"""Process BFS / 社区分类验收（EXEC-01 / D-02 / D-05；T-126-04）。"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import networkx as nx
import pytest

from services.code_graph import process_trace as pt


def _node(
    nid: str,
    *,
    name: str | None = None,
    file_path: str = "app/views.py",
    start_line: int = 1,
) -> tuple[str, dict[str, Any]]:
    return nid, {
        "name": name or nid,
        "symbol_type": "FUNCTION",
        "file_path": file_path,
        "start_line": start_line,
        "end_line": start_line,
    }


def _chain_graph(names: list[str], *, conf: str = "resolved") -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    for i, n in enumerate(names):
        g.add_node(*_node(n, start_line=i + 1))
    for i in range(len(names) - 1):
        g.add_edge(names[i], names[i + 1], kind="call", confidence=conf, line_number=i + 1)
    return g


def test_bfs_respects_depth_branching_min_steps_conf() -> None:
    """硬闸 maxDepth=10 / maxBranching=4 / minSteps=3 / conf≥0.5。

    （Req: EXEC-01, 决策: D-02, 威胁: T-126-04）
    """
    assert pt.MAX_DEPTH == 10
    assert pt.MAX_BRANCHING == 4
    assert pt.MIN_STEPS == 3
    assert pt.MIN_CONF == 0.5

    # 深度：12 跳链，截断后 depth≤10，且最短不足 minSteps 的不出现
    deep = _chain_graph([f"d{i}" for i in range(13)])
    deep_paths = pt.collect_process_paths(deep, "d0")
    assert deep_paths
    for path in deep_paths:
        depths = [s["depth"] for s in path["steps"]]
        assert max(depths) <= pt.MAX_DEPTH
        assert len(path["steps"]) >= pt.MIN_STEPS

    # minSteps：仅 2 节点（1 边）不落库
    short = _chain_graph(["a", "b"])
    assert pt.collect_process_paths(short, "a") == []

    # conf：bare_name=0.3 边不走 → 无 ≥3 步路径
    low = _chain_graph(["e0", "e1", "e2", "e3"], conf="bare_name")
    assert pt.collect_process_paths(low, "e0") == []

    # branching：星型出口 >4，只扩前 4 个（按边分排序后截断）
    star = nx.MultiDiGraph()
    star.add_node(*_node("hub"))
    for i in range(6):
        leaf = f"leaf{i}"
        star.add_node(*_node(leaf))
        # 再挂一层使每条臂 ≥3 steps
        mid = f"mid{i}"
        star.add_node(*_node(mid))
        star.add_edge("hub", mid, kind="call", confidence="resolved", line_number=1)
        star.add_edge(mid, leaf, kind="call", confidence="resolved", line_number=2)
    paths = pt.collect_process_paths(star, "hub")
    terminals = {p["steps"][-1]["name"] for p in paths}
    assert len(terminals) <= pt.MAX_BRANCHING


def test_cycle_marked_not_silently_skipped() -> None:
    """环检测后显式标注，不得静默跳过。

    （Req: EXEC-01, 决策: D-02）
    """
    g = nx.MultiDiGraph()
    for n in ("h", "a", "b"):
        g.add_node(*_node(n))
    g.add_edge("h", "a", kind="call", confidence="resolved", line_number=1)
    g.add_edge("a", "b", kind="call", confidence="resolved", line_number=2)
    g.add_edge("b", "a", kind="call", confidence="resolved", line_number=3)  # cycle

    paths = pt.collect_process_paths(g, "h")
    assert paths, "cycle path must be kept, not dropped"
    assert any(p.get("flags", {}).get("cycle") is True for p in paths)


def test_async_dispatch_boundary_not_crossed() -> None:
    """async 派发边界标 boundary，v1 不跨过。

    （Req: EXEC-01, 决策: D-02）
    """
    g = nx.MultiDiGraph()
    g.add_node(*_node("entry"))
    g.add_node(*_node("svc"))
    g.add_node(*_node("apply_async_helper", name="apply_async"))
    g.add_node(*_node("worker_task"))
    g.add_edge("entry", "svc", kind="call", confidence="resolved", line_number=1)
    g.add_edge("svc", "apply_async_helper", kind="call", confidence="resolved", line_number=2)
    g.add_edge(
        "apply_async_helper",
        "worker_task",
        kind="call",
        confidence="resolved",
        line_number=3,
    )

    paths = pt.collect_process_paths(g, "entry")
    assert paths
    names = {s["name"] for p in paths for s in p["steps"]}
    assert "worker_task" not in names
    assert any(
        p.get("flags", {}).get("boundary") == "async_dispatch"
        or any(s.get("boundary") == "async_dispatch" for s in p["steps"])
        for p in paths
    )


def test_community_class_intra_cross_unknown() -> None:
    """intra / cross / community_class_unknown 降级，不编造社区。

    （Req: EXEC-01, 决策: D-05）
    """
    steps_intra = [
        {"symbol_id": "s1", "name": "a", "file_path": "a.py", "depth": 0},
        {"symbol_id": "s2", "name": "b", "file_path": "a.py", "depth": 1},
        {"symbol_id": "s3", "name": "c", "file_path": "a.py", "depth": 2},
    ]
    lookup_same = {"s1": "cA", "s2": "cA", "s3": "cA"}
    cls, deg = pt.classify_community_class(steps_intra, lookup_same)
    assert cls == "intra_community"
    assert not deg.get("community_class_unknown")

    steps_cross = [
        {"symbol_id": "s1", "name": "a", "file_path": "a.py", "depth": 0},
        {"symbol_id": "s2", "name": "b", "file_path": "b.py", "depth": 1},
        {"symbol_id": "s3", "name": "c", "file_path": "c.py", "depth": 2},
    ]
    lookup_cross = {"s1": "cA", "s2": "cB", "s3": "cB"}
    cls, deg = pt.classify_community_class(steps_cross, lookup_cross)
    assert cls == "cross_community"

    cls, deg = pt.classify_community_class(steps_intra, {})
    assert cls == ""
    assert deg.get("community_class_unknown") is True


def test_get_graph_only_no_loader_import() -> None:
    """静态：process_trace.py 不 import loader/cache；只经 get_graph_service。

    （Req: EXEC-01, 决策: D-03）
    """
    path = Path(pt.__file__).resolve()
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    assert "get_graph_service" in source

    forbidden: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            if mod in {
                "services.code_graph.loader",
                "services.code_graph.cache",
            } or mod.endswith(".loader") or mod.endswith(".cache"):
                forbidden.append(f"from {mod}")
            if "repo_router_v2" in mod:
                forbidden.append(f"from {mod}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if "loader" in alias.name or "cache" in alias.name:
                    # allow stdlib/other; only flag code_graph internals
                    if "code_graph" in alias.name:
                        forbidden.append(f"import {alias.name}")
                if "repo_router_v2" in alias.name:
                    forbidden.append(f"import {alias.name}")
    assert forbidden == [], f"forbidden imports: {forbidden}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_rebuild_processes_persists_and_filters(repository, monkeypatch) -> None:
    """rebuild 全删全建；短路径过滤；built_at_sha 对齐水位。

    （Req: EXEC-01, 决策: D-01/D-04）
    """
    from codegraph.models import Endpoint, ProcessTrace

    repository.last_indexed_commit_sha = "abc123deadbeef"
    await repository.asave(update_fields=["last_indexed_commit_sha"])

    await Endpoint.objects.acreate(
        repository=repository,
        branch_name="",
        http_method="GET",
        url_path="/api/items/",
        handler_name="list_items",
        view_type=Endpoint.ViewType.FUNCTION_VIEW,
        file_path="app/views.py",
        line_number=10,
    )
    # 无法解析 handler → unresolved，不造虚拟节点
    await Endpoint.objects.acreate(
        repository=repository,
        branch_name="",
        http_method="POST",
        url_path="/api/missing",
        handler_name="ghost",
        view_type=Endpoint.ViewType.FUNCTION_VIEW,
        file_path="missing.py",
        line_number=1,
    )

    g = nx.MultiDiGraph()
    g.add_node(
        *_node("h1", name="list_items", file_path="app/views.py", start_line=10)
    )
    g.add_node(*_node("s1", name="svc", file_path="app/svc.py", start_line=1))
    g.add_node(*_node("s2", name="repo", file_path="app/repo.py", start_line=1))
    g.add_edge("h1", "s1", kind="call", confidence="resolved", line_number=11)
    g.add_edge("s1", "s2", kind="call", confidence="resolved", line_number=2)

    class _CG:
        graph = g

    class _Svc:
        async def get_graph(self, *a, **k):
            return _CG()

    monkeypatch.setattr(
        "services.code_graph.get_graph_service",
        lambda: _Svc(),
    )

    result = await pt.rebuild_processes(str(repository.id), "")
    assert result["status"] == "ok"
    rows = [r async for r in ProcessTrace.objects.filter(repository=repository)]
    assert len(rows) == 1
    row = rows[0]
    assert row.process_key == "GET:/api/items"
    assert row.name == "GET /api/items/"
    assert row.step_count >= 3
    assert row.built_at_sha == "abc123deadbeef"
    assert row.entry_endpoint["http_method"] == "GET"
    # 第二次 rebuild 全删全建，仍 1 行
    await pt.rebuild_processes(str(repository.id), "", graph=g)
    assert await ProcessTrace.objects.filter(repository=repository).acount() == 1
