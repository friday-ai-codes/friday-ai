"""历史先验分桶（Phase 129，LIST-03；D-05）。

拆「需求史」``tech_plan`` 与「上线史」``document|code_change``，与 ``team_core``
求交生成 shortlist 可消费的 ``force_include_ids``。

复用 ``ascore_history_match`` 的检索口径；本模块按 entity kind 分桶。无 actor /
检索失败 fail-soft，带 ``unavailable_reason``，不阻断 shortlist 其他信号。

观测：``history_prior_started/completed/failed``；RetrievalTrace 只记条数/耗时/score。
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = [
    "HistoryPriorResult",
    "HISTORY_FORCE_SCORE_THRESHOLD",
    "asplit_history_priors",
    "force_include_from_history",
]

_COMPONENT = "process_runtime"

# 过阈值才 force-include（可测常数）
HISTORY_FORCE_SCORE_THRESHOLD = 0.35

_DEMAND_KINDS = frozenset({"tech_plan"})
_LAUNCH_KINDS = frozenset({"document", "code_change"})


@dataclass
class HistoryPriorResult:
    """历史先验分桶结果。"""

    demand_repo_ids: list[str] = field(default_factory=list)
    launch_repo_ids: list[str] = field(default_factory=list)
    force_include_ids: list[str] = field(default_factory=list)
    reasons_by_repo: dict[str, list[str]] = field(default_factory=dict)
    top_scores: dict[str, float] = field(default_factory=dict)
    hit_counts: dict[str, int] = field(default_factory=dict)
    unavailable_reason: str = ""
    duration_ms: float = 0.0


@dataclass
class _HitBundle:
    hits: list[dict[str, Any]] = field(default_factory=list)
    unavailable_reason: str = ""


def force_include_from_history(result: HistoryPriorResult) -> list[str]:
    """便捷：取出可注入 shortlist 的 force_include_ids。"""
    return list(result.force_include_ids or [])


@sync_to_async
def _resolve_actor(session):
    return session.created_by if session is not None else None


async def _aretrieve_history_hits(
    *,
    query: str,
    candidate_repository_ids: list[str],
    session=None,
    acting_user=None,
) -> _HitBundle:
    """底层检索：返回带 kind 的逐条命中（供分桶）。失败不抛。"""
    from services.process_runtime.blueprint_route_history import HISTORY_ENTITY_KINDS

    candidate_ids = [str(r) for r in (candidate_repository_ids or []) if str(r or "").strip()]
    if not str(query or "").strip() or not candidate_ids:
        return _HitBundle(unavailable_reason="empty_query")

    try:
        from knowledge.retrieval import DeliveryKnowledgeSearchService

        actor = acting_user
        if actor is None and session is not None:
            actor = await _resolve_actor(session)
        if actor is None:
            return _HitBundle(unavailable_reason="no_acting_user")

        results = await DeliveryKnowledgeSearchService().search_similar(
            query,
            user=actor,
            top_k=len(candidate_ids) * 2 + 10,
            entity_kinds=list(HISTORY_ENTITY_KINDS),
            repository_ids=candidate_ids,
            include_document_kind=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "history_prior_retrieve_failed",
            error=redact_secrets_in_text(str(exc)),
            category="sampling",
            component=_COMPONENT,
        )
        return _HitBundle(unavailable_reason="retrieval_error")

    allowed = set(candidate_ids)
    hits: list[dict[str, Any]] = []
    # 工件边归因（复用 history 模块）
    from services.process_runtime import blueprint_route_history as hist

    scored: list[tuple[str, float, str, Any]] = []  # eid, score, kind, entity
    direct: dict[str, str] = {}
    for result in results or []:
        entity = getattr(result, "entity", None)
        entity_id = str(getattr(entity, "entity_id", "") or "")
        if not entity_id:
            continue
        try:
            score = float(getattr(result, "score", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        kind = str(getattr(entity, "kind", "") or getattr(entity, "entity_kind", "") or "")
        scored.append((entity_id, score, kind, entity))
        repository_id = str(getattr(entity, "repository_id", "") or "")
        if repository_id:
            direct[entity_id] = repository_id

    via_edges = await hist._resolve_repos_via_edges(  # noqa: SLF001 — 同包复用边归因
        [eid for eid, _, _, _ in scored if eid not in direct]
    )
    for entity_id, score, kind, _entity in scored:
        repo_ids = [direct[entity_id]] if entity_id in direct else via_edges.get(entity_id, [])
        for rid in repo_ids:
            if rid not in allowed:
                continue
            hits.append(
                {
                    "repository_id": rid,
                    "kind": kind,
                    "score": score,
                    "entity_id": entity_id,
                }
            )
    return _HitBundle(hits=hits, unavailable_reason="")


async def asplit_history_priors(
    *,
    query: str,
    team_core: Sequence[str] | None = None,
    candidate_repository_ids: Sequence[str] | None = None,
    session=None,
    acting_user=None,
    score_threshold: float = HISTORY_FORCE_SCORE_THRESHOLD,
) -> HistoryPriorResult:
    """按 entity kind 分桶并与 team_core 求交生成 force-include。"""
    started = time.perf_counter()
    core = [str(r) for r in (team_core or []) if str(r or "").strip()]
    core_set = set(core)
    candidates = [
        str(r)
        for r in (candidate_repository_ids or core)
        if str(r or "").strip()
    ]
    if not candidates:
        candidates = list(core)

    logger.info(
        "history_prior_started",
        team_core_count=len(core),
        candidate_count=len(candidates),
        category="sampling",
        component=_COMPONENT,
    )

    try:
        bundle = await _aretrieve_history_hits(
            query=query,
            candidate_repository_ids=candidates,
            session=session,
            acting_user=acting_user,
        )
    except Exception as exc:  # noqa: BLE001
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.warning(
            "history_prior_failed",
            error=redact_secrets_in_text(str(exc)),
            duration_ms=duration_ms,
            category="sampling",
            component=_COMPONENT,
        )
        return HistoryPriorResult(
            unavailable_reason="retrieval_error",
            duration_ms=duration_ms,
        )

    if bundle.unavailable_reason:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "history_prior_completed",
            force_include_count=0,
            unavailable_reason=bundle.unavailable_reason,
            duration_ms=duration_ms,
            category="sampling",
            component=_COMPONENT,
        )
        return HistoryPriorResult(
            unavailable_reason=bundle.unavailable_reason,
            duration_ms=duration_ms,
        )

    demand_scores: dict[str, float] = {}
    launch_scores: dict[str, float] = {}
    hit_counts: dict[str, int] = {}
    top_scores: dict[str, float] = {}

    for hit in bundle.hits:
        rid = str(hit.get("repository_id") or "")
        kind = str(hit.get("kind") or "").strip().lower()
        try:
            score = float(hit.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if not rid:
            continue
        hit_counts[rid] = hit_counts.get(rid, 0) + 1
        if score > top_scores.get(rid, 0.0):
            top_scores[rid] = score
        if kind in _DEMAND_KINDS:
            if score > demand_scores.get(rid, 0.0):
                demand_scores[rid] = score
        elif kind in _LAUNCH_KINDS:
            if score > launch_scores.get(rid, 0.0):
                launch_scores[rid] = score

    threshold = float(score_threshold)
    demand_ids = [rid for rid, sc in demand_scores.items() if sc >= threshold]
    launch_ids = [rid for rid, sc in launch_scores.items() if sc >= threshold]

    reasons: dict[str, list[str]] = {}
    force: list[str] = []
    for rid in demand_ids:
        if rid not in core_set:
            continue
        reasons.setdefault(rid, []).append("history_demand")
        if rid not in force:
            force.append(rid)
    for rid in launch_ids:
        if rid not in core_set:
            continue
        reasons.setdefault(rid, []).append("history_launch")
        if rid not in force:
            force.append(rid)

    # 去重 reason
    reasons = {k: list(dict.fromkeys(v)) for k, v in reasons.items()}

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    result = HistoryPriorResult(
        demand_repo_ids=sorted(demand_ids),
        launch_repo_ids=sorted(launch_ids),
        force_include_ids=force,
        reasons_by_repo=reasons,
        top_scores=top_scores,
        hit_counts=hit_counts,
        unavailable_reason="",
        duration_ms=duration_ms,
    )
    # RetrievalTrace：只记指标
    try:
        from interactions.ledger import arecord_retrieval_trace
        from interactions.models import RetrievalTrace

        await arecord_retrieval_trace(
            None,
            kind=RetrievalTrace.Kind.CHUNK,
            payload={
                "source": "history_prior",
                "result_count": len(bundle.hits),
                "force_include_count": len(force),
                "top_score": max(top_scores.values()) if top_scores else 0,
                "duration_ms": duration_ms,
            },
            user_id=None,
            source="process_runtime",
        )
    except Exception:  # noqa: BLE001
        pass

    logger.info(
        "history_prior_completed",
        force_include_count=len(force),
        demand_count=len(demand_ids),
        launch_count=len(launch_ids),
        hit_count=len(bundle.hits),
        duration_ms=duration_ms,
        category="sampling",
        component=_COMPONENT,
    )
    return result
