"""blueprint_execution 派生器纯函数测试（PLAN 111-01 Task 2，SCHEMA-06）。

覆盖：按仓聚合与五必填字段 / 整文档过 validate_technical_plan / 确定性逐字节一致 /
remove→delete 映射 / 跨仓 depends_on 投影 / repository_name 回退 / 空 items。
"""

from __future__ import annotations

import json

from services.process_runtime.blueprint_execution import (
    DEFAULT_BRANCH_STRATEGY,
    derive_execution_plan,
    derive_technical_plan_document,
)
from tests.helpers.blueprint_samples import make_blueprint
from workflows.schemas.technical_plan import validate_technical_plan

_REQUIRED_TASK_FIELDS = ("id", "name", "repository_id", "repository_name", "branch_strategy")


def test_derive_groups_by_repo_with_required_fields():
    plan = derive_execution_plan(make_blueprint())
    # 样例 items 分布在两个 direct 仓（repo-backend / repo-frontend）→ 两个 task
    assert len(plan) == 2
    for task in plan:
        for field in _REQUIRED_TASK_FIELDS:
            assert task.get(field), f"task 缺必填字段 {field}"
        assert task["branch_strategy"] == DEFAULT_BRANCH_STRATEGY
    # repository_name 从 repo_associations 快照取
    by_repo = {task["repository_id"]: task for task in plan}
    assert by_repo["repo-backend"]["repository_name"] == "onion-practice"
    assert by_repo["repo-frontend"]["repository_name"] == "study-app"
    # wave 排序：repo-backend（wave 1）先于 repo-frontend（wave 2）
    assert [task["repository_id"] for task in plan] == ["repo-backend", "repo-frontend"]


def test_derive_document_passes_validate_technical_plan():
    doc, err = derive_technical_plan_document(make_blueprint())
    assert err is None
    assert doc is not None
    assert validate_technical_plan(doc)[0] is True
    assert doc["title"] == "习题生成蓝图样例"
    assert doc["summary"]


def test_derive_deterministic_byte_identical():
    first = json.dumps(derive_execution_plan(make_blueprint()), sort_keys=True, ensure_ascii=False)
    second = json.dumps(derive_execution_plan(make_blueprint()), sort_keys=True, ensure_ascii=False)
    assert first == second
    doc1, _ = derive_technical_plan_document(make_blueprint())
    doc2, _ = derive_technical_plan_document(make_blueprint())
    assert json.dumps(doc1, sort_keys=True, ensure_ascii=False) == json.dumps(
        doc2, sort_keys=True, ensure_ascii=False
    )


def test_remove_action_mapped_to_delete():
    plan = derive_execution_plan(make_blueprint())
    backend = next(task for task in plan if task["repository_id"] == "repo-backend")
    actions = {(f["path"], f["action"]) for f in backend["files"]}
    assert ("src/api/legacy_generate.py", "delete") in actions
    assert all(action != "remove" for _path, action in actions)
    # note 字段保留
    legacy = next(f for f in backend["files"] if f["path"] == "src/api/legacy_generate.py")
    assert legacy["note"] == "移除旧入口"


def test_cross_repo_depends_on_projected_to_dependencies():
    plan = derive_execution_plan(make_blueprint())
    by_repo = {task["repository_id"]: task for task in plan}
    # impl_02（repo-frontend）depends_on impl_01（repo-backend）
    assert by_repo["repo-frontend"]["dependencies"] == ["task_repo-backend"]
    assert by_repo["repo-backend"]["dependencies"] == []


def test_missing_repo_association_falls_back_to_repository_id():
    content = make_blueprint()
    content["implementation_overview"]["items"].append(
        {
            "id": "impl_03",
            "feature_point_id": "fp_01",
            "repository_id": "repo-ghost",
            "change_type": "modify",
            "title": "无关联快照的实现项",
            "wave": 3,
        }
    )
    plan = derive_execution_plan(content)
    ghost = next(task for task in plan if task["repository_id"] == "repo-ghost")
    assert ghost["repository_name"] == "repo-ghost"
    doc, err = derive_technical_plan_document(content)
    assert err is None
    assert validate_technical_plan(doc)[0] is True


def test_empty_items_yields_empty_plan_and_valid_document():
    content = make_blueprint()
    content["implementation_overview"]["items"] = []
    assert derive_execution_plan(content) == []
    # technical_plan schema 对 execution_plan 无 minItems 约束：空数组文档合法
    doc, err = derive_technical_plan_document(content)
    assert err is None
    assert doc is not None
    assert doc["execution_plan"] == []


def test_invalid_depends_on_reference_filtered():
    content = make_blueprint()
    content["implementation_overview"]["items"][1]["depends_on"] = ["impl_nonexistent"]
    plan = derive_execution_plan(content)
    by_repo = {task["repository_id"]: task for task in plan}
    assert by_repo["repo-frontend"]["dependencies"] == []


def test_coding_instruction_assembles_blocks():
    plan = derive_execution_plan(make_blueprint())
    by_repo = {task["repository_id"]: task for task in plan}
    backend_instruction = by_repo["repo-backend"]["coding_instruction"]
    assert "## 新增习题生成接口（create）" in backend_instruction
    assert "```python" in backend_instruction  # pseudocode 围栏
    assert "测试策略：" in backend_instruction
    frontend_instruction = by_repo["repo-frontend"]["coding_instruction"]
    assert "- 新增生成按钮" in frontend_instruction  # list 型 text 逐条拼接
    assert "与既有功能配合：" in frontend_instruction


def test_non_dict_blueprint_defensive():
    assert derive_execution_plan(None) == []
    doc, err = derive_technical_plan_document(None)
    assert doc is None
    assert err
