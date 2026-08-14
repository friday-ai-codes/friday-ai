"""合成 Learning-tools Space 宇宙（Phase 132 / INT-02；D-06）。

提供 team_core（含四基线）、out_of_team 诱饵、membership、压缩 modules/features，
以及四角色 ↔ 四基线期望映射。不读活 DB / 无网络。
"""

from __future__ import annotations

from typing import Any

# 四基线规范 id（测试宇宙内用规范路径作 repository_id）
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

# 四角色 ↔ 四基线（fixture 对齐，非硬编码产品逻辑）
ROLE_EXPECTATIONS: dict[str, str] = {
    "app_shell": REPO_ONION_LEARNING,
    "practice_reuse_host": REPO_ONION_PRACTICE,
    "course_config": REPO_STUDY_COURSE,
    "learning_state": REPO_STUDY_USER_STATUS,
}

# 压缩放置单元（4–9）：对齐高三九模块语义的子集
MODULES: list[dict[str, Any]] = [
    {
        "unit_id": "mod-shell",
        "title": "学习工具壳与导航",
        "role": "app_shell",
        "expected_primary": REPO_ONION_LEARNING,
        "feature_ids": ["fp-nav", "fp-home"],
    },
    {
        "unit_id": "mod-practice",
        "title": "练习复用宿主",
        "role": "practice_reuse_host",
        "expected_primary": REPO_ONION_PRACTICE,
        "feature_ids": ["fp-practice-entry", "fp-wrong-book"],
    },
    {
        "unit_id": "mod-course",
        "title": "课程与任务配置",
        "role": "course_config",
        "expected_primary": REPO_STUDY_COURSE,
        "feature_ids": ["fp-course-cfg", "fp-task-cfg"],
    },
    {
        "unit_id": "mod-state",
        "title": "学习状态与进度",
        "role": "learning_state",
        "expected_primary": REPO_STUDY_USER_STATUS,
        "feature_ids": ["fp-progress", "fp-streak"],
    },
    {
        "unit_id": "mod-dashboard",
        "title": "提分看板",
        "role": "app_shell",
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
    "role_hints": dict(ROLE_EXPECTATIONS),
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


def role_map_payload() -> dict[str, Any]:
    roles: dict[str, Any] = {}
    per_repo: list[dict[str, Any]] = []
    for role, primary in ROLE_EXPECTATIONS.items():
        roles[role] = {
            "primary": primary,
            "supporting": [],
            "forbidden": list(OUT_OF_TEAM_IDS),
        }
        per_repo.append(
            {"repository_id": primary, "role": role, "assignment": "primary"}
        )
    return {
        "status": "ok",
        "roles": roles,
        "per_repo": per_repo,
        "placement_defaults": {"learning_state_writer_not_app_shell": True},
    }


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
