"""合成 Learning-tools Space 宇宙（Phase 132 / INT-02；去固定角色化）。

提供 team_core、out_of_team 诱饵、membership、压缩 modules/features，
以及 unit → expected_primary 映射。不读活 DB / 无网络。
"""

from __future__ import annotations

from typing import Any

# 规范 id（测试宇宙内用规范路径作 repository_id）
REPO_ONION_LEARNING = "frontend/onion-learning"
REPO_ONION_PRACTICE = "frontend/onion-practice"
REPO_STUDY_COURSE = "backend/study-course"
REPO_STUDY_USER_STATUS = "backend/study-user-status"

# out_of_team 诱饵
REPO_STUDY_APP = "study-app"
REPO_STUDY_PRACTICE = "study-practice"
REPO_VOCATION_PROBLEM = "vocation-problem-app"

TEAM_CORE_IDS: list[str] = [
    REPO_ONION_LEARNING,
    REPO_ONION_PRACTICE,
    REPO_STUDY_COURSE,
    REPO_STUDY_USER_STATUS,
]

OUT_OF_TEAM_IDS: list[str] = [
    REPO_STUDY_APP,
    REPO_STUDY_PRACTICE,
    REPO_VOCATION_PROBLEM,
]

# alias 也记入 membership，便于 bar / funnel 用短名查找
MEMBERSHIP: dict[str, str] = {
    REPO_ONION_LEARNING: "team_core",
    REPO_ONION_PRACTICE: "team_core",
    REPO_STUDY_COURSE: "team_core",
    REPO_STUDY_USER_STATUS: "team_core",
    "onion-learning": "team_core",
    "onion-practice": "team_core",
    "study-course": "team_core",
    "study-user-status": "team_core",
    REPO_STUDY_APP: "out_of_team",
    REPO_STUDY_PRACTICE: "out_of_team",
    REPO_VOCATION_PROBLEM: "out_of_team",
}

# unit → 期望 primary（fixture 对齐，非硬编码产品角色枚举）
UNIT_PRIMARY_EXPECTATIONS: dict[str, str] = {
    "mod-shell": REPO_ONION_LEARNING,
    "mod-practice": REPO_ONION_PRACTICE,
    "mod-course": REPO_STUDY_COURSE,
    "mod-state": REPO_STUDY_USER_STATUS,
    "mod-dashboard": REPO_ONION_LEARNING,
}

# 压缩放置单元（4–9）：对齐高三九模块语义的子集
MODULES: list[dict[str, Any]] = [
    {
        "unit_id": "mod-shell",
        "title": "学习工具壳与导航",
        "expected_primary": REPO_ONION_LEARNING,
        "feature_ids": ["fp-nav", "fp-home"],
    },
    {
        "unit_id": "mod-practice",
        "title": "练习复用宿主",
        "expected_primary": REPO_ONION_PRACTICE,
        "feature_ids": ["fp-practice-entry", "fp-wrong-book"],
    },
    {
        "unit_id": "mod-course",
        "title": "课程与任务配置",
        "expected_primary": REPO_STUDY_COURSE,
        "feature_ids": ["fp-course-cfg", "fp-task-cfg"],
    },
    {
        "unit_id": "mod-state",
        "title": "学习状态与进度",
        "expected_primary": REPO_STUDY_USER_STATUS,
        "feature_ids": ["fp-progress", "fp-streak"],
    },
    {
        "unit_id": "mod-dashboard",
        "title": "提分看板",
        "expected_primary": REPO_ONION_LEARNING,
        "feature_ids": ["fp-dashboard"],
    },
]

FEATURES_FLAT: list[dict[str, Any]] = [
    {"id": fid, "module": m["unit_id"], "title": m["title"], "description": m["title"]}
    for m in MODULES
    for fid in m["feature_ids"]
]

# charter / history 信号（漏斗回归用）
CHARTER_SIGNALS: dict[str, Any] = {
    "domains": ["learning-tools", "gaosan-boost"],
    "unit_primary_hints": dict(UNIT_PRIMARY_EXPECTATIONS),
    "force_include": list(TEAM_CORE_IDS),
}

HISTORY_SIGNALS: dict[str, Any] = {
    "prior_primaries": {
        "mod-shell": REPO_ONION_LEARNING,
        "mod-practice": REPO_ONION_PRACTICE,
        "mod-course": REPO_STUDY_COURSE,
        "mod-state": REPO_STUDY_USER_STATUS,
    },
    "force_include_reasons": ["history_prior_gaosan"],
}

SPACE_META: dict[str, Any] = {
    "name": "Learning-tools (synthetic)",
    "space_id": "synthetic-learning-tools",
    "project_id": "synthetic-gaosan",
    "note": "活 Space 不可用时的 CI 合成宇宙；不读 DB",
}


def team_payload() -> dict[str, Any]:
    return {
        "status": "ok",
        "team_core": list(TEAM_CORE_IDS),
        "out_of_team": list(OUT_OF_TEAM_IDS),
        "membership": dict(MEMBERSHIP),
    }


def shortlist_universe() -> list[dict[str, Any]]:
    """短名单候选：team_core 优先 + 诱饵仅作对照（membership 标明 out_of_team）。"""
    rows: list[dict[str, Any]] = []
    for i, rid in enumerate(TEAM_CORE_IDS):
        rows.append(
            {
                "repository_id": rid,
                "rank": i + 1,
                "score": 1.0 - 0.05 * i,
                "team_membership": "team_core",
                "signals": {
                    "activity": 0.8,
                    "capability_coarse": 0.7,
                    "charter_domain": 0.9,
                },
                "force_include_reasons": ["charter", "baseline"],
            }
        )
    for j, rid in enumerate(OUT_OF_TEAM_IDS):
        rows.append(
            {
                "repository_id": rid,
                "rank": len(TEAM_CORE_IDS) + j + 1,
                "score": 0.3 - 0.05 * j,
                "team_membership": "out_of_team",
                "signals": {
                    "activity": 0.9,
                    "capability_coarse": 0.5,
                    "charter_domain": 0.1,
                },
                "force_include_reasons": [],
            }
        )
    return rows


def stub_v2_scores_by_unit() -> dict[str, dict[str, float]]:
    """hard_scope 内 stub 分数：期望 primary 最高，诱饵极低。"""
    out: dict[str, dict[str, float]] = {}
    for m in MODULES:
        scores = {rid: 0.2 for rid in TEAM_CORE_IDS}
        scores[m["expected_primary"]] = 0.99
        for bait in OUT_OF_TEAM_IDS:
            scores[bait] = 0.01
        out[m["unit_id"]] = scores
    return out


def build_funnel_units() -> list[Any]:
    """将合成 MODULES 转为 PlacementUnit 列表。"""
    from services.process_runtime.placement_units import PlacementUnit

    units: list[PlacementUnit] = []
    for m in MODULES:
        query = f"{m['title']} expected={m['expected_primary']}"
        if "学习状态" in str(m.get("title") or ""):
            query = f"学习状态与进度 {m['title']}"
        units.append(
            PlacementUnit(
                unit_id=str(m["unit_id"]),
                feature_ids=list(m.get("feature_ids") or []),
                module_names=[str(m.get("title") or m["unit_id"])],
                query_text=query,
                reuse_host_hints=[],
                feature_names=list(m.get("feature_ids") or []),
            )
        )
    return units


def make_scoped_v2_router() -> tuple[Any, list[dict[str, Any]]]:
    """Stub RepoRouterV2：按 unit query 对齐期望 primary；记录 repository_ids。"""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    call_log: list[dict[str, Any]] = []
    scores_by_unit = stub_v2_scores_by_unit()
    unit_by_token = {m["unit_id"]: m for m in MODULES}

    async def _route(query: str, **kwargs: Any) -> Any:
        call_log.append({"query": query, **kwargs})
        scope = list(kwargs.get("repository_ids") or [])
        matched = None
        q = str(query or "")
        for uid, m in unit_by_token.items():
            if uid in q or str(m.get("title") or "") in q:
                matched = m
                break
            if m["expected_primary"] in q:
                matched = m
                break
        if matched is None:
            if "学习状态" in q or "学习进度" in q:
                matched = next(
                    (m for m in MODULES if m["unit_id"] == "mod-state"), MODULES[0]
                )
            else:
                matched = MODULES[0]
        unit_scores = scores_by_unit.get(matched["unit_id"], {})
        ranked_ids = sorted(
            scope or list(TEAM_CORE_IDS),
            key=lambda rid: (-float(unit_scores.get(rid, 0.0)), rid),
        )
        candidates = [
            SimpleNamespace(
                repo_id=rid,
                repo_name=rid,
                score=float(unit_scores.get(rid, 0.05)),
                confidence="high",
                reasoning="synthetic",
                matched_node_paths=[],
            )
            for rid in ranked_ids
        ]
        return SimpleNamespace(
            candidates=candidates,
            router_version="v2-stub",
            auto_selected=True,
            degrade_reason="",
        )

    router = MagicMock()
    router.route = AsyncMock(side_effect=_route)
    return router, call_log
