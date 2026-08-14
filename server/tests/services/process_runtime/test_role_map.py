"""Phase 129 角色图单测（ROLE-01/02/03；D-02、D-11~D-14）。"""

from __future__ import annotations

import pytest

from services.process_runtime.role_map import (
    PLACEMENT_DEFAULTS,
    RepoRole,
    build_role_map,
)


def test_four_roles_each_get_primary():
    """四仓章程贴近四角色 → 各有 primary。"""
    charters = {
        "r-shell": {
            "owned_domains": [{"domain": "App 壳导航容器", "status": "implemented"}],
            "boundaries": [],
            "source": "confirmed",
            "version": 1,
        },
        "r-practice": {
            "owned_domains": [{"domain": "做题复用宿主练习引擎", "status": "implemented"}],
            "boundaries": [],
            "source": "confirmed",
            "version": 1,
        },
        "r-course": {
            "owned_domains": [{"domain": "课程配置大纲目录", "status": "implemented"}],
            "boundaries": [],
            "source": "confirmed",
            "version": 1,
        },
        "r-state": {
            "owned_domains": [{"domain": "学习状态进度记录", "status": "implemented"}],
            "boundaries": [],
            "source": "confirmed",
            "version": 1,
        },
    }
    result = build_role_map(
        shortlist_repos=["r-shell", "r-practice", "r-course", "r-state"],
        charters_by_repo=charters,
    )
    roles = result.roles if hasattr(result, "roles") else result["roles"]
    assert roles[RepoRole.APP_SHELL.value]["primary"] == "r-shell"
    assert roles[RepoRole.PRACTICE_REUSE_HOST.value]["primary"] == "r-practice"
    assert roles[RepoRole.COURSE_CONFIG.value]["primary"] == "r-course"
    assert roles[RepoRole.LEARNING_STATE.value]["primary"] == "r-state"
    assert (result.status if hasattr(result, "status") else result["status"]) == "ok"


def test_boundary_without_override_not_primary():
    """violated_boundaries 非空且无 override → 不得 primary。"""
    charters = {
        "r-shell": {
            "owned_domains": [{"domain": "App 壳", "status": "implemented"}],
            "boundaries": [{"rule": "禁止承接学习状态写入"}],
            "source": "confirmed",
            "version": 1,
        },
    }
    result = build_role_map(
        shortlist_repos=["r-shell"],
        charters_by_repo=charters,
        violated_boundaries_by_repo={"r-shell": ["禁止承接学习状态写入"]},
        query_terms=["学习状态写入"],
    )
    per_repo = result.per_repo if hasattr(result, "per_repo") else result["per_repo"]
    entry = next(e for e in per_repo if e["repository_id"] == "r-shell")
    assert entry["assignment"] != "primary"
    assert entry["assignment"] in ("forbidden", "supporting")
    roles = result.roles if hasattr(result, "roles") else result["roles"]
    # 不得作为该角色 primary
    for role_bucket in roles.values():
        assert role_bucket.get("primary") != "r-shell"


def test_override_reason_allows_non_forbidden():
    """带 override_reasons 时可保留非 forbidden（对齐 resolve_boundary_override）。"""
    charters = {
        "r-shell": {
            "owned_domains": [{"domain": "App 壳", "status": "implemented"}],
            "boundaries": [{"rule": "禁止承接学习状态写入"}],
            "source": "confirmed",
            "version": 1,
        },
    }
    result = build_role_map(
        shortlist_repos=["r-shell"],
        charters_by_repo=charters,
        violated_boundaries_by_repo={"r-shell": ["禁止承接学习状态写入"]},
        override_reasons={"r-shell": "本次需求确需壳层转发状态事件"},
    )
    per_repo = result.per_repo if hasattr(result, "per_repo") else result["per_repo"]
    entry = next(e for e in per_repo if e["repository_id"] == "r-shell")
    assert entry["assignment"] != "forbidden"
    assert entry.get("boundary_override_reason")


def test_unmapped_owned_domain_clarify():
    """章程拥有域无法映射四枚举 → clarify(unmapped_role)。"""
    charters = {
        "r-x": {
            "owned_domains": [{"domain": "量子纠缠结算中台", "status": "implemented"}],
            "boundaries": [],
            "source": "confirmed",
            "version": 1,
        },
    }
    result = build_role_map(
        shortlist_repos=["r-x"],
        charters_by_repo=charters,
    )
    status = result.status if hasattr(result, "status") else result["status"]
    reason = result.clarify_reason if hasattr(result, "clarify_reason") else result["clarify_reason"]
    assert status == "clarify"
    assert reason == "unmapped_role"


def test_placement_defaults_learning_state_not_app_shell():
    """placement_defaults 含 learning_state 写方不得默认 app_shell primary。"""
    assert PLACEMENT_DEFAULTS.get("learning_state_writer_not_app_shell") is True
    result = build_role_map(shortlist_repos=[], charters_by_repo={})
    defaults = (
        result.placement_defaults
        if hasattr(result, "placement_defaults")
        else result["placement_defaults"]
    )
    assert defaults.get("learning_state_writer_not_app_shell") is True


def test_repo_role_enum_exactly_four():
    """D-02/D5：恰好四角色枚举。"""
    assert {r.value for r in RepoRole} == {
        "app_shell",
        "practice_reuse_host",
        "course_config",
        "learning_state",
    }
