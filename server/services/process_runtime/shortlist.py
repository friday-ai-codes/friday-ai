"""短名单生成（Phase 129，LIST-01/02/04；D-01、D-04、D-06~D-10）。

在 ``team_core ∪ 合法 adjacent`` 宇宙内合成活跃度、能力粗相关、章程域命中；
planned 章程与外部 ``force_include_ids`` 可强制拉入并突破 top-N 上界。
``out_of_team`` 一律剔除。

**禁止**改写 ``RepoRouterV2``——能力粗分可注入 stub，生产路径可在限定
``repository_ids`` 上调用 V2 取分。

观测：``shortlist_started/completed/failed``，``category=sampling``，
``component=process_runtime``；禁止需求原文入日志。
"""

from __future__ import annotations

import time
from collections.abc import Collection, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = [
    "ShortlistResult",
    "ShortlistRepo",
    "DEFAULT_TOP_N",
    "build_shortlist",
    "shortlist_to_dict",
]

_COMPONENT = "process_runtime"
DEFAULT_TOP_N = 10

# 信号等权（discretion，可测、可进 breakdown）
_W_ACTIVITY = 1.0
_W_CAPABILITY = 1.0
_W_CHARTER = 1.0


@dataclass
class ShortlistRepo:
    """短名单单仓条目。"""

    repository_id: str
    rank: int = 0
    score: float = 0.0
    team_membership: str = "team_core"
    signals: dict[str, float] = field(default_factory=dict)
    force_include_reasons: list[str] = field(default_factory=list)


@dataclass
class ShortlistResult:
    """短名单结果。"""

    status: str = "ok"
    clarify_reason: str = ""
    repositories: list[dict[str, Any]] = field(default_factory=list)
    shortlist_count: int = 0
    duration_ms: float = 0.0
    degrade_reasons: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def shortlist_to_dict(result: ShortlistResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return asdict(result)


def _id_list(values: Collection[str] | None) -> list[str]:
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


def _score_map(raw: Mapping[str, float] | None) -> dict[str, float]:
    if not raw:
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        rid = str(k or "").strip()
        if not rid:
            continue
        try:
            out[rid] = float(v or 0.0)
        except (TypeError, ValueError):
            out[rid] = 0.0
    return out


def _membership(
    rid: str, *, core: set[str], adjacent: set[str]
) -> str:
    if rid in core:
        return "team_core"
    if rid in adjacent:
        return "team_adjacent"
    return "out_of_team"


async def build_shortlist(
    *,
    team_core: Sequence[str] | None = None,
    adjacent_ids: Sequence[str] | None = None,
    out_of_team_ids: Sequence[str] | None = None,
    activity_scores: Mapping[str, float] | None = None,
    capability_scores: Mapping[str, float] | None = None,
    charter_domain_scores: Mapping[str, float] | None = None,
    planned_charter_ids: Sequence[str] | None = None,
    force_include_ids: Sequence[str] | None = None,
    force_include_reasons_by_id: Mapping[str, Sequence[str]] | None = None,
    top_n: int = DEFAULT_TOP_N,
    query: str = "",  # noqa: ARG001 — 仅用于调用方兼容；永不写入日志
    profile: Mapping[str, Any] | None = None,  # noqa: ARG001 — 预留画像粗相关
    degrade_reasons: Sequence[str] | None = None,
) -> ShortlistResult:
    """在团队宇宙内生成可解释 shortlist。

    信号可注入（单测 stub）；未注入时对应分视为 0。``force_include_ids`` 与
    ``planned_charter_ids`` 在宇宙内强制保留，可突破 ``top_n``。
    """
    started = time.perf_counter()
    core = _id_list(team_core)
    adjacent = _id_list(adjacent_ids)
    out_of_team = set(_id_list(out_of_team_ids))
    universe = [rid for rid in dict.fromkeys([*core, *adjacent]) if rid not in out_of_team]
    universe_set = set(universe)
    core_set = set(core)
    adjacent_set = set(adjacent) & universe_set

    logger.info(
        "shortlist_started",
        team_core_count=len(core),
        adjacent_count=len(adjacent_set),
        universe_count=len(universe),
        top_n=int(top_n),
        category="sampling",
        component=_COMPONENT,
    )

    try:
        activity = _score_map(activity_scores)
        capability = _score_map(capability_scores)
        charter = _score_map(charter_domain_scores)
        planned = set(_id_list(planned_charter_ids)) & universe_set
        force_ids = set(_id_list(force_include_ids)) & universe_set
        # 拒绝 out_of_team（即便误传 force / planned）
        planned -= out_of_team
        force_ids -= out_of_team
        reason_map: dict[str, list[str]] = {}
        if force_include_reasons_by_id:
            for rid, reasons in force_include_reasons_by_id.items():
                key = str(rid or "").strip()
                if key not in universe_set or key in out_of_team:
                    continue
                cleaned = [str(r).strip() for r in (reasons or []) if str(r or "").strip()]
                if cleaned:
                    reason_map[key] = cleaned

        scored: list[dict[str, Any]] = []
        for rid in universe:
            act = float(activity.get(rid, 0.0))
            cap = float(capability.get(rid, 0.0))
            ch = float(charter.get(rid, 0.0))
            total = _W_ACTIVITY * act + _W_CAPABILITY * cap + _W_CHARTER * ch
            reasons: list[str] = []
            if rid in planned:
                reasons.append("charter_planned")
            if rid in force_ids:
                reasons.extend(reason_map.get(rid, []))
                # 钩子传入但无显式 reason 时保留空，由调用方补；至少确保 force 合入
            # 去重保序
            reasons = list(dict.fromkeys(reasons))
            scored.append(
                {
                    "repository_id": rid,
                    "rank": 0,
                    "score": total,
                    "team_membership": _membership(
                        rid, core=core_set, adjacent=adjacent_set
                    ),
                    "signals": {
                        "activity": act,
                        "capability_coarse": cap,
                        "charter_domain": ch,
                    },
                    "force_include_reasons": reasons,
                }
            )

        scored.sort(key=lambda r: (-float(r["score"]), r["repository_id"]))
        n = max(1, int(top_n)) if top_n else DEFAULT_TOP_N
        must_keep = planned | force_ids
        selected: list[dict[str, Any]] = []
        selected_ids: set[str] = set()
        for item in scored:
            if len(selected) >= n and item["repository_id"] not in must_keep:
                continue
            if item["repository_id"] in selected_ids:
                continue
            # top-N 内优先；超出 N 仅 must_keep
            if len(selected) < n or item["repository_id"] in must_keep:
                selected.append(item)
                selected_ids.add(item["repository_id"])

        # 确保 must_keep 全在（分数排序后可能因逻辑遗漏）
        by_id = {r["repository_id"]: r for r in scored}
        for rid in must_keep:
            if rid not in selected_ids and rid in by_id:
                selected.append(by_id[rid])
                selected_ids.add(rid)

        selected.sort(key=lambda r: (-float(r["score"]), r["repository_id"]))
        for i, item in enumerate(selected, start=1):
            item["rank"] = i

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        result = ShortlistResult(
            status="ok",
            repositories=selected,
            shortlist_count=len(selected),
            duration_ms=duration_ms,
            degrade_reasons=list(degrade_reasons or []),
            meta={"shortlist_count": len(selected)},
        )
        logger.info(
            "shortlist_completed",
            shortlist_count=len(selected),
            force_include_count=len(must_keep & selected_ids),
            duration_ms=duration_ms,
            category="sampling",
            component=_COMPONENT,
        )
        return result
    except Exception as exc:  # noqa: BLE001 — best-effort 形状恒定
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.warning(
            "shortlist_failed",
            error=redact_secrets_in_text(str(exc)),
            duration_ms=duration_ms,
            category="sampling",
            component=_COMPONENT,
        )
        return ShortlistResult(
            status="ok",
            repositories=[],
            shortlist_count=0,
            duration_ms=duration_ms,
            degrade_reasons=["shortlist_error"],
            meta={"shortlist_count": 0},
        )
