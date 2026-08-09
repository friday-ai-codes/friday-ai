"""符号图社区检测 + ``SymbolCommunity`` 全删全建落库（Phase 125 / MOD-01）。

落点纪律（D-12 / RESEARCH Pitfall 5）
====================================
本模块与 ``loader`` 同类：持 ORM 写入，**不进**包根 ``__all__`` barrel，也**不进**
``test_access._INTERNAL_SUBMODULES`` 黑名单。取图必须经
``services.code_graph.get_graph_service`` —— ⛔ 不直连 ``loader`` / ``cache``。

算法护栏（D-04）
================
冻结 ``MultiDiGraph`` → 投影新 ``nx.Graph``（sorted nodes/edges）→ 对 WCC
size≥``MIN_COMMUNITY_SIZE`` 跑 ``louvain_communities(..., seed=LOUVAIN_SEED)``；
过小分量归 ``unclustered:{top_dir}``，不发摘要（摘要接线在 125-03）。
"""

from __future__ import annotations

import hashlib
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

import networkx as nx
import structlog
from asgiref.sync import sync_to_async
from networkx.algorithms.community import louvain_communities

logger = structlog.get_logger(__name__)

LOUVAIN_SEED = 42
JACCARD_THRESHOLD = 0.8
MIN_COMMUNITY_SIZE = 5
# T-125-04：写入前截断，防 JSON 行膨胀 DoS。
MAX_MEMBERS_STORED = 500
MAX_TOP_FILES_STORED = 40

MemberDict = dict[str, Any]
SummaryFn = Callable[[Sequence[MemberDict], Mapping[str, Any]], Any]


def project_undirected(g: nx.MultiDiGraph | nx.Graph) -> nx.Graph:
    """把（可能冻结的）有向多重图投影为确定性无向简单图。

    ⛔ 不就地改 ``g``（缓存图可能已 ``freeze``）。
    """
    u = nx.Graph()
    u.add_nodes_from(sorted(g.nodes()))
    edges = {(a, b) if a <= b else (b, a) for a, b in g.edges()}
    u.add_edges_from(sorted(edges))
    return u


def _member_stable_key(member: Mapping[str, Any]) -> str:
    sid = str(member.get("symbol_id") or "").strip()
    if sid:
        return sid
    file_path = str(member.get("file_path") or "")
    name = str(member.get("name") or "")
    symbol_type = str(member.get("symbol_type") or "")
    return f"{file_path}:{name}:{symbol_type}"


def member_fingerprint(members: Iterable[Mapping[str, Any]]) -> str:
    """``sha256`` hex 截断 32；键序无关（D-05）。"""
    keys = sorted({_member_stable_key(m) for m in members if _member_stable_key(m)})
    digest = hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()
    return digest[:32]


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    """集合 Jaccard；空对空视为 1.0。"""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def match_communities_greedy(
    new_communities: Sequence[Mapping[str, Any]],
    old_communities: Sequence[Mapping[str, Any]],
    *,
    threshold: float = JACCARD_THRESHOLD,
) -> list[tuple[int, int, float]]:
    """一对一贪心最大 Jaccard 对账（D-06）。

    返回 ``[(new_idx, old_idx, score), ...]``，仅含 ≥ threshold 的配对。
    """
    pairs: list[tuple[float, int, int]] = []
    for ni, nc in enumerate(new_communities):
        nkeys = set(nc.get("member_keys") or [])
        for oi, oc in enumerate(old_communities):
            okays = set(oc.get("member_keys") or [])
            score = jaccard(nkeys, okays)
            if score >= threshold:
                pairs.append((score, ni, oi))
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))
    used_new: set[int] = set()
    used_old: set[int] = set()
    matched: list[tuple[int, int, float]] = []
    for score, ni, oi in pairs:
        if ni in used_new or oi in used_old:
            continue
        used_new.add(ni)
        used_old.add(oi)
        matched.append((ni, oi, score))
    return matched


def _top_dir(file_path: str) -> str:
    parts = PurePosixPath(file_path.replace("\\", "/")).parts
    if not parts:
        return "unknown"
    return parts[0] or "unknown"


def _node_member(
    graph: nx.MultiDiGraph,
    node_id: str,
    *,
    chunk_evidence: Mapping[str, Any] | None = None,
) -> MemberDict:
    data = graph.nodes[node_id]
    member: MemberDict = {
        "symbol_id": str(node_id),
        "name": str(data.get("name") or ""),
        "file_path": str(data.get("file_path") or ""),
        "symbol_type": str(data.get("symbol_type") or ""),
    }
    if chunk_evidence is not None:
        evidences = chunk_evidence.get(str(node_id)) or ()
        if evidences:
            first = evidences[0]
            chunk_id = getattr(first, "source_chunk_id", None) or None
            if chunk_id:
                member["chunk_id"] = str(chunk_id)
    return member


def detect_communities(
    graph: nx.MultiDiGraph,
    *,
    chunk_evidence: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """跑 Louvain / unclustered 归桶，返回待落库社区描述（尚未写 ORM）。"""
    undirected = project_undirected(graph)
    communities: list[dict[str, Any]] = []

    for component_nodes in nx.connected_components(undirected):
        nodes = sorted(component_nodes)
        if len(nodes) < MIN_COMMUNITY_SIZE:
            # 过小 WCC → 按 top_dir 归 unclustered（D-04 Discretion）。
            by_dir: dict[str, list[str]] = defaultdict(list)
            for nid in nodes:
                fp = str(graph.nodes[nid].get("file_path") or "")
                by_dir[_top_dir(fp)].append(nid)
            for top_dir, dir_nodes in sorted(by_dir.items()):
                members = [_node_member(graph, nid, chunk_evidence=chunk_evidence) for nid in sorted(dir_nodes)]
                fp = member_fingerprint(members)
                communities.append(
                    {
                        "community_key": f"unclustered:{top_dir}:{fp[:8]}",
                        "algorithm": "louvain",
                        "unclustered": True,
                        "members": members,
                        "member_keys": [_member_stable_key(m) for m in members],
                        "member_fingerprint": fp,
                        "member_count": len(members),
                        "top_files": _top_files(members),
                    }
                )
            continue

        subgraph = undirected.subgraph(nodes).copy()
        # 再保证节点序稳定（子图 copy 后节点序可能变）。
        ordered = nx.Graph()
        ordered.add_nodes_from(sorted(subgraph.nodes()))
        ordered.add_edges_from(sorted(subgraph.edges()))
        partitions = louvain_communities(ordered, seed=LOUVAIN_SEED)
        for part in partitions:
            part_nodes = sorted(part)
            members = [
                _node_member(graph, nid, chunk_evidence=chunk_evidence) for nid in part_nodes
            ]
            fp = member_fingerprint(members)
            communities.append(
                {
                    "community_key": fp[:16],
                    "algorithm": "louvain",
                    "unclustered": False,
                    "members": members,
                    "member_keys": [_member_stable_key(m) for m in members],
                    "member_fingerprint": fp,
                    "member_count": len(members),
                    "top_files": _top_files(members),
                }
            )

    # 稳定输出序：指纹 → key。
    communities.sort(key=lambda c: (c["member_fingerprint"], c["community_key"]))
    return communities


def _top_files(members: Sequence[Mapping[str, Any]]) -> list[str]:
    counts = Counter(str(m.get("file_path") or "") for m in members if m.get("file_path"))
    ranked = [fp for fp, _ in counts.most_common(MAX_TOP_FILES_STORED) if fp]
    return ranked


def _truncate_members(members: Sequence[MemberDict]) -> list[MemberDict]:
    if len(members) <= MAX_MEMBERS_STORED:
        return list(members)
    # 稳定截断：按 symbol_id 排序后取前 N。
    ordered = sorted(members, key=lambda m: str(m.get("symbol_id") or ""))
    return ordered[:MAX_MEMBERS_STORED]


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


def _persist_communities(
    *,
    repository_id: str,
    branch_name: str,
    communities: Sequence[Mapping[str, Any]],
    built_at_sha: str,
) -> int:
    from codegraph.models import SymbolCommunity
    from repositories.models import Repository

    repo = Repository.objects.get(id=repository_id)
    SymbolCommunity.objects.filter(repository=repo, branch_name=branch_name).delete()
    rows = [
        SymbolCommunity(
            repository=repo,
            branch_name=branch_name,
            community_key=str(c["community_key"])[:64],
            algorithm=str(c.get("algorithm") or "louvain"),
            member_count=int(c.get("member_count") or 0),
            members=_truncate_members(list(c.get("members") or [])),
            top_files=list(c.get("top_files") or [])[:MAX_TOP_FILES_STORED],
            member_fingerprint=str(c.get("member_fingerprint") or ""),
            summary=c.get("summary"),
            summary_model=c.get("summary_model"),
            summary_generated_at=c.get("summary_generated_at"),
            built_at_sha=built_at_sha,
        )
        for c in communities
    ]
    if rows:
        SymbolCommunity.objects.bulk_create(rows)
    return len(rows)


async def rebuild_communities(
    repository_id: str,
    branch_name: str = "",
    *,
    graph: Any | None = None,
    summary_fn: SummaryFn | None = None,
) -> dict[str, Any]:
    """取图 → Louvain → 指纹 →（可选 summary_fn）→ 按仓/分支全删全建。

    ``graph`` 可注入（测试）；缺省经 ``get_graph_service().get_graph``。
    本 plan（125-02）默认 ``summary_fn=None``，摘要接线留给 125-03。
    """
    from services.code_graph import get_graph_service

    started = time.monotonic()
    branch = branch_name or ""
    summaries_skipped = 0
    summaries_generated = 0

    try:
        logger.info(
            "community_rebuild_started",
            category="caller",
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
        nx_graph = getattr(code_graph, "graph", code_graph)
        chunk_evidence = getattr(code_graph, "chunk_evidence", None)

        communities = await sync_to_async(detect_communities)(
            nx_graph,
            chunk_evidence=chunk_evidence,
        )

        if summary_fn is not None:
            for community in communities:
                if community.get("unclustered") or community["member_count"] < MIN_COMMUNITY_SIZE:
                    summaries_skipped += 1
                    continue
                try:
                    summary = summary_fn(community["members"], community)
                except Exception:  # noqa: BLE001 — 单社区失败不阻断
                    summary = None
                if summary:
                    community["summary"] = summary
                    summaries_generated += 1
                else:
                    summaries_skipped += 1

        built_at_sha = await sync_to_async(_resolve_built_at_sha)(str(repository_id))
        written = await sync_to_async(_persist_communities)(
            repository_id=str(repository_id),
            branch_name=branch,
            communities=communities,
            built_at_sha=built_at_sha,
        )

        duration_ms = round((time.monotonic() - started) * 1000, 2)
        try:
            logger.info(
                "community_rebuild_completed",
                category="caller",
                component="code_graph",
                repository_id=str(repository_id),
                branch_name=branch,
                communities_total=len(communities),
                communities_written=written,
                summaries_skipped=summaries_skipped,
                summaries_generated=summaries_generated,
                duration_ms=duration_ms,
            )
            logger.debug(
                "community_rebuild_counts",
                category="sampling",
                component="code_graph",
                repository_id=str(repository_id),
                communities_total=len(communities),
                summaries_skipped=summaries_skipped,
                summaries_generated=summaries_generated,
            )
        except Exception:  # noqa: BLE001
            pass

        return {
            "status": "ok",
            "repository_id": str(repository_id),
            "branch_name": branch,
            "communities_total": len(communities),
            "communities_written": written,
            "summaries_skipped": summaries_skipped,
            "summaries_generated": summaries_generated,
            "duration_ms": duration_ms,
        }
    except Exception as exc:
        try:
            from common.logging import redact_secrets_in_text

            logger.warning(
                "community_rebuild_failed",
                category="caller",
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
    "JACCARD_THRESHOLD",
    "LOUVAIN_SEED",
    "MAX_MEMBERS_STORED",
    "MAX_TOP_FILES_STORED",
    "MIN_COMMUNITY_SIZE",
    "detect_communities",
    "jaccard",
    "match_communities_greedy",
    "member_fingerprint",
    "project_undirected",
    "rebuild_communities",
]
