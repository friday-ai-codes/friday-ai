"""MergedPlan §7 content schema 校验测试（Phase 40-01 Task 2，DOMAIN §7）。

覆盖 ``validate_merged_plan`` 的 4 个 behavior：合法 → (True, None)；缺 execution_plan
→ (False, err)；execution_plan 项缺 repository_id → (False, err)；半可信非 dict / 缺 title
→ (False, err) 不抛异常。execution_plan 子结构复用 validate_technical_plan（PF-02）。
"""

from __future__ import annotations

from typing import Any

from services.process_runtime import validate_merged_plan


def _valid_merged_plan() -> dict[str, Any]:
    """可复用的合法 §7 MergedPlan 工厂（2 仓 execution_plan + dependencies）。

    execution_plan 项满足 validate_technical_plan 必填子集
    （id/name/repository_id/repository_name/branch_strategy）。
    """
    return {
        "title": "跨仓登录改造",
        "summary": "后端加鉴权接口，前端接入",
        "api_contracts": [{"name": "POST /login", "repo": "backend"}],
        "dependency_dag": {"frontend": ["backend"], "backend": []},
        "data_migrations": [{"repository_id": "backend"}],
        "compat_risks": [],
        "release_order": ["backend", "frontend"],
        "rollback_plan": {"backend": "回滚迁移", "frontend": "回滚发布"},
        "execution_plan": [
            {
                "id": "t-backend",
                "name": "后端鉴权接口",
                "repository_id": "backend",
                "repository_name": "backend-repo",
                "branch_strategy": "feature",
                "coding_instruction": "实现 POST /login",
                "dependencies": [],
            },
            {
                "id": "t-frontend",
                "name": "前端登录页",
                "repository_id": "frontend",
                "repository_name": "frontend-repo",
                "branch_strategy": "feature",
                "coding_instruction": "接入 POST /login",
                "dependencies": ["t-backend"],
            },
        ],
    }


def test_valid_merged_plan_passes() -> None:
    """合法 §7 MergedPlan → (True, None)。"""
    valid, err = validate_merged_plan(_valid_merged_plan())
    assert valid is True
    assert err is None


def test_missing_execution_plan_rejected() -> None:
    """缺 execution_plan → (False, 含 'execution_plan' 的错误串)（委托 technical_plan）。"""
    content = _valid_merged_plan()
    del content["execution_plan"]
    valid, err = validate_merged_plan(content)
    assert valid is False
    assert err is not None
    assert "execution_plan" in err


def test_execution_plan_item_missing_repository_id_rejected() -> None:
    """execution_plan 某项缺 repository_id → (False, err)（technical_plan 子结构校验）。"""
    content = _valid_merged_plan()
    del content["execution_plan"][0]["repository_id"]
    valid, err = validate_merged_plan(content)
    assert valid is False
    assert err is not None


def test_non_dict_input_does_not_raise() -> None:
    """半可信非 dict 顶层 → (False, err)，不抛异常。"""
    valid, err = validate_merged_plan(["not", "a", "dict"])
    assert valid is False
    assert err is not None


def test_missing_title_rejected() -> None:
    """缺 title → (False, err)，不抛异常。"""
    content = _valid_merged_plan()
    del content["title"]
    valid, err = validate_merged_plan(content)
    assert valid is False
    assert err is not None
