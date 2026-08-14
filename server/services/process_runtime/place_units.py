"""放置单元细落点（Phase 130，UNIT-02/03；D-07~D-11）。

在 ``shortlist ∪ reuse hosts``（∩ team）硬范围内为每个 Placement Unit 产出
``primary_repo`` / ``supporting_repos`` / confidence / evidence / open_questions。
可调用 ``RepoRouterV2.route(..., repository_ids=hard_scope)`` 只取分数；
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


def _roles_payload(role_map: Mapping[str, Any] | None) -> dict[str, Any]:
    if not role_map:
        return {}
    if isinstance(role_map, Mapping) and "roles" in role_map:
        roles = role_map.get("roles") or {}
        return roles if isinstance(roles, dict) else {}
    # 允许直接传 roles dict
    return dict(role_map) if isinstance(role_map, Mapping) else {}


def _forbidden_ids(role_map: Mapping[str, Any] | None) -> set[str]:
    forbidden: set[str] = set()
    roles = _roles_payload(role_map)
    for bucket in roles.values():
        if not isinstance(bucket, dict):
            continue
        for rid in bucket.get("forbidden") or []:
            if rid:
                forbidden.add(str(rid))
    if isinstance(role_map, Mapping):
        for entry in role_map.get("per_repo") or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("assignment") or "") == "forbidden":
                rid = str(entry.get("repository_id") or "").strip()
                if rid:
                    forbidden.add(rid)
    return forbidden


def resolve_reuse_host_repo_ids(
    *,
    role_map: Mapping[str, Any] | None,
    units: Sequence[Any],
    team_universe: set[str],
) -> list[str]:
    """从 role_map.practice_reuse_host + unit hints 解析复用宿主（∩ team）。"""
    hosts: list[str] = []
    seen: set[str] = set()
    roles = _roles_payload(role_map)
    practice = roles.get("practice_reuse_host") if isinstance(roles, dict) else None
    if isinstance(practice, dict):
        for rid in [practice.get("primary"), *(practice.get("supporting") or [])]:
            sid = str(rid or "").strip()
            if sid and sid in team_universe and sid not in seen:
                seen.add(sid)
                hosts.append(sid)

    # hints 仅标记需要 host；具体 id 仍来自 role_map（不硬编码 UUID）
    need_practice = False
    for unit in units:
        hints = getattr(unit, "reuse_host_hints", None)
        if hints is None and isinstance(unit, dict):
            hints = unit.get("reuse_host_hints")
        for h in hints or []:
            hs = str(h).lower()
            if "practice" in hs or "做题" in hs or "reuse_host" in hs:
                need_practice = True
    if need_practice and not hosts:
        # 无 role_map host 时不捏造；仅返回空（open_questions 下游处理）
        pass
    return hosts


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


def _is_learning_state_unit(unit: Any) -> bool:
    hints = [str(h).lower() for h in (_unit_attr(unit, "reuse_host_hints") or [])]
    if any("learning_state" in h for h in hints):
        return True
    qt = str(_unit_attr(unit, "query_text") or "")
    return any(tok in qt for tok in ("学习状态", "学习进度", "learning state", "学情"))


async def place_units(
    units: Sequence[Any] | None,
    *,
    shortlist_ids: Sequence[str] | None = None,
    role_map: Mapping[str, Any] | None = None,
    placement_defaults: Mapping[str, Any] | None = None,
    team_core: Sequence[str] | None = None,
    router: Any = None,
    use_llm: bool = False,
    top_k: int = 5,
    capability_scores: Mapping[str, float] | None = None,
) -> PlacementResult:
    """在 hard_scope 内为每个 unit 细落点。"""
    started = time.perf_counter()
    unit_list = list(units or [])
    defaults = dict(placement_defaults or {})
    team = _id_list(team_core)
    team_universe = set(team) if team else set(_id_list(shortlist_ids))
    # 若未给 team，仍允许 shortlist 宇宙
    if not team_universe:
        team_universe = set(_id_list(shortlist_ids))

    reuse_hosts = resolve_reuse_host_repo_ids(
        role_map=role_map, units=unit_list, team_universe=team_universe or set(_id_list(shortlist_ids) + _id_list(team_core))
    )
    # 若 practice host 在 shortlist 外但在 team 内，仍并入
    if team:
        reuse_hosts = [h for h in reuse_hosts if h in set(team)]
    hard_scope = resolve_hard_scope(
        shortlist_ids=shortlist_ids,
        reuse_host_repo_ids=reuse_hosts,
        team_core=team or list(team_universe),
    )
    forbidden = _forbidden_ids(role_map)
    roles = _roles_payload(role_map)
    degrade_reasons: list[str] = []

    logger.info(
        "place_units_started",
        unit_count=len(unit_list),
        hard_scope_count=len(hard_scope),
        shortlist_count=len(_id_list(shortlist_ids)),
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

        # 可选：批量预热 — 仍按 unit 调用以保持可测「按 unit 计」
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
                                "router_version": str(
                                    getattr(result, "router_version", "") or ""
                                ),
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

            # 角色信号加权（非唯一决策）
            for role_name, bucket in roles.items():
                if not isinstance(bucket, dict):
                    continue
                primary = str(bucket.get("primary") or "").strip()
                if primary and primary in hard_scope:
                    bump = 0.15
                    if role_name == "practice_reuse_host" and any(
                        "practice" in str(h).lower()
                        for h in (_unit_attr(unit, "reuse_host_hints") or [])
                    ):
                        bump = 0.35
                    if role_name == "learning_state" and _is_learning_state_unit(unit):
                        bump = 0.4
                    scores[primary] = scores.get(primary, 0.0) + bump
                    evidence.append(
                        {
                            "source": "role_map",
                            "role": role_name,
                            "repository_id": primary,
                            "bump": bump,
                        }
                    )

            # 候选排序：排除 forbidden
            ranked = sorted(
                (
                    (rid, sc)
                    for rid, sc in scores.items()
                    if rid in hard_scope and rid not in forbidden
                ),
                key=lambda x: (-x[1], x[0]),
            )

            app_shell = ""
            shell_bucket = roles.get("app_shell") if isinstance(roles, dict) else None
            if isinstance(shell_bucket, dict):
                app_shell = str(shell_bucket.get("primary") or "").strip()

            primary: str | None = None
            if ranked:
                primary = ranked[0][0]

            # learning_state_writer_not_app_shell
            if (
                defaults.get("learning_state_writer_not_app_shell")
                and _is_learning_state_unit(unit)
                and primary
                and app_shell
                and primary == app_shell
            ):
                alt = next((rid for rid, _ in ranked if rid != app_shell), None)
                if alt:
                    evidence.append(
                        {
                            "source": "placement_defaults",
                            "rule": "learning_state_writer_not_app_shell",
                            "from": app_shell,
                            "to": alt,
                        }
                    )
                    primary = alt
                else:
                    open_questions.append(
                        "learning_state_writer_only_app_shell_candidate"
                    )

            # practice_reuse_prefers_host_not_shell
            if (
                defaults.get("practice_reuse_prefers_host_not_shell")
                and any(
                    "practice" in str(h).lower()
                    for h in (_unit_attr(unit, "reuse_host_hints") or [])
                )
                and primary
                and app_shell
                and primary == app_shell
            ):
                practice_bucket = roles.get("practice_reuse_host")
                host = ""
                if isinstance(practice_bucket, dict):
                    host = str(practice_bucket.get("primary") or "").strip()
                if host and host in hard_scope and host not in forbidden:
                    primary = host
                    evidence.append(
                        {
                            "source": "placement_defaults",
                            "rule": "practice_reuse_prefers_host_not_shell",
                            "to": host,
                        }
                    )

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
                    len(ranked) > 1
                    and abs(ranked[0][1] - ranked[1][1]) < 0.05
                )
                confidence = _confidence_from_score(top_score, contested=contested)
                if contested:
                    open_questions.append("near_tie_multi_repo")

            if _unit_attr(unit, "reuse_host_hints") and not reuse_hosts:
                if any(
                    "practice" in str(h).lower()
                    for h in (_unit_attr(unit, "reuse_host_hints") or [])
                ):
                    open_questions.append("missing_practice_reuse_host")

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
        # 去重 degrade
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
