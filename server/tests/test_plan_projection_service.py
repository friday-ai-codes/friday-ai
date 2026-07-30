"""编排方案版本 → chat CodingPlan 投影的映射与幂等断言（Phase 109 · SPINE-01）。

分组（``-k`` 选择器）：

- ``mapping``：§7 → CodingPlan 四字段的纯映射（含 ``create → add`` 穷举与 fail-safe）
- ``conversation`` / ``idempotent`` / ``concurrent`` / ``new_version_keeps_old`` /
  ``traceability``：投影 service 的行为断言（Task 2 追加）
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from chat.plan_projection_service import (
    _ACTION_TO_CHANGE_TYPE,
    map_merged_plan_to_coding_plan,
)

# ============================================================================
# Helpers
# ============================================================================


def _task(
    *,
    repository_id: str,
    files: Any = None,
    name: str = "任务",
    task_id: str = "t1",
) -> dict[str, Any]:
    """构造一条 §7 ``execution_plan[]`` task（只填映射关心的键）。"""
    return {
        "id": task_id,
        "name": name,
        "repository_id": repository_id,
        "repository_name": f"repo-{repository_id}",
        "branch_strategy": "feature",
        "coding_instruction": f"实现 {name}",
        "files": [] if files is None else files,
    }


def _content(*tasks: dict[str, Any], title: str = "跨仓改造方案") -> dict[str, Any]:
    return {
        "title": title,
        "summary": "把 A 仓的接口改造后同步 B 仓调用方。",
        "execution_plan": list(tasks),
        "compat_risks": ["调用方需同步升级"],
    }


# ============================================================================
# mapping —— §7 → CodingPlan 四字段
# ============================================================================


def test_mapping_returns_exactly_four_keys() -> None:
    payload = map_merged_plan_to_coding_plan(_content(_task(repository_id="r1")))
    assert set(payload) == {
        "title",
        "tech_plan",
        "affected_files",
        "recommended_repository_ids",
    }
    assert payload["title"] == "跨仓改造方案"
    # tech_plan 由唯一渲染器 render_merged_plan_markdown 产出，非空且含标题。
    assert "跨仓改造方案" in payload["tech_plan"]


@pytest.mark.parametrize(
    ("action", "expected_change_type"),
    [
        ("create", "add"),
        ("modify", "modify"),
        ("delete", "delete"),
    ],
)
def test_mapping_action_to_change_type_enum_exhaustive(
    action: str, expected_change_type: str
) -> None:
    """三个已知 action 逐条穷举。

    每条**同时**断言 ``file_path`` 与 ``change_type`` —— 只断言 file_path 正是
    ``create → add`` 静默漂移（漏转换不崩、只静默显示成 create）的典型警示信号。
    """
    payload = map_merged_plan_to_coding_plan(
        _content(
            _task(
                repository_id="r1",
                files=[{"path": "src/api.py", "action": action}],
            )
        )
    )
    assert payload["affected_files"] == [
        {"file_path": "src/api.py", "change_type": expected_change_type}
    ]
    entry = payload["affected_files"][0]
    assert entry["file_path"] == "src/api.py"
    assert entry["change_type"] == expected_change_type


def test_mapping_action_table_is_exactly_create_add() -> None:
    """转换表本体的形状断言（防后人改表时把 create 悄悄映成 create）。"""
    assert _ACTION_TO_CHANGE_TYPE == {
        "create": "add",
        "modify": "modify",
        "delete": "delete",
    }


@pytest.mark.parametrize(
    "file_entry",
    [
        {"path": "src/renamed.py", "action": "rename"},  # 未知 action
        {"path": "src/renamed.py"},  # 缺 action 键
        {"path": "src/renamed.py", "action": None},  # action 为 None
    ],
)
def test_mapping_unknown_or_missing_action_falls_back_to_modify(
    file_entry: dict[str, Any],
) -> None:
    payload = map_merged_plan_to_coding_plan(
        _content(_task(repository_id="r1", files=[file_entry]))
    )
    assert payload["affected_files"] == [{"file_path": "src/renamed.py", "change_type": "modify"}]
    assert payload["affected_files"][0]["change_type"] == "modify"


def test_mapping_aggregates_files_across_repositories() -> None:
    """多仓聚合：两个 task 分属两仓 → 文件全收、repo id 按 task 顺序去重保序。"""
    repo_a, repo_b = str(uuid.uuid4()), str(uuid.uuid4())
    payload = map_merged_plan_to_coding_plan(
        _content(
            _task(
                repository_id=repo_a,
                task_id="t1",
                files=[
                    {"path": "a/service.py", "action": "modify"},
                    {"path": "a/new_module.py", "action": "create"},
                ],
            ),
            _task(
                repository_id=repo_b,
                task_id="t2",
                files=[{"path": "b/caller.ts", "action": "modify"}],
            ),
            # 第三个 task 回到 repo_a → repo id 不重复出现。
            _task(
                repository_id=repo_a,
                task_id="t3",
                files=[{"path": "a/legacy.py", "action": "delete"}],
            ),
        )
    )
    assert payload["affected_files"] == [
        {"file_path": "a/service.py", "change_type": "modify"},
        {"file_path": "a/new_module.py", "change_type": "add"},
        {"file_path": "b/caller.ts", "change_type": "modify"},
        {"file_path": "a/legacy.py", "change_type": "delete"},
    ]
    # 保序即保 release_order 意图：repo_a 先出现。
    assert payload["recommended_repository_ids"] == [repo_a, repo_b]


def test_mapping_dedupes_repeated_path_action_and_keeps_order() -> None:
    """同一 (path, action) 在两个 task 重复 → 只留一条且保序。"""
    payload = map_merged_plan_to_coding_plan(
        _content(
            _task(
                repository_id="r1",
                task_id="t1",
                files=[
                    {"path": "shared/util.py", "action": "modify"},
                    {"path": "r1/only.py", "action": "create"},
                ],
            ),
            _task(
                repository_id="r2",
                task_id="t2",
                files=[
                    {"path": "shared/util.py", "action": "modify"},
                    {"path": "r2/only.py", "action": "modify"},
                ],
            ),
        )
    )
    paths = [f["file_path"] for f in payload["affected_files"]]
    assert paths == ["shared/util.py", "r1/only.py", "r2/only.py"]
    assert paths.count("shared/util.py") == 1
    # 同 path 不同 action 视为两条（change_type 不同，语义不同）。
    payload2 = map_merged_plan_to_coding_plan(
        _content(
            _task(
                repository_id="r1",
                files=[
                    {"path": "shared/util.py", "action": "modify"},
                    {"path": "shared/util.py", "action": "delete"},
                ],
            )
        )
    )
    assert payload2["affected_files"] == [
        {"file_path": "shared/util.py", "change_type": "modify"},
        {"file_path": "shared/util.py", "change_type": "delete"},
    ]


@pytest.mark.parametrize(
    "hostile_content",
    [
        None,
        "不是 dict 而是字符串",
        {"title": "无 execution_plan 键"},
        {"title": "execution_plan 非 list", "execution_plan": {"oops": 1}},
        {"execution_plan": ["task 不是 dict", 42, None]},
        {"execution_plan": [{"repository_id": "r1", "files": "files 非 list"}]},
        {"execution_plan": [{"repository_id": "r1", "files": ["项非 dict", 7]}]},
        {"execution_plan": [{"repository_id": "r1", "files": [{"path": "", "action": "create"}]}]},
        {"execution_plan": [{"repository_id": "", "files": [{"action": "create"}]}]},
    ],
)
def test_mapping_fail_safe_on_semi_trusted_content(hostile_content: Any) -> None:
    """半可信输入恒不抛异常，且返回结构合法（LLM 产物防御，T-109-03-04）。"""
    payload = map_merged_plan_to_coding_plan(hostile_content)
    assert set(payload) == {
        "title",
        "tech_plan",
        "affected_files",
        "recommended_repository_ids",
    }
    assert isinstance(payload["title"], str)
    assert isinstance(payload["tech_plan"], str)
    # 文件侧一律降级为空 list（没有任何一条能凑出合法 file_path）。
    assert payload["affected_files"] == []
    # repository_id 是独立的一支：``files`` 非法不该连带丢掉合法的 repo id
    # （多仓 fan-out 的目标仓仍可用），只断言结构合法。
    assert isinstance(payload["recommended_repository_ids"], list)
    assert all(isinstance(r, str) for r in payload["recommended_repository_ids"])


@pytest.mark.parametrize("hostile_content", [None, 42, "字符串", [], {}])
def test_mapping_fail_safe_top_level_non_dict_yields_empty_lists(
    hostile_content: Any,
) -> None:
    """顶层完全不可用时两个 list 都为空、``tech_plan`` 为空串（不抛）。"""
    payload = map_merged_plan_to_coding_plan(hostile_content)
    assert payload["title"] == ""
    assert payload["tech_plan"] == ""
    assert payload["affected_files"] == []
    assert payload["recommended_repository_ids"] == []
