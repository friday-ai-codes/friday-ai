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
import inspect
import json
import time
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

import networkx as nx
import structlog
from asgiref.sync import sync_to_async
from django.db import transaction
from networkx.algorithms.community import louvain_communities

logger = structlog.get_logger(__name__)

LOUVAIN_SEED = 42
JACCARD_THRESHOLD = 0.8
MIN_COMMUNITY_SIZE = 5
# T-125-04：写入前截断，防 JSON 行膨胀 DoS。
MAX_MEMBERS_STORED = 500
MAX_TOP_FILES_STORED = 40
# Jaccard 对账用完整 key 列表；与展示用 members 截断分离（WR-02）。
MAX_MEMBER_KEYS_STORED = 50_000

MemberDict = dict[str, Any]
SummaryFn = Callable[
    [Sequence[MemberDict], Mapping[str, Any]],
    Any | Awaitable[Any],
]


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


def _unique_community_key(base: str, used: set[str]) -> str:
    """保证 ``(repository, branch, community_key)`` 唯一，碰撞时加 ``~N`` 后缀。"""
    key = (base or "community")[:64]
    if key not in used:
        used.add(key)
        return key
    for i in range(1, 10_000):
        suffix = f"~{i}"
        candidate = f"{key[: max(0, 64 - len(suffix))]}{suffix}"
        if candidate not in used:
            used.add(candidate)
            return candidate
    raise RuntimeError("community_key_collision_exhausted")


def _persist_member_keys(keys: Sequence[str] | None) -> list[str]:
    """落库用完整稳定键列表（截断上限远高于 members 展示截断）。"""
    ordered = sorted({str(k) for k in (keys or []) if str(k)})
    if len(ordered) > MAX_MEMBER_KEYS_STORED:
        return ordered[:MAX_MEMBER_KEYS_STORED]
    return ordered


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


def _load_old_communities(repository_id: str, branch_name: str) -> list[dict[str, Any]]:
    """读旧 ``SymbolCommunity`` 行，供指纹 / Jaccard 对账（D-06）。"""
    from codegraph.models import SymbolCommunity

    rows = list(
        SymbolCommunity.objects.filter(
            repository_id=repository_id,
            branch_name=branch_name,
        ).values(
            "community_key",
            "member_fingerprint",
            "members",
            "member_keys",
            "summary",
            "summary_model",
            "summary_generated_at",
        )
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        members = list(row.get("members") or [])
        stored_keys = [
            str(k) for k in (row.get("member_keys") or []) if str(k)
        ]
        # 新行用持久化 member_keys；旧行回退从 truncated members 重建。
        member_keys = stored_keys or [
            _member_stable_key(m) for m in members if isinstance(m, Mapping)
        ]
        out.append(
            {
                "community_key": str(row.get("community_key") or ""),
                "member_fingerprint": str(row.get("member_fingerprint") or ""),
                "members": members,
                "member_keys": member_keys,
                "summary": row.get("summary"),
                "summary_model": row.get("summary_model"),
                "summary_generated_at": row.get("summary_generated_at"),
            }
        )
    return out


def _summary_nonempty(summary: Any) -> bool:
    return bool(str(summary or "").strip())


def _reuse_summary_fields(community: dict[str, Any], old: Mapping[str, Any]) -> None:
    community["summary"] = old.get("summary")
    community["summary_model"] = old.get("summary_model")
    community["summary_generated_at"] = old.get("summary_generated_at")
    old_key = str(old.get("community_key") or "").strip()
    if old_key:
        community["community_key"] = old_key


def _normalize_summary_payload(result: Any) -> str | None:
    if result is None:
        return None
    if isinstance(result, str):
        text = result.strip()
        return text or None
    if isinstance(result, Mapping):
        try:
            return json.dumps(dict(result), ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            return None
    text = str(result).strip()
    return text or None


async def _call_summary_fn(
    summary_fn: SummaryFn,
    members: Sequence[MemberDict],
    community: Mapping[str, Any],
) -> str | None:
    try:
        result = summary_fn(members, community)
        if inspect.isawaitable(result):
            result = await result
        return _normalize_summary_payload(result)
    except Exception:  # noqa: BLE001 — 单社区失败不阻断
        return None


async def _apply_summary_reconcile(
    communities: list[dict[str, Any]],
    old_communities: Sequence[Mapping[str, Any]],
    *,
    summary_fn: SummaryFn | None,
) -> tuple[int, int]:
    """指纹 short-circuit → Jaccard 贪心 → 串行 LLM（D-06/D-07/D-08/D-11）。"""
    summaries_skipped = 0
    summaries_generated = 0

    old_by_fp: dict[str, dict[str, Any]] = {}
    for old in old_communities:
        fp = str(old.get("member_fingerprint") or "")
        if fp and fp not in old_by_fp:
            old_by_fp[fp] = dict(old)

    used_old_fps: set[str] = set()
    used_old_keys: set[str] = set()
    need_llm: list[dict[str, Any]] = []
    pending_jaccard: list[dict[str, Any]] = []

    for community in communities:
        if community.get("unclustered") or int(community.get("member_count") or 0) < MIN_COMMUNITY_SIZE:
            summaries_skipped += 1
            continue

        fp = str(community.get("member_fingerprint") or "")
        old_exact = old_by_fp.get(fp) if fp else None
        if old_exact is not None:
            used_old_fps.add(fp)
            used_old_keys.add(str(old_exact.get("community_key") or ""))
            if _summary_nonempty(old_exact.get("summary")):
                _reuse_summary_fields(community, old_exact)
                summaries_skipped += 1
            else:
                # D-08：指纹未变但 summary 空白 → 允许重试
                need_llm.append(community)
            continue

        pending_jaccard.append(community)

    remaining_old = [
        dict(o)
        for o in old_communities
        if str(o.get("member_fingerprint") or "") not in used_old_fps
        and str(o.get("community_key") or "") not in used_old_keys
    ]
    if pending_jaccard and remaining_old:
        matches = match_communities_greedy(pending_jaccard, remaining_old, threshold=JACCARD_THRESHOLD)
        matched_new: set[int] = set()
        for ni, oi, _score in matches:
            matched_new.add(ni)
            old = remaining_old[oi]
            new = pending_jaccard[ni]
            if _summary_nonempty(old.get("summary")):
                _reuse_summary_fields(new, old)
                summaries_skipped += 1
            else:
                need_llm.append(new)
        for ni, community in enumerate(pending_jaccard):
            if ni not in matched_new:
                need_llm.append(community)
    else:
        need_llm.extend(pending_jaccard)

    if summary_fn is not None:
        from django.utils import timezone

        for community in need_llm:
            summary = await _call_summary_fn(summary_fn, community.get("members") or [], community)
            if summary:
                community["summary"] = summary
                if not community.get("summary_generated_at"):
                    community["summary_generated_at"] = timezone.now()
                summaries_generated += 1
            else:
                summaries_skipped += 1
    else:
        summaries_skipped += len(need_llm)

    return summaries_skipped, summaries_generated


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
    used_keys: set[str] = set()
    rows: list[SymbolCommunity] = []
    for c in communities:
        key = _unique_community_key(str(c.get("community_key") or ""), used_keys)
        rows.append(
            SymbolCommunity(
                repository=repo,
                branch_name=branch_name,
                community_key=key,
                algorithm=str(c.get("algorithm") or "louvain"),
                member_count=int(c.get("member_count") or 0),
                members=_truncate_members(list(c.get("members") or [])),
                member_keys=_persist_member_keys(list(c.get("member_keys") or [])),
                top_files=list(c.get("top_files") or [])[:MAX_TOP_FILES_STORED],
                member_fingerprint=str(c.get("member_fingerprint") or ""),
                summary=c.get("summary"),
                summary_model=c.get("summary_model"),
                summary_generated_at=c.get("summary_generated_at"),
                built_at_sha=built_at_sha,
            )
        )
    with transaction.atomic():
        SymbolCommunity.objects.filter(repository=repo, branch_name=branch_name).delete()
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
    """取图 → Louvain → 指纹/Jaccard 对账 →（可选 summary_fn）→ 全删全建。

    ``graph`` 可注入（测试）；缺省经 ``get_graph_service().get_graph``。
    durable 默认传入 ``agenerate_module_summary``；``summary_fn=None`` 时只落库不调 LLM。
    """
    from services.code_graph import get_graph_service

    started = time.monotonic()
    branch = branch_name or ""
    summaries_skipped = 0
    summaries_generated = 0

    try:
        logger.info(
            "code_graph_community_rebuild_started",
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
        nx_graph = getattr(code_graph, "graph", code_graph)
        chunk_evidence = getattr(code_graph, "chunk_evidence", None)

        communities = await sync_to_async(detect_communities)(
            nx_graph,
            chunk_evidence=chunk_evidence,
        )
        old_communities = await sync_to_async(_load_old_communities)(
            str(repository_id),
            branch,
        )
        summaries_skipped, summaries_generated = await _apply_summary_reconcile(
            communities,
            old_communities,
            summary_fn=summary_fn,
        )

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
                "code_graph_community_rebuild_completed",
                category="sampling",
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
                "code_graph_community_rebuild_counts",
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
                "code_graph_community_rebuild_failed",
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
    "JACCARD_THRESHOLD",
    "LOUVAIN_SEED",
    "MAX_MEMBER_KEYS_STORED",
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
