"""放置单元细落点（Phase 130，UNIT-02/03；去固定角色化）。

在 ``shortlist ∩ team`` 硬范围内为每个 Placement Unit 产出
``primary_repo`` / ``supporting_repos`` / confidence / evidence / open_questions。
调用 ``RepoRouterV2.route(..., repository_ids=hard_scope, use_llm=True)`` 取分；
**禁止**全库开放 primary。primary∉hard_scope → 丢弃并 degrade/open_question。

观测：``place_units_started/completed/failed``，``category=sampling``，
``component=process_runtime``；禁止需求全文入日志。
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = [
    "UnitPlacement",
    "PlacementResult",
    "place_units",
    "placement_result_to_dict",
    "resolve_hard_scope",
]

_COMPONENT = "process_runtime"


@dataclass
class UnitPlacement:
    """单个放置单元的落点结果。"""

    unit_id: str
    primary_repo: str | None = None
    supporting_repos: list[str] = field(default_factory=list)
    confidence: str = "low"
    evidence: list[dict[str, Any]] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    feature_ids: list[str] = field(default_factory=list)
    hard_scope: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)


@dataclass
class PlacementResult:
    """place_units 结果容器。"""

    status: str = "ok"
    placements: list[UnitPlacement] = field(default_factory=list)
    unit_count: int = 0
    placement_count: int = 0
    hard_scope: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    degrade_reasons: list[str] = field(default_factory=list)


def placement_result_to_dict(result: PlacementResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "status": result.status,
        "placements": [asdict(p) for p in result.placements],
        "unit_count": result.unit_count,
        "placement_count": result.placement_count,
        "hard_scope": list(result.hard_scope),
        "duration_ms": result.duration_ms,
        "degrade_reasons": list(result.degrade_reasons),
    }


def _id_list(values: Sequence[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        rid = str(v or "").strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        out.append(rid)
    return out


def resolve_hard_scope(
    *,
    shortlist_ids: Sequence[str] | None,
    reuse_host_repo_ids: Sequence[str] | None = None,
    team_core: Sequence[str] | None = None,
) -> list[str]:
    """hard_scope = (shortlist ∪ reuse hosts) ∩ team（team 空则仅用 shortlist∪hosts）。"""
    shortlist = _id_list(shortlist_ids)
    hosts = _id_list(reuse_host_repo_ids)
    combined = _id_list([*shortlist, *hosts])
    team = _id_list(team_core)
    if not team:
        return combined
    team_set = set(team)
    return [rid for rid in combined if rid in team_set]


def _unit_attr(unit: Any, key: str, default: Any = None) -> Any:
    if isinstance(unit, dict):
        return unit.get(key, default)
    return getattr(unit, key, default)


def _confidence_from_score(score: float, *, contested: bool) -> str:
    if contested:
        return "low"
    if score >= 0.75:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


async def place_units(
    units: Sequence[Any] | None,
    *,
    shortlist_ids: Sequence[str] | None = None,
    role_map: Mapping[str, Any] | None = None,  # noqa: ARG001 — 兼容旧调用方，已忽略
    placement_defaults: Mapping[str, Any] | None = None,  # noqa: ARG001 — 已退役
    team_core: Sequence[str] | None = None,
    router: Any = None,
    use_llm: bool = True,
    top_k: int = 5,
    capability_scores: Mapping[str, float] | None = None,
    reuse_host_repo_ids: Sequence[str] | None = None,
    forbidden_repo_ids: Sequence[str] | None = None,
) -> PlacementResult:
    """在 hard_scope 内为每个 unit 细落点（RepoRouterV2 驱动，无固定角色加权）。"""
    started = time.perf_counter()
    unit_list = list(units or [])
    team = _id_list(team_core)
    team_universe = set(team) if team else set(_id_list(shortlist_ids))
    if not team_universe:
        team_universe = set(_id_list(shortlist_ids))

    reuse_hosts = _id_list(reuse_host_repo_ids)
    if team:
        reuse_hosts = [h for h in reuse_hosts if h in set(team)]
    hard_scope = resolve_hard_scope(
        shortlist_ids=shortlist_ids,
        reuse_host_repo_ids=reuse_hosts,
        team_core=team or list(team_universe),
    )
    forbidden = set(_id_list(forbidden_repo_ids))
    degrade_reasons: list[str] = []

    logger.info(
        "place_units_started",
        unit_count=len(unit_list),
        hard_scope_count=len(hard_scope),
        shortlist_count=len(_id_list(shortlist_ids)),
        use_llm=bool(use_llm),
        category="sampling",
        component=_COMPONENT,
    )

    try:
        if not hard_scope:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "place_units_completed",
                unit_count=len(unit_list),
                placement_count=0,
                hard_scope_count=0,
                duration_ms=duration_ms,
                category="sampling",
                component=_COMPONENT,
            )
            return PlacementResult(
                status="degraded",
                placements=[],
                unit_count=len(unit_list),
                placement_count=0,
                hard_scope=[],
                duration_ms=duration_ms,
                degrade_reasons=["empty_hard_scope"],
            )

        placements: list[UnitPlacement] = []
        for unit in unit_list:
            unit_id = str(_unit_attr(unit, "unit_id") or "")
            feature_ids = list(_unit_attr(unit, "feature_ids") or [])
            query_text = str(_unit_attr(unit, "query_text") or "")
            open_questions: list[str] = []
            evidence: list[dict[str, Any]] = [
                {"source": "hard_scope", "repository_ids_count": len(hard_scope)},
            ]
            scores: dict[str, float] = {
                rid: float((capability_scores or {}).get(rid, 0.0)) for rid in hard_scope
            }

            if router is not None:
                try:
                    route_fn = getattr(router, "route", None)
                    if route_fn is not None:
                        result = await route_fn(
                            query_text,
                            top_k=top_k,
                            repository_ids=list(hard_scope),
                            use_llm=use_llm,
                        )
                        for c in getattr(result, "candidates", []) or []:
                            rid = str(getattr(c, "repo_id", "") or "")
                            if not rid:
                                continue
                            if rid not in hard_scope:
                                degrade_reasons.append("v2_candidate_out_of_scope")
                                open_questions.append(
                                    f"discarded_out_of_scope:{rid[:64]}"
                                )
                                continue
                            scores[rid] = max(
                                scores.get(rid, 0.0),
                                float(getattr(c, "score", 0.0) or 0.0),
                            )
                        evidence.append(
                            {
                                "source": "repo_router_v2",
                                "kind": "v2",
                                "router_version": str(
                                    getattr(result, "router_version", "") or ""
                                ),
                                "use_llm": bool(use_llm),
                                "in_scope_hits": len(
                                    [
                                        c
                                        for c in getattr(result, "candidates", []) or []
                                        if str(getattr(c, "repo_id", "")) in hard_scope
                                    ]
                                ),
                            }
                        )
                except Exception as exc:  # noqa: BLE001
                    degrade_reasons.append("router_failed")
                    open_questions.append("router_unavailable")
                    logger.warning(
                        "place_units_router_failed",
                        unit_id=unit_id[:64],
                        error=redact_secrets_in_text(str(exc)),
                        category="sampling",
                        component=_COMPONENT,
                    )

            ranked = sorted(
                (
                    (rid, sc)
                    for rid, sc in scores.items()
                    if rid in hard_scope and rid not in forbidden
                ),
                key=lambda x: (-x[1], x[0]),
            )

            primary: str | None = ranked[0][0] if ranked else None

            # 最终守卫：primary ∈ hard_scope 且非 forbidden
            if primary and (primary not in hard_scope or primary in forbidden):
                open_questions.append(f"discarded_invalid_primary:{primary[:64]}")
                degrade_reasons.append("primary_out_of_hard_scope")
                primary = next(
                    (rid for rid, _ in ranked if rid in hard_scope and rid not in forbidden),
                    None,
                )

            supporting = [
                rid
                for rid, _ in ranked
                if rid != primary and rid in hard_scope and rid not in forbidden
            ][: max(0, top_k - 1)]

            if not primary:
                open_questions.append("no_in_scope_primary")
                confidence = "low"
            else:
                top_score = scores.get(primary, 0.0)
                contested = (
                    len(ranked) > 1 and abs(ranked[0][1] - ranked[1][1]) < 0.05
                )
                confidence = _confidence_from_score(top_score, contested=contested)
                if contested:
                    open_questions.append("near_tie_multi_repo")

            placements.append(
                UnitPlacement(
                    unit_id=unit_id,
                    primary_repo=primary,
                    supporting_repos=supporting,
                    confidence=confidence,
                    evidence=evidence,
                    open_questions=list(dict.fromkeys(open_questions)),
                    feature_ids=feature_ids,
                    hard_scope=list(hard_scope),
                    scores={k: round(v, 4) for k, v in scores.items() if k in hard_scope},
                )
            )

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        degrade_reasons = list(dict.fromkeys(degrade_reasons))
        status = "ok" if placements else "degraded"
        result = PlacementResult(
            status=status,
            placements=placements,
            unit_count=len(unit_list),
            placement_count=len(placements),
            hard_scope=list(hard_scope),
            duration_ms=duration_ms,
            degrade_reasons=degrade_reasons,
        )
        logger.info(
            "place_units_completed",
            unit_count=result.unit_count,
            placement_count=result.placement_count,
            hard_scope_count=len(hard_scope),
            duration_ms=duration_ms,
            category="sampling",
            component=_COMPONENT,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.warning(
            "place_units_failed",
            error=redact_secrets_in_text(str(exc)),
            duration_ms=duration_ms,
            category="sampling",
            component=_COMPONENT,
        )
        return PlacementResult(
            status="degraded",
            placements=[],
            unit_count=len(unit_list),
            placement_count=0,
            hard_scope=list(hard_scope),
            duration_ms=duration_ms,
            degrade_reasons=["place_units_exception"],
        )
