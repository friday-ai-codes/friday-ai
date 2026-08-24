"""版本化单仓 GraphQueryService：Symbol/Community/Process 确定性融合。"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from common.logging import redact_secrets_in_text
from services.code_graph.cache import get_graph_service
from services.code_graph.impact import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_NODES,
    DEFAULT_RESULT_LIMIT,
    analyze_impact,
)
from services.code_graph.process_index import search_process_index
from services.code_graph.query_manifest import (
    graph_query_manifest,
    graph_query_manifest_hash,
)
from services.retrieval.rag_search import search_rag

logger = structlog.get_logger(__name__)

GRAPH_QUERY_RESPONSE_VERSION = "graph-query/v1"
GRAPH_QUERY_RANKING_VERSION = "rrf-v1"
_RRF_K = 60
_SYMBOL_WEIGHT = 0.6
_PROCESS_WEIGHT = 0.4
_COMMUNITY_BOOST = 0.05


def _load_query_facts(
    repository_id: str,
    branch_name: str,
) -> dict[str, Any]:
    from codegraph.models import SymbolCommunity
    from repositories.models import Repository, RepositoryBranchIndex

    repo = Repository.objects.get(id=repository_id)
    effective_branch = branch_name or ""
    branch_row = None
    if branch_name:
        branch_row = RepositoryBranchIndex.objects.filter(
            repository_id=repository_id,
            branch_name=branch_name,
        ).first()
    commit_sha = str(
        (branch_row.last_indexed_commit_sha if branch_row else None)
        or repo.last_indexed_commit_sha
        or ""
    )
    communities = list(
        SymbolCommunity.objects.filter(
            repository_id=repository_id,
            branch_name=effective_branch,
        ).values(
            "community_key",
            "summary",
            "members",
            "top_files",
            "built_at_sha",
        )
    )
    return {
        "repository_id": repository_id,
        "branch_name": effective_branch,
        "commit_sha": commit_sha,
        "communities": communities,
    }


def _symbol_uid(item: Mapping[str, Any]) -> str:
    payload = item.get("payload") or {}
    return str(
        payload.get("symbol_uid")
        or payload.get("symbol_id")
        or payload.get("uid")
        or ""
    )


def _rrf(rank: int, weight: float) -> float:
    return round(weight / (_RRF_K + rank), 8)


def _disambiguation_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = row.get("payload") or {}
    return {
        "symbol_id": str(row.get("symbol_id") or ""),
        "name": str(payload.get("name") or ""),
        "file_path": str(payload.get("file_path") or ""),
        "start_line": int(payload.get("start_line") or payload.get("line_start") or 0),
        "end_line": int(payload.get("end_line") or payload.get("line_end") or 0),
    }


def _community_index(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    rendered: list[dict[str, Any]] = []
    for row in rows:
        community = {
            "community_key": str(row.get("community_key") or ""),
            "summary": str(row.get("summary") or ""),
            "top_files": list(row.get("top_files") or []),
            "built_at_sha": str(row.get("built_at_sha") or ""),
        }
        rendered.append(community)
        for member in row.get("members") or []:
            uid = str((member or {}).get("symbol_id") or "")
            if uid:
                by_symbol.setdefault(uid, []).append(community)
    return by_symbol, rendered


class GraphQueryService:
    """所有消费面共享的单仓查询 service；协议映射留给外壳。"""

    async def query(
        self,
        query: str,
        *,
        repository_id: str,
        branch_name: str = "",
        user: Any | None = None,
        initiated_by_user_id: str = "system",
        max_symbols: int = 10,
        max_processes: int = 5,
        budget_chars: int = 50_000,
        include_impact: bool = False,
        anchor_symbol_id: str | None = None,
        impact_max_depth: int = 3,
        impact_limit: int = 200,
        impact_max_nodes: int = 2000,
    ) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("query 不能为空")

        started = time.monotonic()
        try:
            logger.info(
                "code_graph_query_started",
                repository_id=repository_id,
                branch_name=branch_name,
                response_version=GRAPH_QUERY_RESPONSE_VERSION,
                initiated_by_user_id=initiated_by_user_id,
                category="caller",
                component="code_graph",
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            # 每次都走 get_graph 权限/exclusion 闸，缓存命中也不能跳过。
            code_graph = await get_graph_service().get_graph(
                repository_id,
                branch=branch_name or "",
                user=user,
            )
            facts = await sync_to_async(_load_query_facts)(
                repository_id, branch_name or ""
            )
            commit_sha = str(facts["commit_sha"])
            if not commit_sha:
                raise ValueError("graph_query_missing_index_commit")

            watermarks = {
                str(row.get("built_at_sha") or "")
                for row in facts["communities"]
            }
            community_rows = list(facts["communities"])
            warnings: list[str] = []
            capabilities = {
                "bm25": {"status": "unavailable"},
                "embedding": {"status": "unavailable"},
                "process_enrichment": {"status": "unavailable"},
                "community": {"status": "unavailable"},
                "impact": {"status": "unavailable"},
            }
            partial = False
            if community_rows and ("" in watermarks or watermarks != {commit_sha}):
                community_rows = []
                partial = True
                warnings.append("community_watermark_mismatch")
                capabilities["community"] = {
                    "status": "degraded",
                    "reason": "watermark_mismatch",
                }
            else:
                capabilities["community"] = {"status": "used"}

            symbol_rows: list[dict[str, Any]] = []
            try:
                snapshot = await search_rag(
                    query,
                    repo_ids=[repository_id],
                    branch_name=branch_name or None,
                    top_k=max(max_symbols * 3, 30),
                )
                if snapshot.status != "ok":
                    raise RuntimeError(snapshot.error or "symbol_lane_failed")
                for rank, item in enumerate(snapshot.items, start=1):
                    uid = _symbol_uid(item)
                    if not uid:
                        continue
                    symbol_rows.append(
                        {
                            "symbol_id": uid,
                            "payload": dict(item.get("payload") or {}),
                            "score": item.get("score"),
                            "ledger": {
                                "lane": "symbol_hybrid",
                                "lane_rank": rank,
                                "lane_contribution": _rrf(rank, _SYMBOL_WEIGHT),
                                "community_contribution": 0.0,
                                "final_score": 0.0,
                                "ranking_version": GRAPH_QUERY_RANKING_VERSION,
                            },
                        }
                    )
                capabilities["bm25"] = {"status": "used"}
                capabilities["embedding"] = {"status": "used"}
            except Exception as exc:
                partial = True
                warnings.append("symbol_lane_failed")
                capabilities["bm25"] = {
                    "status": "degraded",
                    "reason": type(exc).__name__,
                }
                capabilities["embedding"] = {
                    "status": "degraded",
                    "reason": type(exc).__name__,
                }

            process_rows: list[dict[str, Any]] = []
            try:
                raw_processes = await search_process_index(
                    query,
                    repository_id=repository_id,
                    branch_name=branch_name or "",
                    commit_sha=commit_sha,
                    top_k=max(max_processes * 3, 15),
                )
                for rank, row in enumerate(raw_processes, start=1):
                    process_rows.append(
                        {
                            **row,
                            "ledger": {
                                "lane": "process_hybrid",
                                "lane_rank": rank,
                                "lane_contribution": _rrf(rank, _PROCESS_WEIGHT),
                                "community_contribution": 0.0,
                                "final_score": _rrf(rank, _PROCESS_WEIGHT),
                                "ranking_version": GRAPH_QUERY_RANKING_VERSION,
                            },
                        }
                    )
                capabilities["process_enrichment"] = {"status": "used"}
            except Exception as exc:
                partial = True
                warnings.append("process_lane_failed")
                capabilities["process_enrichment"] = {
                    "status": "degraded",
                    "reason": type(exc).__name__,
                }

            by_symbol, communities = _community_index(community_rows)
            memberships: dict[str, list[dict[str, Any]]] = {}
            for process in process_rows:
                for step_index, step in enumerate(process.get("steps") or []):
                    uid = str(step.get("symbol_id") or "")
                    if uid:
                        memberships.setdefault(uid, []).append(
                            {
                                "process_key": process.get("process_key"),
                                "step_index": step_index,
                                "step": dict(step),
                            }
                        )
            for symbol in symbol_rows:
                uid = symbol["symbol_id"]
                symbol_communities = by_symbol.get(uid, [])
                boost = round(
                    min(len(symbol_communities), 1) * _COMMUNITY_BOOST,
                    8,
                )
                symbol["communities"] = symbol_communities
                symbol["process_memberships"] = memberships.get(uid, [])
                symbol["ledger"]["community_contribution"] = boost
                symbol["ledger"]["final_score"] = round(
                    symbol["ledger"]["lane_contribution"] + boost,
                    8,
                )

            symbol_rows.sort(
                key=lambda row: (
                    -float(row["ledger"]["final_score"]),
                    row["symbol_id"],
                )
            )
            process_rows.sort(
                key=lambda row: (
                    -float(row["ledger"]["final_score"]),
                    str(row.get("process_key") or ""),
                )
            )
            symbol_matched = len(symbol_rows)
            process_matched = len(process_rows)
            returned_symbols = symbol_rows[: max(max_symbols, 0)]
            returned_processes = process_rows[: max(max_processes, 0)]
            truncated_reasons: list[str] = []
            if len(returned_symbols) < symbol_matched:
                truncated_reasons.append("symbol_limit")
            if len(returned_processes) < process_matched:
                truncated_reasons.append("process_limit")

            # 预算先裁正文，schema/evidence/watermark 始终保留。
            estimated = sum(
                len(str(row.get("payload") or {})) for row in returned_symbols
            ) + sum(len(str(row.get("content") or "")) for row in returned_processes)
            if estimated > max(budget_chars, 0):
                for row in returned_symbols:
                    row["payload"].pop("content", None)
                for row in returned_processes:
                    row.pop("content", None)
                truncated_reasons.append("content_budget")

            impact: dict[str, Any] = {
                "status": "not_requested",
                "summary": None,
            }
            if include_impact:
                candidates = [
                    _disambiguation_candidate(row) for row in returned_symbols
                ]
                anchor = str(anchor_symbol_id or "")
                if not anchor and len(candidates) > 1:
                    impact = {
                        "status": "needs_disambiguation",
                        "anchor": None,
                        "candidates": candidates,
                        "summary": None,
                        "warning": "impact_not_run_without_unique_anchor",
                    }
                    capabilities["impact"] = {
                        "status": "degraded",
                        "reason": "needs_disambiguation",
                    }
                else:
                    if not anchor and len(candidates) == 1:
                        anchor = candidates[0]["symbol_id"]
                    if not anchor or anchor not in code_graph.graph:
                        impact = {
                            "status": "unavailable",
                            "anchor": anchor or None,
                            "candidates": candidates,
                            "summary": None,
                            "warning": "anchor_stale_missing_or_excluded",
                        }
                        partial = True
                        warnings.append("impact_anchor_unavailable")
                        capabilities["impact"] = {
                            "status": "degraded",
                            "reason": "anchor_unavailable",
                        }
                    else:
                        raw_impact = analyze_impact(
                            code_graph.graph,
                            anchor,
                            max_depth=max(1, min(impact_max_depth, DEFAULT_MAX_DEPTH)),
                            min_confidence=1.0,
                            include_low_confidence=False,
                            limit=max(0, min(impact_limit, DEFAULT_RESULT_LIMIT)),
                            max_nodes=max(1, min(impact_max_nodes, DEFAULT_MAX_NODES)),
                        )
                        impact_summary = dict(raw_impact["summary"])
                        truncated = bool(
                            impact_summary.get("truncated_by_nodes")
                            or any(
                                int(count) > 0
                                for count in (
                                    impact_summary.get("truncated_by_depth") or {}
                                ).values()
                            )
                        )
                        no_observed = int(impact_summary.get("total_found") or 0) == 0
                        impact = {
                            "status": "completed",
                            "anchor": {
                                "symbol_id": anchor,
                                "name": str(
                                    code_graph.graph.nodes[anchor].get("name") or ""
                                ),
                                "file_path": str(
                                    code_graph.graph.nodes[anchor].get("file_path") or ""
                                ),
                                "start_line": int(
                                    code_graph.graph.nodes[anchor].get("start_line") or 0
                                ),
                            },
                            "risk": raw_impact["risk"],
                            "risk_inputs": raw_impact["risk_inputs"],
                            "groups": raw_impact["groups"],
                            "summary": impact_summary,
                            "truncated": truncated,
                            "warning": (
                                "no_observed_impact_not_safe" if no_observed else ""
                            ),
                            "drill_down_hint": (
                                "提高 impact_limit 或缩小 max_depth 后按 Symbol UID 续查"
                                if truncated
                                else ""
                            ),
                        }
                        if no_observed:
                            warnings.append("no_observed_impact_not_safe")
                        capabilities["impact"] = {"status": "used"}

            response = {
                "contract_version": graph_query_manifest()["contract_version"],
                "manifest_hash": graph_query_manifest_hash(),
                "response_version": GRAPH_QUERY_RESPONSE_VERSION,
                "ranking_version": GRAPH_QUERY_RANKING_VERSION,
                "scope": {
                    "repository_id": repository_id,
                    "branch_name": branch_name or "",
                    "commit_sha": commit_sha,
                    "index_key": code_graph.meta.built_signature,
                },
                "partial": partial,
                "warnings": warnings,
                "capabilities": capabilities,
                "symbols": {
                    "matched_count": symbol_matched,
                    "returned_count": len(returned_symbols),
                    "items": returned_symbols,
                },
                "communities": {
                    "matched_count": len(communities),
                    "returned_count": len(communities),
                    "items": communities,
                },
                "processes": {
                    "matched_count": process_matched,
                    "returned_count": len(returned_processes),
                    "items": returned_processes,
                },
                "impact": impact,
                "truncated": bool(truncated_reasons),
                "truncated_reasons": truncated_reasons,
                "continuation_hint": (
                    "提高候选上限或使用候选 UID 继续查询"
                    if truncated_reasons
                    else ""
                ),
            }
            try:
                logger.info(
                    "code_graph_query_completed",
                    repository_id=repository_id,
                    branch_name=branch_name,
                    partial=partial,
                    symbols_returned=len(returned_symbols),
                    processes_returned=len(returned_processes),
                    duration_ms=int((time.monotonic() - started) * 1000),
                    initiated_by_user_id=initiated_by_user_id,
                    category="caller",
                    component="code_graph",
                )
            except Exception:  # noqa: BLE001
                pass
            return response
        except Exception as exc:
            try:
                logger.warning(
                    "code_graph_query_failed",
                    repository_id=repository_id,
                    branch_name=branch_name,
                    error=redact_secrets_in_text(str(exc)),
                    duration_ms=int((time.monotonic() - started) * 1000),
                    initiated_by_user_id=initiated_by_user_id,
                    category="caller",
                    component="code_graph",
                )
            except Exception:  # noqa: BLE001
                pass
            raise


__all__ = [
    "GRAPH_QUERY_RANKING_VERSION",
    "GRAPH_QUERY_RESPONSE_VERSION",
    "GraphQueryService",
]
