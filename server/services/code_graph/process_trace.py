"""执行流正向 BFS + ``ProcessTrace`` 全删全建（Phase 126 / EXEC-01 / D-02..D-05）。

落点纪律
========
取图必须经 ``services.code_graph.get_graph_service`` —— ⛔ 不直连 ``loader`` /
``cache``，⛔ 不进 ``repo_router_v2``。本模块持 ORM 写入（对齐 ``community.py``）。

BFS 硬闸（D-02）
===============
``MAX_DEPTH=10`` / ``MAX_BRANCHING=4`` / ``MIN_STEPS=3`` / ``MIN_CONF=0.5``；
环显式 ``cycle``；async 词表末端 ``boundary: async_dispatch`` 且不跨越。
"""

from __future__ import annotations

import re
import time
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any

import networkx as nx
import structlog
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction

from common.logging import redact_secrets_in_text
from services.code_graph import EdgeConfidence, confidence_score
from services.exclusion import normalize_rel_path

logger = structlog.get_logger(__name__)

MAX_DEPTH = 10
MAX_BRANCHING = 4
MIN_STEPS = 3
MIN_CONF = 0.5
# 路径预算：去掉全局首访后靠预算抑扇出（WR-01）；环仍只靠 path_ids。
MAX_PATHS_PER_ENTRY = 64
MAX_FRONTIER_SIZE = 256

# Token / 后缀边界匹配，避免 delay_response / group_sender 等误截断（WR-04）。
_ASYNC_BOUNDARY_RE = re.compile(
    r"(?:^|_)(?:sync_to_async|apply_async|create_task|background_runner|group_send)(?:$|_)"
    r"|(?:^|\.)(?:delay|defer)$",
    re.IGNORECASE,
)

# 单行 JSON 主干截断（T-126-04）
MAX_STEPS_STORED = 64

StepDict = dict[str, Any]
PathDict = dict[str, Any]


def _edge_score(attrs: Mapping[str, Any]) -> float:
    """边置信度数值；与 impact 同纪律（cross_repo 用 match_confidence 原值）。"""
    confidence = EdgeConfidence(attrs["confidence"])
    if confidence is EdgeConfidence.CROSS_REPO:
        return confidence_score(confidence, match_confidence=attrs["match_confidence"])
    return confidence_score(confidence)


def _normalize_url_path(url_path: str) -> str:
    p = (url_path or "").strip() or "/"
    if p != "/" and p.endswith("/"):
        p = p.rstrip("/")
    return p


def make_process_key(http_method: str, url_path: str) -> str:
    """稳定键 ``{METHOD}:{normalized_path}``（RESEARCH discretionary）。"""
    method = (http_method or "GET").strip().upper() or "GET"
    return f"{method}:{_normalize_url_path(url_path)}"


def make_process_name(http_method: str, url_path: str) -> str:
    method = (http_method or "GET").strip().upper() or "GET"
    path = (url_path or "").strip() or "/"
    return f"{method} {path}"


def is_async_boundary_name(name: str) -> bool:
    """识别 async 派发边界名；短词 ``delay``/``defer`` 仅精确或 ``.delay`` 后缀。"""
    return bool(_ASYNC_BOUNDARY_RE.search(name or ""))


def max_processes_for_symbol_count(symbol_count: int) -> int:
    """``max(MIN, min(CAP, symbol_count // 10))``。"""
    mn = int(getattr(settings, "CODE_GRAPH_PROCESS_MIN", 20))
    cap = int(getattr(settings, "CODE_GRAPH_PROCESS_MAX_CAP", 300))
    return max(mn, min(cap, max(0, int(symbol_count)) // 10))


def _best_edge_attrs(
    graph: nx.MultiDiGraph, src: str, dst: str
) -> tuple[float, Mapping[str, Any]] | None:
    """同一对节点多档边取最高分；低于 ``MIN_CONF`` 返回 None。"""
    best: tuple[float, Mapping[str, Any]] | None = None
    try:
        edge_data = graph[src][dst]
    except KeyError:
        return None
    for attrs in edge_data.values():
        try:
            score = _edge_score(attrs)
        except (KeyError, ValueError):
            continue
        if score < MIN_CONF:
            continue
        if best is None or score > best[0]:
            best = (score, attrs)
    return best


def _step_from_node(
    graph: nx.MultiDiGraph,
    node_id: str,
    *,
    depth: int,
    community_key: str | None = None,
    boundary: str | None = None,
) -> StepDict:
    attrs = graph.nodes[node_id] if node_id in graph else {}
    step: StepDict = {
        "symbol_id": str(node_id),
        "name": str(attrs.get("name") or node_id),
        "file_path": str(attrs.get("file_path") or ""),
        "line": int(attrs.get("start_line") or 0) or None,
        "depth": depth,
    }
    if community_key:
        step["community_key"] = community_key
    if boundary:
        step["boundary"] = boundary
    return step


def collect_process_paths(
    graph: nx.MultiDiGraph,
    entry_id: str,
    *,
    max_depth: int = MAX_DEPTH,
    max_branching: int = MAX_BRANCHING,
    min_steps: int = MIN_STEPS,
    min_conf: float = MIN_CONF,
) -> list[PathDict]:
    """从 ``entry_id`` 正向 BFS 收集主干路径（纯函数，可注入合成图）。

    返回 ``[{steps, flags}, ...]``；已做 entry→terminal 最长保留 + 子串去重；
    短于 ``min_steps`` 的不返回。⛔ 不用 ``nx.bfs_layers``。
    """
    _ = min_conf  # 过滤在 _best_edge_attrs；保留形参对齐契约
    if entry_id not in graph:
        return []

    raw: list[PathDict] = []
    # BFS 状态：node, path_ids(tuple), steps(tuple of dicts frozen via tuple of items)
    frontier: deque[tuple[str, tuple[str, ...], tuple[StepDict, ...], dict[str, Any]]] = (
        deque()
    )
    entry_step = _step_from_node(graph, entry_id, depth=0)
    frontier.append((entry_id, (entry_id,), (entry_step,), {}))
    # 环只用 path_ids；不再用全局首访，否则 diamond 会丢掉交替终点（WR-01）。
    budget_exhausted = False

    while frontier:
        if len(raw) >= MAX_PATHS_PER_ENTRY:
            budget_exhausted = True
            break

        node, path_ids, steps, flags = frontier.popleft()
        depth = len(steps) - 1

        # 已达深度硬闸 → 收束为终端
        if depth >= max_depth:
            flags = {**flags, "truncated": True}
            if len(steps) >= min_steps:
                raw.append({"steps": list(steps), "flags": flags})
            continue

        # 收集合格后继，按边分降序，截断 branching
        candidates: list[tuple[str, float, Mapping[str, Any]]] = []
        for succ in graph.successors(node):
            best = _best_edge_attrs(graph, node, succ)
            if best is None:
                continue
            candidates.append((succ, best[0], best[1]))
        candidates.sort(key=lambda t: (-t[1], str(t[0])))
        if len(candidates) > max_branching:
            candidates = candidates[:max_branching]
            flags = {**flags, "truncated": True}

        if not candidates:
            if len(steps) >= min_steps:
                raw.append({"steps": list(steps), "flags": dict(flags)})
            continue

        expanded = False
        for succ, _score, _attrs in candidates:
            if len(raw) >= MAX_PATHS_PER_ENTRY:
                budget_exhausted = True
                break

            succ_name = str(graph.nodes[succ].get("name") or succ)

            # 环：在路径内重访 → 标注并收束，不静默丢弃
            if succ in path_ids:
                cycle_step = _step_from_node(graph, succ, depth=depth + 1)
                cycle_steps = list(steps) + [cycle_step]
                cycle_flags = {**flags, "cycle": True}
                if len(cycle_steps) >= min_steps:
                    raw.append({"steps": cycle_steps, "flags": cycle_flags})
                expanded = True
                continue

            # async 边界：纳入末端但不跨越
            if is_async_boundary_name(succ_name):
                bound_step = _step_from_node(
                    graph,
                    succ,
                    depth=depth + 1,
                    boundary="async_dispatch",
                )
                bound_steps = list(steps) + [bound_step]
                bound_flags = {**flags, "boundary": "async_dispatch"}
                if len(bound_steps) >= min_steps:
                    raw.append({"steps": bound_steps, "flags": bound_flags})
                expanded = True
                continue

            if len(frontier) >= MAX_FRONTIER_SIZE:
                flags = {**flags, "truncated": True}
                budget_exhausted = True
                break

            next_step = _step_from_node(graph, succ, depth=depth + 1)
            frontier.append(
                (
                    succ,
                    path_ids + (succ,),
                    steps + (next_step,),
                    dict(flags),
                )
            )
            expanded = True

        # 无后继可扩且当前路径已够长 → 作为终端保留
        if not expanded and len(steps) >= min_steps:
            raw.append({"steps": list(steps), "flags": dict(flags)})

        if budget_exhausted:
            break

    if budget_exhausted and raw:
        # 预算截断时给已收路径打 truncated，便于下游 degradation 感知
        for path in raw:
            path["flags"] = {**dict(path.get("flags") or {}), "truncated": True}

    return _dedupe_paths(raw)


def _path_signature(steps: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(str(s.get("symbol_id") or s.get("name") or "") for s in steps)


def _is_subsequence(short: Sequence[str], long: Sequence[str]) -> bool:
    """``short`` 是否为 ``long`` 的（可非连续）子序列；用于子串去重。"""
    if len(short) > len(long):
        return False
    it = iter(long)
    return all(x in it for x in short)


def _dedupe_paths(paths: Sequence[PathDict]) -> list[PathDict]:
    """同 entry→terminal 留最长；短路径若为长路径子串则删。"""
    if not paths:
        return []
    # 按 (entry, terminal) 分组留最长
    best_by_ends: dict[tuple[str, str], PathDict] = {}
    for p in paths:
        steps = p["steps"]
        if not steps:
            continue
        key = (
            str(steps[0].get("symbol_id") or ""),
            str(steps[-1].get("symbol_id") or ""),
        )
        prev = best_by_ends.get(key)
        if prev is None or len(steps) > len(prev["steps"]):
            best_by_ends[key] = p

    kept = list(best_by_ends.values())
    # 子串去重：若 A 的 id 序列是 B 的子序列且更短，丢 A
    sigs = [(p, _path_signature(p["steps"])) for p in kept]
    drop: set[int] = set()
    for i, (pi, si) in enumerate(sigs):
        for j, (pj, sj) in enumerate(sigs):
            if i == j or len(si) >= len(sj):
                continue
            if _is_subsequence(si, sj):
                drop.add(i)
                break
    return [p for i, (p, _) in enumerate(sigs) if i not in drop]


def classify_community_class(
    steps: Sequence[Mapping[str, Any]],
    symbol_to_community: Mapping[str, str],
) -> tuple[str, dict[str, Any]]:
    """路径成员对账社区软引用 → intra / cross / unknown（D-05）。

    返回 ``(community_class, degradation)``；无法对账时 class 为空串且
    ``degradation.community_class_unknown=True``，⛔ 不编造。
    """
    keys: set[str] = set()
    resolved = 0
    for step in steps:
        sid = str(step.get("symbol_id") or "").strip()
        if not sid:
            continue
        ck = symbol_to_community.get(sid)
        if ck:
            keys.add(str(ck))
            resolved += 1

    degradation: dict[str, Any] = {}
    if not keys:
        degradation["community_class_unknown"] = True
        return "", degradation
    if len(keys) == 1:
        return "intra_community", degradation
    return "cross_community", degradation


def _resolve_handler_node(
    graph: nx.MultiDiGraph,
    *,
    file_path: str,
    handler_name: str,
) -> str | None:
    """``(归一 file_path, name)`` → 图节点 id；歧义/缺失返回 None（不造虚拟节点）。"""
    if not file_path or not handler_name:
        return None
    target_path = normalize_rel_path(file_path)
    target_name = handler_name
    hits: list[str] = []
    for nid, attrs in graph.nodes(data=True):
        name = str(attrs.get("name") or "")
        if name != target_name:
            continue
        fp = str(attrs.get("file_path") or "")
        if normalize_rel_path(fp) == target_path:
            hits.append(str(nid))
    if len(hits) == 1:
        return hits[0]
    return None


def _load_symbol_community_lookup(
    repository_id: str, branch_name: str
) -> dict[str, str]:
    from codegraph.models import SymbolCommunity

    lookup: dict[str, str] = {}
    rows = SymbolCommunity.objects.filter(
        repository_id=repository_id,
        branch_name=branch_name,
    ).values_list("community_key", "members")
    for community_key, members in rows:
        for m in members or []:
            if not isinstance(m, Mapping):
                continue
            sid = str(m.get("symbol_id") or "").strip()
            if sid and sid not in lookup:
                lookup[sid] = str(community_key)
    return lookup


def _resolve_built_at_sha(repository_id: str) -> str:
    try:
        from repositories.models import Repository

        row = (
            Repository.objects.filter(id=repository_id)
            .values_list("last_indexed_commit_sha", flat=True)
            .first()
        )
        return str(row or "")
    except Exception:  # noqa: BLE001 — 水位失败不阻断落库
        return ""


def _load_endpoints(repository_id: str, branch_name: str) -> list[dict[str, Any]]:
    from codegraph.models import Endpoint

    qs = Endpoint.objects.filter(
        repository_id=repository_id,
        branch_name=branch_name,
    ).values(
        "http_method",
        "url_path",
        "handler_name",
        "file_path",
        "line_number",
    )
    return list(qs)


def _persist_processes(
    *,
    repository_id: str,
    branch_name: str,
    rows: Sequence[Mapping[str, Any]],
    built_at_sha: str,
) -> int:
    from codegraph.models import ProcessTrace
    from repositories.models import Repository

    repo = Repository.objects.get(id=repository_id)
    objects: list[ProcessTrace] = []
    for r in rows:
        steps = list(r.get("steps") or [])[:MAX_STEPS_STORED]
        truncated = bool((r.get("flags") or {}).get("truncated")) or (
            len(list(r.get("steps") or [])) > MAX_STEPS_STORED
        )
        flags = dict(r.get("flags") or {})
        if truncated:
            flags["truncated"] = True
        objects.append(
            ProcessTrace(
                repository=repo,
                branch_name=branch_name,
                process_key=str(r["process_key"]),
                name=str(r["name"]),
                entry_endpoint=dict(r.get("entry_endpoint") or {}),
                steps=steps,
                community_class=str(r.get("community_class") or ""),
                step_count=int(r.get("step_count") or len(steps)),
                flags=flags,
                built_at_sha=built_at_sha,
            )
        )
    with transaction.atomic():
        ProcessTrace.objects.filter(repository=repo, branch_name=branch_name).delete()
        if objects:
            ProcessTrace.objects.bulk_create(objects)
    return len(objects)


def _build_process_rows(
    graph: nx.MultiDiGraph,
    endpoints: Sequence[Mapping[str, Any]],
    *,
    symbol_to_community: Mapping[str, str],
    max_processes: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Endpoint → BFS → 分类；返回 (rows, degradation_summary)。

    先收集全部可解析候选，再按 ``cross_community`` 优先、``step_count`` 降序截断
    （WR-06）——避免按 Endpoint 迭代顺序任意丢弃跨社区 / 更长流。
    """
    degradation: dict[str, Any] = {
        "unresolved_endpoints": 0,
        "community_class_unknown": 0,
    }
    candidates: list[dict[str, Any]] = []
    used_keys: set[str] = set()

    for ep in endpoints:
        method = str(ep.get("http_method") or "GET")
        url_path = str(ep.get("url_path") or "/")
        handler_name = str(ep.get("handler_name") or "")
        file_path = str(ep.get("file_path") or "")
        entry_snapshot = {
            "http_method": method,
            "url_path": url_path,
            "handler_name": handler_name,
            "file_path": file_path,
            "line_number": int(ep.get("line_number") or 0),
        }
        node_id = _resolve_handler_node(
            graph, file_path=file_path, handler_name=handler_name
        )
        if node_id is None:
            degradation["unresolved_endpoints"] = (
                int(degradation["unresolved_endpoints"]) + 1
            )
            continue

        paths = collect_process_paths(graph, node_id)
        process_key = make_process_key(method, url_path)
        name = make_process_name(method, url_path)

        # 同 endpoint 多路径：取最长一条作为主干摘要（D-04）
        if not paths:
            continue
        best = max(paths, key=lambda p: len(p["steps"]))
        steps = list(best["steps"])
        # 回填 community_key 到 step
        for step in steps:
            sid = str(step.get("symbol_id") or "")
            ck = symbol_to_community.get(sid)
            if ck:
                step["community_key"] = ck
        community_class, class_deg = classify_community_class(steps, symbol_to_community)
        if class_deg.get("community_class_unknown"):
            degradation["community_class_unknown"] = (
                int(degradation["community_class_unknown"]) + 1
            )

        row = {
            "process_key": process_key,
            "name": name,
            "entry_endpoint": entry_snapshot,
            "steps": steps,
            "step_count": len(steps),
            "community_class": community_class,
            "flags": dict(best.get("flags") or {}),
        }
        if process_key in used_keys:
            # 同 key 冲突：保留更长
            existing_idx = next(
                i for i, r in enumerate(candidates) if r["process_key"] == process_key
            )
            if len(steps) <= len(candidates[existing_idx]["steps"]):
                continue
            candidates.pop(existing_idx)
        used_keys.add(process_key)
        candidates.append(row)

    candidates.sort(
        key=lambda r: (
            0 if r.get("community_class") == "cross_community" else 1,
            -int(r.get("step_count") or 0),
            str(r.get("process_key") or ""),
        )
    )
    if len(candidates) > max_processes:
        degradation["truncated_by_max_processes"] = True
    rows = candidates[: max(0, int(max_processes))]
    return rows, degradation


async def rebuild_processes(
    repository_id: str,
    branch_name: str = "",
    *,
    graph: Any | None = None,
) -> dict[str, Any]:
    """取图 → Endpoint 入口 BFS → 社区分类 → 全删全建 ``ProcessTrace``。

    ``graph`` 可注入（测试）；缺省经 ``get_graph_service().get_graph``。
    """
    from services.code_graph import get_graph_service

    started = time.monotonic()
    branch = branch_name or ""

    try:
        logger.info(
            "code_graph_process_rebuild_started",
            category="sampling",
            component="code_graph",
            repository_id=str(repository_id),
            branch_name=branch,
        )
    except Exception:  # noqa: BLE001
        pass

    try:
        code_graph = graph
        if code_graph is None:
            code_graph = await get_graph_service().get_graph(
                str(repository_id),
                branch=branch,
            )
        # NetworkX 图自身带 ``.graph`` 属性字典——不能用 getattr 兜底，否则会把
        # 注入的 MultiDiGraph 误当成空 dict。
        if isinstance(
            code_graph, (nx.Graph, nx.DiGraph, nx.MultiGraph, nx.MultiDiGraph)
        ):
            nx_graph = code_graph
        else:
            nx_graph = getattr(code_graph, "graph", code_graph)
        if not isinstance(nx_graph, nx.MultiDiGraph):
            # 允许测试注入普通 DiGraph：升成 MultiDiGraph 视图
            if isinstance(nx_graph, nx.Graph):
                multi = nx.MultiDiGraph()
                multi.add_nodes_from(nx_graph.nodes(data=True))
                for u, v, data in nx_graph.edges(data=True):
                    multi.add_edge(u, v, **data)
                nx_graph = multi
            else:
                raise TypeError("process_rebuild_requires_multidigraph")

        endpoints = await sync_to_async(_load_endpoints)(str(repository_id), branch)
        symbol_to_community = await sync_to_async(_load_symbol_community_lookup)(
            str(repository_id),
            branch,
        )
        max_proc = max_processes_for_symbol_count(nx_graph.number_of_nodes())
        rows, degradation = await sync_to_async(_build_process_rows)(
            nx_graph,
            endpoints,
            symbol_to_community=symbol_to_community,
            max_processes=max_proc,
        )
        built_at_sha = await sync_to_async(_resolve_built_at_sha)(str(repository_id))
        written = await sync_to_async(_persist_processes)(
            repository_id=str(repository_id),
            branch_name=branch,
            rows=rows,
            built_at_sha=built_at_sha,
        )

        duration_ms = round((time.monotonic() - started) * 1000, 2)
        result = {
            "status": "ok",
            "processes_total": len(rows),
            "processes_written": written,
            "built_at_sha": built_at_sha,
            "degradation": degradation,
            "duration_ms": duration_ms,
        }
        try:
            logger.info(
                "code_graph_process_rebuild_completed",
                category="sampling",
                component="code_graph",
                repository_id=str(repository_id),
                branch_name=branch,
                processes_total=len(rows),
                processes_written=written,
                unresolved_endpoints=degradation.get("unresolved_endpoints"),
                duration_ms=duration_ms,
            )
        except Exception:  # noqa: BLE001
            pass
        return result
    except Exception as exc:
        try:
            logger.warning(
                "code_graph_process_rebuild_failed",
                category="sampling",
                component="code_graph",
                repository_id=str(repository_id),
                branch_name=branch,
                error=redact_secrets_in_text(str(exc)),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001
            pass
        raise


__all__ = [
    "MAX_BRANCHING",
    "MAX_DEPTH",
    "MIN_CONF",
    "MIN_STEPS",
    "classify_community_class",
    "collect_process_paths",
    "is_async_boundary_name",
    "make_process_key",
    "make_process_name",
    "max_processes_for_symbol_count",
    "rebuild_processes",
]
