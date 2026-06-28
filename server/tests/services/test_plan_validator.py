"""PlanValidator 5 项跨仓校验测试（Phase 40-01 Task 3，DOMAIN §7）。

每项校验一个「触发违例」用例 + 合法 MergedPlan 全过 + 半可信输入不抛异常。
让架构师「不只是更贵的总结器」（MERGE-02 拦截 + MERGE-03 跨仓依赖建模）。
"""

from __future__ import annotations

from typing import Any

from services.process_runtime import validate_plan


def _valid_merged_plan() -> dict[str, Any]:
    """合法 §7 MergedPlan：契约一致 + 无环 + 迁移/发布顺序合依赖 + 回滚覆盖。

    依赖关系：frontend 依赖 backend（dependency_dag）；backend 暴露 POST /login，
    frontend 依赖该契约。
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
                "api_contracts_exposed": ["POST /login"],
            },
            {
                "id": "t-frontend",
                "name": "前端登录页",
                "repository_id": "frontend",
                "repository_name": "frontend-repo",
                "branch_strategy": "feature",
                "coding_instruction": "接入 POST /login",
                "dependencies": ["t-backend"],
                "dependencies_on_other_repos": ["POST /login"],
            },
        ],
    }


def _checks(report: dict) -> set[str]:
    return {e.get("check") for e in report.get("errors", [])}


def test_valid_merged_plan_passes() -> None:
    """合法 MergedPlan → valid=True、errors 空。"""
    report = validate_plan(_valid_merged_plan())
    assert report["valid"] is True
    assert report["errors"] == []


def test_contract_consistency_violation() -> None:
    """依赖引用未暴露的契约 → contract_consistency error。"""
    content = _valid_merged_plan()
    content["execution_plan"][1]["dependencies_on_other_repos"] = ["GET /missing"]
    report = validate_plan(content)
    assert report["valid"] is False
    assert "contract_consistency" in _checks(report)


def test_dependency_cycle_violation() -> None:
    """dependency_dag 成环 → dependency_cycle error。"""
    content = _valid_merged_plan()
    content["dependency_dag"] = {"a": ["b"], "b": ["a"]}
    report = validate_plan(content)
    assert report["valid"] is False
    assert "dependency_cycle" in _checks(report)


def test_migration_order_violation() -> None:
    """迁移顺序倒置（被依赖方迁移排在依赖方之后）→ migration_order error。"""
    content = _valid_merged_plan()
    # frontend 依赖 backend → backend 迁移须先行；此处倒置
    content["data_migrations"] = [
        {"repository_id": "frontend"},
        {"repository_id": "backend"},
    ]
    report = validate_plan(content)
    assert report["valid"] is False
    assert "migration_order" in _checks(report)


def test_release_order_violation() -> None:
    """发布顺序违反依赖（依赖方先发）→ release_order error。"""
    content = _valid_merged_plan()
    # frontend 依赖 backend，但 frontend 先发
    content["release_order"] = ["frontend", "backend"]
    report = validate_plan(content)
    assert report["valid"] is False
    assert "release_order" in _checks(report)


def test_rollback_completeness_empty() -> None:
    """rollback_plan 为空 → rollback_completeness error。"""
    content = _valid_merged_plan()
    content["rollback_plan"] = {}
    report = validate_plan(content)
    assert report["valid"] is False
    assert "rollback_completeness" in _checks(report)


def test_rollback_completeness_missing_repo() -> None:
    """rollback_plan 未覆盖某仓 → rollback_completeness error。"""
    content = _valid_merged_plan()
    content["rollback_plan"] = {"backend": "回滚迁移"}  # 缺 frontend
    report = validate_plan(content)
    assert report["valid"] is False
    assert "rollback_completeness" in _checks(report)


def test_empty_execution_plan_rejected() -> None:
    """WR-01：空 execution_plan（零可执行任务）→ non_empty_plan error。"""
    content = _valid_merged_plan()
    content["execution_plan"] = []
    report = validate_plan(content)
    assert report["valid"] is False
    assert "non_empty_plan" in _checks(report)


def test_missing_execution_plan_rejected() -> None:
    """WR-01：缺 execution_plan 字段（当空）→ non_empty_plan error。"""
    content = _valid_merged_plan()
    del content["execution_plan"]
    report = validate_plan(content)
    assert report["valid"] is False
    assert "non_empty_plan" in _checks(report)


def test_malformed_dependency_dag_rejected() -> None:
    """WR-02：dependency_dag 形状非法（边列表而非邻接表 dict）→ dependency_cycle error，
    而非被静默降级为空跳过（false-pass）。"""
    content = _valid_merged_plan()
    content["dependency_dag"] = [["a", "b"], ["b", "a"]]  # 边列表，非 dict
    report = validate_plan(content)
    assert report["valid"] is False
    assert "dependency_cycle" in _checks(report)


def test_malformed_data_migrations_rejected() -> None:
    """WR-02：data_migrations 形状非法（非 list）→ migration_order error，不静默跳过。"""
    content = _valid_merged_plan()
    content["data_migrations"] = {"backend": 1}  # 应为 list
    report = validate_plan(content)
    assert report["valid"] is False
    assert "migration_order" in _checks(report)


def test_malformed_release_order_rejected() -> None:
    """WR-02：release_order 形状非法（非 list）→ release_order error，不静默跳过。"""
    content = _valid_merged_plan()
    content["release_order"] = "backend,frontend"  # 应为 list
    report = validate_plan(content)
    assert report["valid"] is False
    assert "release_order" in _checks(report)


def test_non_dict_input_does_not_raise() -> None:
    """半可信非 dict 顶层 → valid=False，不抛异常。"""
    report = validate_plan(["not", "a", "dict"])
    assert report["valid"] is False
    assert isinstance(report["errors"], list)


def test_missing_fields_does_not_raise() -> None:
    """缺字段当空集处理，不抛异常（缺 execution_plan/dependency_dag 等）。"""
    report = validate_plan({"title": "x"})
    assert isinstance(report["valid"], bool)
    assert isinstance(report["errors"], list)
    assert isinstance(report["warnings"], list)
