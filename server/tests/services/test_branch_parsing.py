"""分支名 → work_item_id 反向解析守护测试（CURSOR-01）。"""

from __future__ import annotations

import pytest

from services.branch_parsing import parse_work_item_id_from_branch


@pytest.mark.parametrize(
    ("branch", "expected"),
    [
        ("feat/xxxx-m123-add-login", 123),
        ("feat/xxxx-m456", 456),
        ("FEAT/XXXX-M789-Slug", 789),  # 大小写不敏感
        ("feature/foo-m321-bar", 321),  # 宽松兜底：任意前缀
        ("hotfix-m42", 42),
        ("main", None),
        ("feat/no-work-item", None),
        ("", None),
        (None, None),
        ("feat/xxxx-mabc-slug", None),  # 非数字
    ],
)
def test_parse_work_item_id_from_branch(branch, expected) -> None:
    assert parse_work_item_id_from_branch(branch) == expected


def test_fail_soft_never_raises() -> None:
    # 各种畸形输入一律 fail-soft（返回 None 或数字，绝不抛）。
    for weird in ["///", "-m-", "m123", "feat/xxxx-m", "  "]:
        assert parse_work_item_id_from_branch(weird) in (None,) or isinstance(
            parse_work_item_id_from_branch(weird), int
        )
