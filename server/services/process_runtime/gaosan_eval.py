"""高三提分专项 D2 placement-unit 评测标尺（Phase 132 / INT-02）。

D2 门槛（D-01/D-02/D-03/D-08/D-09）：
- 评测粒度 = placement-unit（非 43 feature-point top1）
- 四基线仓各自至少一次作为某放置单元的 primary（alias 归一后计数）
- out_of_team_primary_count == 0（硬失败）

观测：若打日志仅 sampling counts（passed / missing / out_of_team 计数），禁止需求全文。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = [
    "BASELINE_REPOS",
    "EVAL_GRANULARITY",
    "REPO_ALIASES",
    "normalize_repo_key",
    "score_placement_bar",
]

# D-01：评测粒度
EVAL_GRANULARITY = "placement-unit"

# D-02：四基线规范名
BASELINE_REPOS: tuple[str, ...] = (
    "frontend/onion-learning",
    "frontend/onion-practice",
    "backend/study-course",
    "backend/study-user-status",
)

# alias → 规范名（basename / 去前缀等价）
REPO_ALIASES: dict[str, str] = {
    "onion-practice": "frontend/onion-practice",
    "frontend/onion-practice": "frontend/onion-practice",
    "onion-learning": "frontend/onion-learning",
    "frontend/onion-learning": "frontend/onion-learning",
    "study-course": "backend/study-course",
    "backend/study-course": "backend/study-course",
    "study-user-status": "backend/study-user-status",
    "backend/study-user-status": "backend/study-user-status",
}

_PREFIXES = ("frontend/", "backend/")
_COMPONENT = "process_runtime"


def normalize_repo_key(name: str | None) -> str:
    """去空白、统一小写，剥离已知 frontend/backend 前缀做等价键。

    返回用于集合比较的归一化键（通常为 basename）。规范名报告仍用
    ``canonical_repo_name`` / BASELINE_REPOS。
    """
    raw = str(name or "").strip().lower().replace("\\", "/")
    while "//" in raw:
        raw = raw.replace("//", "/")
    # 已知 alias 表优先映射到规范名再取 basename
    if raw in REPO_ALIASES:
        raw = REPO_ALIASES[raw]
    for prefix in _PREFIXES:
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    return raw


def canonical_repo_name(name: str | None) -> str | None:
    """尽量还原为 BASELINE 规范名；未知仓返回原 strip 或 None。"""
    if name is None:
        return None
    raw = str(name).strip()
    if not raw:
        return None
    low = raw.lower().replace("\\", "/")
    if low in REPO_ALIASES:
        return REPO_ALIASES[low]
    key = normalize_repo_key(raw)
    for baseline in BASELINE_REPOS:
        if normalize_repo_key(baseline) == key:
            return baseline
    return raw


def _membership_of(
    repo: str | None,
    membership: Mapping[str, str] | None,
) -> str | None:
    if not repo or not membership:
        return None
    # 直接键
    if repo in membership:
        return membership[repo]
    low = repo.lower()
    if low in membership:
        return membership[low]
    # alias / basename 匹配
    key = normalize_repo_key(repo)
    for mk, mv in membership.items():
        if normalize_repo_key(mk) == key:
            return mv
    return None


def score_placement_bar(
    placements: Sequence[Mapping[str, Any] | Any] | None,
    membership: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """按 D2 门槛评分 placement-unit 级 primary 覆盖。

    Returns
    -------
    dict with keys:
      passed, missing_baselines, baseline_primary_hits,
      out_of_team_primary_count, normalized_primaries
    """
    membership = membership or {}
    placements = list(placements or [])

    baseline_keys = {normalize_repo_key(b): b for b in BASELINE_REPOS}
    hit_canonical: dict[str, str] = {}
    normalized_primaries: list[str] = []
    out_of_team_count = 0

    for p in placements:
        if isinstance(p, Mapping):
            primary = p.get("primary_repo")
        else:
            primary = getattr(p, "primary_repo", None)
        if not primary:
            continue
        key = normalize_repo_key(str(primary))
        if not key:
            continue
        normalized_primaries.append(key)
        if key in baseline_keys and key not in hit_canonical:
            hit_canonical[key] = baseline_keys[key]

        mem = _membership_of(str(primary), membership)
        if mem == "out_of_team":
            out_of_team_count += 1

    missing = [baseline_keys[k] for k in baseline_keys if k not in hit_canonical]
    hits = [hit_canonical[k] for k in baseline_keys if k in hit_canonical]
    passed = len(missing) == 0 and out_of_team_count == 0

    try:
        logger.info(
            "gaosan_placement_bar_scored",
            category="sampling",
            component=_COMPONENT,
            passed=passed,
            missing_baseline_count=len(missing),
            baseline_hit_count=len(hits),
            out_of_team_primary_count=out_of_team_count,
            placement_count=len(placements),
            eval_granularity=EVAL_GRANULARITY,
        )
    except Exception:
        pass

    return {
        "passed": passed,
        "missing_baselines": missing,
        "baseline_primary_hits": hits,
        "out_of_team_primary_count": out_of_team_count,
        "normalized_primaries": normalized_primaries,
        "eval_granularity": EVAL_GRANULARITY,
    }
